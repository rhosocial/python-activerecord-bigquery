# tests/rhosocial/activerecord_bigquery_test/feature/backend/introspection/test_introspection_parsing.py
"""Row -> dataclass parsing, fed the documented column names and values.

No connection and no SQL: these tests call the ``parse_*`` methods with
rows spelled exactly as the documentation spells them (lowercase column
names, ``YES``/``NO`` flags, the documented ``table_type`` words), which is
what BigQuery returns. The parsing rules pinned here are the ones a server
answer would enforce: pseudo columns dropped, ``is_nullable`` mapped,
identity fields under their documented names, and one unreadable type
degrading one column rather than the table.

Docs:

* TABLES https://cloud.google.com/bigquery/docs/information-schema-tables
* COLUMNS https://cloud.google.com/bigquery/docs/information-schema-columns
* TABLE_CONSTRAINTS https://cloud.google.com/bigquery/docs/information-schema-table-constraints
* KEY_COLUMN_USAGE https://cloud.google.com/bigquery/docs/information-schema-key-column-usage
* VIEWS https://cloud.google.com/bigquery/docs/information-schema-views
* SCHEMATA https://cloud.google.com/bigquery/docs/information-schema-datasets-schemata
* TABLE_OPTIONS https://cloud.google.com/bigquery/docs/information-schema-table-options
* PARTITIONS https://cloud.google.com/bigquery/docs/information-schema-partitions
"""

from datetime import datetime

import pytest
from rhosocial.activerecord.backend.introspection.types import (
    ColumnNullable,
    IndexType,
    TableType,
)

from rhosocial.activerecord.backend.impl.bigquery.config import (
    BigQueryConnectionConfig,
)
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect
from rhosocial.activerecord.backend.impl.bigquery.introspection import (
    AsyncBigQueryIntrospector,
    SyncBigQueryIntrospector,
)
from rhosocial.activerecord.backend.impl.bigquery.introspection.types import (
    BigQueryTableStorageInfo,
)


class _BackendStandIn:
    def __init__(self, project="my-project", dataset="my_dataset"):
        self.dialect = BigQueryDialect()
        self.config = BigQueryConnectionConfig(project=project, dataset=dataset)
        self._version = (3, 0, 0)


class _RecordingExecutor:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        return []


class _RecordingAsyncExecutor:
    def __init__(self):
        self.calls = []

    async def execute(self, sql, params=()):
        self.calls.append((sql, params))
        return []


@pytest.fixture
def introspector():
    return SyncBigQueryIntrospector(_BackendStandIn(), _RecordingExecutor())


@pytest.fixture
def async_introspector():
    return AsyncBigQueryIntrospector(_BackendStandIn(), _RecordingAsyncExecutor())


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


def test_tables_parse_the_documented_type_words(introspector):
    rows = [
        {
            "table_catalog": "my-project",
            "table_schema": "my_dataset",
            "table_name": "orders",
            "table_type": "BASE TABLE",
            "is_insertable_into": "YES",
            "is_typed": "NO",
            "creation_time": datetime(2026, 10, 24, 12, 0, 0),
            "ddl": "CREATE TABLE `my-project.my_dataset.orders` (id INT64)",
            "default_collation_name": None,
        },
        {
            "table_name": "orders_clone",
            "table_type": "CLONE",
            "is_insertable_into": "YES",
        },
        {
            "table_name": "orders_snapshot",
            "table_type": "SNAPSHOT",
        },
        {
            "table_name": "my_view",
            "table_type": "VIEW",
            "is_insertable_into": "NO",
        },
        {
            "table_name": "my_mv",
            "table_type": "MATERIALIZED VIEW",
        },
        {
            "table_name": "external_table",
            "table_type": "EXTERNAL",
        },
    ]
    tables = introspector.parse_tables(rows, "my_dataset")
    assert [t.name for t in tables] == [
        "orders",
        "orders_clone",
        "orders_snapshot",
        "my_view",
        "my_mv",
        "external_table",
    ]
    assert [t.table_type for t in tables] == [
        TableType.BASE_TABLE,
        TableType.BASE_TABLE,  # a clone is a table for "can I select from it"
        TableType.BASE_TABLE,  # a snapshot too
        TableType.VIEW,
        TableType.MATERIALIZED_VIEW,  # the catalog distinguishes it
        TableType.EXTERNAL,
    ]
    orders = tables[0]
    assert orders.schema == "my_dataset"
    assert orders.create_time == "2026-10-24T12:00:00"
    assert orders.extra["bigquery_table_type"] == "BASE TABLE"
    assert orders.extra["is_insertable_into"] is True
    assert orders.extra["ddl"].startswith("CREATE TABLE")
    # The original spelling survives, so a clone is not mistaken for a
    # plain table downstream.
    assert tables[1].extra["bigquery_table_type"] == "CLONE"


