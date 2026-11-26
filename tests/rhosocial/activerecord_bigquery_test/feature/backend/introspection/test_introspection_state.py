# tests/rhosocial/activerecord_bigquery_test/feature/backend/introspection/test_introspection_state.py
"""The neutral object-state answers, from canned ``INFORMATION_SCHEMA`` rows.

No connection: the executor answers each question from a catalog fixture
keyed by the view a statement names, and the tests read the neutral
dataclasses the manager returns. What is pinned here is the mapping the
backend owns:

* an unpartitioned table answers an empty ``PartitionState`` -- its
  ``scheme`` is ``None`` and its ``bounds`` empty; the catalog's single
  ``partition_id = NULL`` row is "no partitions", never a bound;
* a column-, range- or ingestion-time-partitioned table answers
  ``PartitionScheme.RANGE``, with the partitioning column (or the
  ingestion-time pseudo column) as the key;
* ``TableState`` carries the catalog's table kind, the ``OPTIONS`` rows and
  the description as the comment;
* constraints answer ``enforced=False``/``validated=False``, because
  BigQuery declares keys without enforcing them;
* the families BigQuery has no catalogue for -- indexes, sequences and
  engine-created objects -- stay core's refusal rather than an empty list
  that would read as a real answer.

Docs:
* TABLES https://cloud.google.com/bigquery/docs/information-schema-tables
* COLUMNS https://cloud.google.com/bigquery/docs/information-schema-columns
* TABLE_OPTIONS https://cloud.google.com/bigquery/docs/information-schema-table-options
* PARTITIONS https://cloud.google.com/bigquery/docs/information-schema-partitions
* TABLE_CONSTRAINTS https://cloud.google.com/bigquery/docs/information-schema-table-constraints
"""

import asyncio

import pytest
from rhosocial.activerecord.backend.dialect.exceptions import ProtocolNotImplementedError
from rhosocial.activerecord.backend.introspection.errors import ObjectNotFoundError
from rhosocial.activerecord.backend.introspection.types import (
    ItemKind,
    PartitionScheme,
    PartitionState,
)

from rhosocial.activerecord.backend.impl.bigquery.config import (
    BigQueryConnectionConfig,
)
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect
from rhosocial.activerecord.backend.impl.bigquery.introspection import (
    AsyncBigQueryIntrospector,
    BigQueryIntrospector,
)


class _BackendStandIn:
    def __init__(self, project="my-project", dataset="my_dataset"):
        self.dialect = BigQueryDialect()
        self.config = BigQueryConnectionConfig(project=project, dataset=dataset)
        self._version = (3, 0, 0)


class _Catalog:
    """One canned answer per catalogue view, chosen by the view the SQL names."""

    def __init__(
        self,
        tables=(),
        columns=(),
        options=(),
        partitions=(),
        constraints=(),
        datasets=(),
        routines=(),
    ):
        self.tables = list(tables)
        self.columns = list(columns)
        self.options = list(options)
        self.partitions = list(partitions)
        self.constraints = list(constraints)
        self.datasets = list(datasets)
        self.routines = list(routines)

    def rows_for(self, sql):
        # The order matters: TABLE_OPTIONS/TABLE_CONSTRAINTS/PARTITIONS all
        # carry "TABLE..." in their names, and TABLES must be matched last.
        if "SCHEMATA" in sql:
            return self.datasets
        if "TABLE_OPTIONS" in sql:
            return self.options
        if "PARTITIONS" in sql:
            return self.partitions
        if "TABLE_CONSTRAINTS" in sql:
            return self.constraints
        if "ROUTINES" in sql:
            return self.routines
        if "COLUMNS" in sql:
            return self.columns
        if "TABLES" in sql:
            return self.tables
        return []


class _CatalogExecutor:
    def __init__(self, catalog):
        self.catalog = catalog
        self.questions = []

    def execute(self, sql, params=()):
        self.questions.append(sql)
        return list(self.catalog.rows_for(sql))


class _AsyncCatalogExecutor(_CatalogExecutor):
    async def execute(self, sql, params=()):
        self.questions.append(sql)
        return list(self.catalog.rows_for(sql))


def _introspector(catalog):
    return BigQueryIntrospector(_BackendStandIn(), _CatalogExecutor(catalog))


def _async_introspector(catalog):
    return AsyncBigQueryIntrospector(_BackendStandIn(), _AsyncCatalogExecutor(catalog))


def _table(name, table_type="BASE TABLE", **extra):
    row = {"table_name": name, "table_type": table_type}
    row.update(extra)
    return row


def _column(name, ordinal, **extra):
    row = {
        "column_name": name,
        "ordinal_position": ordinal,
        "data_type": "INT64",
        "is_nullable": "YES",
        "is_hidden": "NO",
    }
    row.update(extra)
    return row