def test_tables_default_unknown_spellings_to_base_table(introspector):
    tables = introspector.parse_tables([{"table_name": "t", "table_type": "SOMETHING NEW"}], "ds")
    assert tables[0].table_type is TableType.BASE_TABLE
    assert tables[0].extra["bigquery_table_type"] == "SOMETHING NEW"


def test_tables_accept_uppercase_row_keys(introspector):
    """A driver or fixture that preserves the catalog's own spelling."""
    tables = introspector.parse_tables(
        [{"TABLE_NAME": "orders", "TABLE_TYPE": "BASE TABLE"}], "my_dataset"
    )
    assert tables[0].name == "orders"
    assert tables[0].table_type is TableType.BASE_TABLE


# ---------------------------------------------------------------------------
# Columns
# ---------------------------------------------------------------------------


def _column_row(**overrides):
    row = {
        "table_name": "orders",
        "column_name": "id",
        "ordinal_position": 1,
        "is_nullable": "NO",
        "data_type": "INT64",
        "is_generated": "NEVER",
        "generation_expression": None,
        "is_stored": None,
        "is_hidden": "NO",
        "is_system_defined": "NO",
        "is_partitioning_column": "NO",
        "clustering_ordinal_position": None,
        "collation_name": None,
        "column_default": None,
        "rounding_mode": None,
        "is_identity": "NO",
        "identity_generation": None,
        "identity_start": None,
        "identity_increment": None,
        "identity_maximum": None,
        "identity_minimum": None,
        "identity_cycle": None,
    }
    row.update(overrides)
    return row


def test_columns_parse_nullability_type_and_position(introspector):
    columns = introspector.parse_columns(
        [
            _column_row(),
            _column_row(
                column_name="note",
                ordinal_position=2,
                data_type="STRING",
                is_nullable="YES",
            ),
            _column_row(
                column_name="unmarked",
                ordinal_position=3,
                data_type="STRING",
                is_nullable="no",
            ),
        ],
        "orders",
        "my_dataset",
    )
    assert [(c.name, c.nullable, c.data_type, c.ordinal_position) for c in columns] == [
        ("id", ColumnNullable.NOT_NULL, "int64", 1),
        ("note", ColumnNullable.NULLABLE, "string", 2),
        # The catalog spells YES/NO uppercase; a lowercase answer the
        # driver passed through means the same thing.
        ("unmarked", ColumnNullable.NOT_NULL, "string", 3),
    ]
    assert columns[0].table_name == "orders"
    assert columns[0].schema == "my_dataset"
    # A readable type is parsed to a DataType for the schema differ.
    assert columns[0].parsed_data_type is not None
    assert columns[0].data_type_full == "INT64"
    # BigQuery has no core auto-increment flag; identity is in ``extra``.
    assert columns[0].is_auto_increment is False


def test_columns_drop_pseudo_columns(introspector):
    columns = introspector.parse_columns(
        [
            _column_row(),
            _column_row(
                column_name="_PARTITIONTIME",
                data_type="TIMESTAMP",
                ordinal_position=None,
                is_hidden="YES",
                is_system_defined="YES",
            ),
        ],
        "orders",
        "my_dataset",
    )
    assert [c.name for c in columns] == ["id"]


def test_columns_parse_identity_columns_under_the_documented_names(introspector):
    columns = introspector.parse_columns(
        [
            _column_row(
                column_name="order_id",
                is_identity="YES",
                identity_generation="ALWAYS",
                identity_start="1",
                identity_increment="1",
                identity_maximum="1000",
                identity_minimum="1",
                identity_cycle="NEVER",
            )
        ],
        "orders",
        "my_dataset",
    )
    extra = columns[0].extra
    assert extra["is_identity"] is True
    assert extra["identity_generation"] == "ALWAYS"
    assert extra["identity_start"] == 1
    assert extra["identity_increment"] == 1
    assert extra["identity_maximum"] == 1000
    assert extra["identity_minimum"] == 1
    assert extra["identity_cycle"] == "NEVER"