def _option(name, value, option_type="STRING"):
    return {"option_name": name, "option_value": value, "option_type": option_type}


def _partition(partition_id, **extra):
    row = {"table_name": "orders", "partition_id": partition_id}
    row.update(extra)
    return row


# ---------------------------------------------------------------------------
# Partition state
# ---------------------------------------------------------------------------


def test_a_null_partition_row_is_not_a_partition():
    """An unpartitioned table's one row has ``partition_id = NULL``.

    That row is the catalog saying "no partitions". It becomes the empty
    ``PartitionState`` whose ``scheme`` is ``None`` -- core's single neutral
    answer -- rather than a bound, and never a ``None`` object.
    """
    introspector = _introspector(
        _Catalog(
            tables=[_table("orders")],
            columns=[_column("id", 1)],
            partitions=[_partition(None, total_rows=3)],
        )
    )

    state = introspector.get_partition_state("orders", "my_dataset")

    assert isinstance(state, PartitionState)
    assert state.scheme is None
    assert state.bounds == ()


def test_a_column_partitioned_table_answers_range_with_its_key():
    introspector = _introspector(
        _Catalog(
            tables=[_table("orders")],
            columns=[
                _column("id", 1),
                _column("created", 2, is_partitioning_column="YES", data_type="DATE"),
                _column("tier", 3, clustering_ordinal_position=1),
            ],
            options=[
                _option("require_partition_filter", "true", "BOOL"),
                _option("partition_expiration_days", "90", "FLOAT64"),
            ],
            partitions=[
                _partition("20260101", total_rows=5, total_billable_bytes=512),
                _partition("__NULL__", total_rows=0),
            ],
        )
    )

    state = introspector.get_partition_state("orders", "my_dataset")

    assert state is not None
    assert state.scheme == PartitionScheme.RANGE
    assert state.key_columns == ("created",)
    assert state.key_expression == "created"
    assert [bound.name for bound in state.bounds] == ["20260101", "__NULL__"]
    assert state.raw["require_partition_filter"] is True
    assert state.raw["clustering_columns"] == ["tier"]
    assert state.raw["partition_expiration_days"] == 90
    assert state.raw["ingestion_time_partitioned"] is False


def test_an_ingestion_time_table_with_no_rows_is_still_partitioned():
    """The pseudo column is the only signal once the table holds no rows.

    ``COLUMNS`` reports ``_PARTITIONTIME`` with ``is_hidden = 'YES'``; the
    parsed column list drops it, so the answer must come from the raw
    rows. Without it, an empty ingestion-time table would read as
    unpartitioned -- a false answer, not an absence of one.
    """
    introspector = _introspector(
        _Catalog(
            tables=[_table("orders")],
            columns=[
                _column("id", 1),
                _column("_PARTITIONTIME", None, is_hidden="YES", data_type="TIMESTAMP"),
                _column("_PARTITIONDATE", None, is_hidden="YES", data_type="DATE"),
            ],
        )
    )

    state = introspector.get_partition_state("orders", "my_dataset")

    assert state is not None
    assert state.scheme == PartitionScheme.RANGE
    assert state.key_expression == "_PARTITIONTIME"
    assert state.key_columns == ()
    assert state.raw["ingestion_time_partitioned"] is True
    assert state.raw["pseudo_columns"] == ["_PARTITIONTIME", "_PARTITIONDATE"]
    assert state.bounds == ()


def test_partition_options_alone_identify_a_partitioned_table():
    """An empty column-partitioned table with no partition rows still answers.

    ``TABLE_OPTIONS`` can only carry ``require_partition_filter`` on a
    partitioned table, so its presence is a partition signal even when
    ``PARTITIONS`` is empty and ``COLUMNS`` names no partitioning column
    (an endpoint that does not report it).
    """
    introspector = _introspector(
        _Catalog(
            tables=[_table("orders")],
            columns=[_column("id", 1)],
            options=[_option("require_partition_filter", "false", "BOOL")],
        )
    )

    state = introspector.get_partition_state("orders", "my_dataset")

    assert state is not None
    assert state.scheme == PartitionScheme.RANGE
    assert state.bounds == ()
    assert state.raw["require_partition_filter"] is False


def test_stats_are_filled_only_when_asked_for():
    catalog = _Catalog(
        tables=[_table("orders")],
        columns=[_column("id", 1), _column("created", 2, is_partitioning_column="YES")],
        partitions=[_partition("20260101", total_rows=5, total_billable_bytes=512)],
    )
    executor = _CatalogExecutor(catalog)
    introspector = BigQueryIntrospector(_BackendStandIn(), executor)

    without = introspector.get_partition_state("orders", "my_dataset")
    with_stats = introspector.get_partition_state("orders", "my_dataset", include_stats=True)

    assert without is not None and with_stats is not None
    assert without.bounds[0].row_count is None
    assert without.bounds[0].size_bytes is None
    assert with_stats.bounds[0].row_count == 5
    assert with_stats.bounds[0].size_bytes == 512
    # Asking for stats reuses the same catalog answers: no statistics
    # question was run and no SQL was issued twice.
    assert len(executor.questions) == len(set(executor.questions))
    assert with_stats.scheme == without.scheme


def test_a_missing_table_is_an_error_not_an_unpartitioned_answer():
    introspector = _introspector(_Catalog(tables=[_table("payments")], columns=[_column("id", 1)]))

    with pytest.raises(ObjectNotFoundError) as caught:
        introspector.get_partition_state("orders", "my_dataset")

    assert "orders" in str(caught.value)


# ---------------------------------------------------------------------------
# Table state
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "catalog_spelling, kind, traits",
    [
        ("BASE TABLE", "regular", ()),
        ("CLONE", "regular", ("clone",)),
        ("SNAPSHOT", "regular", ("snapshot",)),
        ("EXTERNAL", "external", ()),
        ("VIEW", "view", ()),
        ("MATERIALIZED VIEW", "materialized_view", ()),
    ],
)
def test_table_state_maps_each_documented_type(catalog_spelling, kind, traits):
    introspector = _introspector(_Catalog(tables=[_table("orders", catalog_spelling)]))

    state = introspector.get_table_state("orders", "my_dataset")

    assert state.kind == kind
    assert state.traits == traits
    assert state.raw["bigquery_table_type"] == catalog_spelling


def test_table_state_carries_options_comment_and_partitioning():
    introspector = _introspector(
        _Catalog(
            tables=[_table("orders", default_collation_name="und:ci")],
            columns=[_column("id", 1), _column("created", 2, is_partitioning_column="YES")],
            options=[
                _option("description", "Order headers"),
                _option("require_partition_filter", "true", "BOOL"),
                _option("compression", "GZIP"),
            ],
            partitions=[_partition("20260101")],
        )
    )

    state = introspector.get_table_state("orders", "my_dataset")

    assert state.comment == "Order headers"
    assert state.storage.collation == "und:ci"
    assert state.storage.compression == "GZIP"
    # BigQuery's managed storage has no engine, charset or tablespace.
    assert state.storage.engine is None
    assert state.storage.charset is None
    assert state.storage.tablespace is None
    assert state.storage.raw["require_partition_filter"] == "true"
    assert isinstance(state.partitioning, PartitionState)
    assert state.partitioning.scheme == PartitionScheme.RANGE


def test_table_state_for_an_unpartitioned_table_carries_an_empty_state():
    introspector = _introspector(
        _Catalog(
            tables=[_table("orders")],
            columns=[_column("id", 1)],
            partitions=[_partition(None)],
        )
    )

    state = introspector.get_table_state("orders", "my_dataset")

    assert isinstance(state.partitioning, PartitionState)
    assert state.partitioning.scheme is None
    assert state.partitioning.bounds == ()


def test_table_state_for_a_missing_table_raises():
    introspector = _introspector(_Catalog(tables=[_table("payments")]))

    with pytest.raises(ObjectNotFoundError):
        introspector.get_table_state("orders", "my_dataset")


# ---------------------------------------------------------------------------
# Constraints, schemas, shared objects
# ---------------------------------------------------------------------------


def test_constraints_answer_their_enforcement_state():
    """BigQuery declares primary and foreign keys without enforcing them."""
    introspector = _introspector(
        _Catalog(
            tables=[_table("orders")],
            constraints=[
                {
                    "constraint_name": "pk_orders",
                    "constraint_type": "PRIMARY KEY",
                    "column_name": "id",
                    "ordinal_position": 1,
                },
                {
                    "constraint_name": "fk_orders_buyer",
                    "constraint_type": "FOREIGN KEY",
                    "column_name": "buyer_id",
                    "ordinal_position": 1,
                },
            ],
        )
    )

    states = {state.name: state for state in introspector.list_constraint_states("orders")}

    assert set(states) == {"pk_orders", "fk_orders_buyer"}
    assert states["pk_orders"].kind == "primary_key"
    assert states["fk_orders_buyer"].kind == "foreign_key"
    assert states["pk_orders"].enforced is False
    assert states["pk_orders"].validated is False
    assert states["pk_orders"].raw["columns"] == ["id"]


def test_list_schemas_answers_the_datasets():
    introspector = _introspector(
        _Catalog(datasets=[{"schema_name": "my_dataset"}, {"schema_name": "other"}])
    )

    assert introspector.list_schemas() == ["my_dataset", "other"]