def test_columns_parse_partitioning_and_clustering_flags(introspector):
    columns = introspector.parse_columns(
        [
            _column_row(
                column_name="created",
                data_type="DATE",
                ordinal_position=2,
                is_partitioning_column="YES",
            ),
            _column_row(
                column_name="region",
                ordinal_position=3,
                is_partitioning_column="NO",
                clustering_ordinal_position="2",
            ),
            _column_row(
                column_name="tier",
                ordinal_position=4,
                is_partitioning_column="NO",
                clustering_ordinal_position="1",
            ),
        ],
        "orders",
        "my_dataset",
    )
    partitioning = [c.name for c in columns if c.extra["is_partitioning_column"] is True]
    assert partitioning == ["created"]
    clustering = sorted(
        (
            (c.extra["clustering_ordinal_position"], c.name)
            for c in columns
            if c.extra["clustering_ordinal_position"] is not None
        )
    )
    assert [name for _position, name in clustering] == ["tier", "region"]


def test_an_unreadable_type_degrades_one_column_with_a_warning(introspector):
    with pytest.warns(RuntimeWarning, match="STRUCT<id INT64>"):
        columns = introspector.parse_columns(
            [
                _column_row(),
                _column_row(column_name="payload", data_type="STRUCT<id INT64>"),
            ],
            "orders",
            "my_dataset",
        )
    assert columns[0].parsed_data_type is not None
    # The unreadable column keeps its string and leaves the parsed object
    # unset, which is the differ's documented fallback.
    assert columns[1].parsed_data_type is None
    assert columns[1].data_type == "struct<id int64>"


# ---------------------------------------------------------------------------
# Indexes, views, datasets, options, partitions
# ---------------------------------------------------------------------------


def test_indexes_group_constraint_rows_by_name(introspector):
    indexes = introspector.parse_indexes(
        [
            {
                "constraint_name": "pk_orders",
                "constraint_type": "PRIMARY KEY",
                "column_name": "id",
                "ordinal_position": 1,
            },
            {
                "constraint_name": "pk_orders",
                "constraint_type": "PRIMARY KEY",
                "column_name": "tenant_id",
                "ordinal_position": 2,
            },
        ],
        "orders",
        "my_dataset",
    )
    assert len(indexes) == 1
    index = indexes[0]
    assert index.name == "pk_orders"
    assert index.is_primary is True
    assert index.is_unique is True
    assert index.index_type is IndexType.UNKNOWN
    assert [(c.name, c.ordinal_position) for c in index.columns] == [
        ("id", 1),
        ("tenant_id", 2),
    ]
    assert index.extra["constraint_type"] == "PRIMARY KEY"


def test_a_foreign_key_constraint_row_parses_as_not_primary(introspector):
    indexes = introspector.parse_indexes(
        [
            {
                "constraint_name": "fk_orders",
                "constraint_type": "FOREIGN KEY",
                "column_name": "user_id",
                "ordinal_position": 1,
            }
        ],
        "orders",
        "my_dataset",
    )
    assert indexes[0].is_primary is False


def test_views_parse_the_definition_and_standard_sql_flag(introspector):
    views = introspector.parse_views(
        [
            {
                "table_catalog": "my-project",
                "table_schema": "my_dataset",
                "table_name": "recent_orders",
                "view_definition": "SELECT * FROM orders",
                "check_option": None,
                "use_standard_sql": "YES",
            }
        ],
        "my_dataset",
    )
    view = views[0]
    assert view.name == "recent_orders"
    assert view.schema == "my_dataset"
    assert view.definition == "SELECT * FROM orders"
    assert view.check_option is None
    assert view.extra["use_standard_sql"] is True


def test_single_view_info_returns_none_for_no_rows(introspector):
    assert introspector.parse_view_info([], "missing", "my_dataset") is None


def test_single_view_info_parses_the_first_row(introspector):
    info = introspector.parse_view_info(
        [
            {
                "table_name": "v",
                "view_definition": "SELECT 1",
                "check_option": None,
                "use_standard_sql": "NO",
            }
        ],
        "v",
        "my_dataset",
    )
    assert info.name == "v"
    assert info.extra["use_standard_sql"] is False


def test_datasets_parse_the_schemata_columns(introspector):
    created = datetime(2026, 10, 24, 12, 0, 0)
    datasets = introspector.parse_datasets(
        [
            {
                "catalog_name": "my-project",
                "schema_name": "my_dataset",
                "schema_owner": None,
                "creation_time": created,
                "last_modified_time": created,
                "location": "US",
                "ddl": "CREATE SCHEMA my_dataset",
                "default_collation_name": None,
                "sync_status": None,
            }
        ]
    )
    dataset = datasets[0]
    assert dataset.schema_name == "my_dataset"
    assert dataset.catalog_name == "my-project"
    assert dataset.location == "US"
    assert dataset.creation_time == created
    assert dataset.ddl == "CREATE SCHEMA my_dataset"
    assert dataset.schema_owner is None


def test_table_options_parse_one_row_per_option(introspector):
    options = introspector.parse_table_options(
        [
            {
                "table_name": "orders",
                "option_name": "partition_expiration_days",
                "option_value": "90",
                "option_type": "FLOAT64",
                "table_catalog": "my-project",
                "table_schema": "my_dataset",
            },
            {
                "table_name": "orders",
                "option_name": "labels",
                "option_value": '[("env", "prod")]',
                "option_type": "ARRAY<STRUCT<STRING, STRING>>",
            },
        ]
    )
    assert [(o.option_name, o.option_type, o.option_value) for o in options] == [
        ("partition_expiration_days", "FLOAT64", "90"),
        ("labels", "ARRAY<STRUCT<STRING, STRING>>", '[("env", "prod")]'),
    ]
    assert options[0].table_catalog == "my-project"


def test_partitions_parse_counts_and_tiers(introspector):
    modified = datetime(2026, 10, 24, 12, 0, 0)
    partitions = introspector.parse_partitions(
        [
            {
                "table_name": "orders",
                "partition_id": "20260101",
                "total_rows": "5",
                "total_logical_bytes": "1024",
                "total_billable_bytes": "512",
                "last_modified_time": modified,
                "storage_tier": "ACTIVE",
            },
            {
                "table_name": "orders",
                "partition_id": "__NULL__",
                "total_rows": 0,
                "storage_tier": "LONG_TERM",
            },
            {
                # An unpartitioned table answers one row with a NULL id.
                "table_name": "plain",
                "partition_id": None,
                "total_rows": 3,
            },
        ]
    )
    assert [p.partition_id for p in partitions] == [
        "20260101",
        "__NULL__",
        None,
    ]
    assert partitions[0].total_rows == 5
    assert partitions[0].total_logical_bytes == 1024
    assert partitions[0].storage_tier == "ACTIVE"
    assert partitions[1].storage_tier == "LONG_TERM"
    assert partitions[0].last_modified_time == modified


def test_database_info_reports_the_project_and_the_backend_level(introspector):
    info = introspector.parse_database_info([{"catalog_name": "my-project"}])
    assert info.name == "my-project"
    assert info.vendor == "BigQuery"
    assert info.version_tuple == (3, 0, 0)
    assert info.extra["project"] == "my-project"
    assert info.extra["dataset"] == "my_dataset"
    assert info.extra["version_source"] == ("backend feature level, not a server version")


def test_database_info_falls_back_to_the_configured_project(introspector):
    info = introspector.parse_database_info([])
    assert info.name == "my-project"


# ---------------------------------------------------------------------------
# Storage shape: the three answers composed
# ---------------------------------------------------------------------------


def test_storage_shape_composes_options_partitions_and_columns(introspector):
    columns = introspector.parse_columns(
        [
            _column_row(
                column_name="created",
                data_type="DATE",
                ordinal_position=2,
                is_partitioning_column="YES",
            ),
            _column_row(
                column_name="tier",
                ordinal_position=3,
                clustering_ordinal_position=1,
            ),
        ],
        "orders",
        "my_dataset",
    )
    storage = BigQueryTableStorageInfo(
        table_name="orders",
        schema="my_dataset",
        options=introspector.parse_table_options(
            [
                {
                    "table_name": "orders",
                    "option_name": "require_partition_filter",
                    "option_value": "true",
                    "option_type": "BOOL",
                }
            ]
        ),
        partitions=introspector.parse_partitions(
            [{"table_name": "orders", "partition_id": "20260101", "total_rows": 5}]
        ),
        partitioning_columns=introspector._partitioning_columns(columns),
        clustering_columns=introspector._clustering_columns(columns),
    )
    assert storage.table_name == "orders"
    assert [o.option_name for o in storage.options] == ["require_partition_filter"]
    assert [p.partition_id for p in storage.partitions] == ["20260101"]
    assert storage.partitioning_columns == ["created"]
    assert storage.clustering_columns == ["tier"]


# ---------------------------------------------------------------------------
# Both managers share the dialect's capability answers
# ---------------------------------------------------------------------------


def test_async_introspector_declines_index_introspection(async_introspector):
    """The capability is declared once and the async manager inherits it."""
    assert async_introspector.dialect.supports_index_introspection() is False