def test_item_exists_answers_the_kinds_the_catalogue_can():
    introspector = _introspector(
        _Catalog(
            tables=[_table("orders"), _table("recent_orders", "VIEW")],
            datasets=[{"schema_name": "my_dataset"}],
            routines=[
                {"routine_name": "add_one", "routine_type": "FUNCTION"},
                {"routine_name": "load_orders", "routine_type": "PROCEDURE"},
            ],
        )
    )

    assert introspector.item_exists(ItemKind.SCHEMA, "my_dataset") is True
    assert introspector.item_exists(ItemKind.SCHEMA, "missing") is False
    assert introspector.item_exists(ItemKind.TABLE, "orders", "my_dataset") is True
    assert introspector.item_exists(ItemKind.TABLE, "missing", "my_dataset") is False
    assert introspector.item_exists(ItemKind.FUNCTION, "add_one", "my_dataset") is True
    assert introspector.item_exists(ItemKind.FUNCTION, "load_orders", "my_dataset") is False


def test_item_exists_refuses_a_kind_bigquery_cannot_be_asked_about():
    introspector = _introspector(_Catalog(datasets=[{"schema_name": "my_dataset"}]))

    with pytest.raises(ProtocolNotImplementedError) as caught:
        introspector.item_exists(ItemKind.SEQUENCE, "orders_seq", "my_dataset")

    assert "item_exists" in str(caught.value)


def test_item_exists_refuses_a_project_qualified_name():
    introspector = _introspector(_Catalog(datasets=[{"schema_name": "my_dataset"}]))

    with pytest.raises(ProtocolNotImplementedError):
        introspector.item_exists(ItemKind.SCHEMA, "other-project.my_dataset")


@pytest.mark.parametrize(
    "method, args",
    [
        ("list_index_states", ("orders",)),
        ("list_sequence_states", ()),
        ("list_derived_objects", ("orders",)),
    ],
)
def test_families_without_a_catalogue_stay_refusals(method, args):
    introspector = _introspector(_Catalog(tables=[_table("orders")]))

    with pytest.raises(ProtocolNotImplementedError) as caught:
        getattr(introspector, method)(*args, schema="my_dataset")

    assert method in str(caught.value)


# ---------------------------------------------------------------------------
# The async manager answers the same questions
# ---------------------------------------------------------------------------


def test_async_state_mirrors_the_sync_answers():
    catalog = _Catalog(
        tables=[_table("orders")],
        columns=[_column("id", 1), _column("created", 2, is_partitioning_column="YES")],
        options=[_option("description", "Order headers")],
        partitions=[_partition("20260101")],
        constraints=[
            {
                "constraint_name": "pk_orders",
                "constraint_type": "PRIMARY KEY",
                "column_name": "id",
                "ordinal_position": 1,
            }
        ],
        datasets=[{"schema_name": "my_dataset"}],
    )
    introspector = _async_introspector(catalog)

    state = asyncio.run(introspector.get_table_state("orders", "my_dataset"))
    partition_state = asyncio.run(introspector.get_partition_state("orders", "my_dataset"))
    constraints = asyncio.run(introspector.list_constraint_states("orders", "my_dataset"))
    schemas = asyncio.run(introspector.list_schemas())
    exists = asyncio.run(introspector.item_exists(ItemKind.TABLE, "orders", "my_dataset"))

    assert state.kind == "regular"
    assert state.comment == "Order headers"
    assert isinstance(partition_state, PartitionState)
    assert partition_state.scheme == PartitionScheme.RANGE
    assert [constraint.kind for constraint in constraints] == ["primary_key"]
    assert schemas == ["my_dataset"]
    assert exists is True


def test_async_unpartitioned_table_answers_an_empty_partition_state():
    introspector = _async_introspector(
        _Catalog(
            tables=[_table("orders")],
            columns=[_column("id", 1)],
            partitions=[_partition(None)],
        )
    )

    state = asyncio.run(introspector.get_partition_state("orders", "my_dataset"))
    table_state = asyncio.run(introspector.get_table_state("orders", "my_dataset"))

    assert isinstance(state, PartitionState)
    assert state.scheme is None
    assert state.bounds == ()
    assert isinstance(table_state.partitioning, PartitionState)
    assert table_state.partitioning.scheme is None
    assert table_state.partitioning.bounds == ()


def test_async_item_exists_refuses_a_missing_family():
    introspector = _async_introspector(_Catalog(tables=[_table("orders")]))

    with pytest.raises(ProtocolNotImplementedError) as caught:
        asyncio.run(introspector.item_exists(ItemKind.SEQUENCE, "orders_seq"))

    assert "item_exists" in str(caught.value)
