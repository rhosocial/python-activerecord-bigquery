# tests/rhosocial/activerecord_bigquery_test/feature/backend/introspection\test_introspection_cache.py
"""The introspection cache: one question per answer, on both backends.

The executor counts the questions it is asked. A cold pass asks once per
distinct question; a warm pass asks none, because every answer is cached
under the key that question answered. Nothing here touches a server: the
executor is a fake that answers canned rows and counts.

The BigQuery-only questions are covered too, because they are the ones with
the most interesting keys -- ``list_table_options`` and
``list_partitions`` share the table scope but answer different things, so
they must not answer each other.
"""

import pytest

from rhosocial.activerecord.backend.impl.bigquery.config import (
    BigQueryConnectionConfig,
)
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect
from rhosocial.activerecord.backend.impl.bigquery.introspection import (
    AsyncBigQueryIntrospector,
    SyncBigQueryIntrospector,
)

TABLES_ROWS = [
    {
        "table_catalog": "my-project",
        "table_schema": "my_dataset",
        "table_name": "orders",
        "table_type": "BASE TABLE",
    },
    {"table_name": "payments", "table_type": "BASE TABLE"},
]

COLUMNS_ROWS = [
    {
        "column_name": "id",
        "data_type": "INT64",
        "is_nullable": "NO",
        "ordinal_position": 1,
        "is_hidden": "NO",
    },
    {
        "column_name": "amount",
        "data_type": "NUMERIC",
        "is_nullable": "YES",
        "ordinal_position": 2,
        "is_hidden": "NO",
        "is_partitioning_column": "NO",
    },
]

DATASETS_ROWS = [{"schema_name": "my_dataset", "catalog_name": "my-project"}]

OPTIONS_ROWS = [
    {
        "table_name": "orders",
        "option_name": "require_partition_filter",
        "option_value": "true",
        "option_type": "BOOL",
    }
]

PARTITIONS_ROWS = [{"table_name": "orders", "partition_id": "20260101", "total_rows": 5}]

CONSTRAINTS_ROWS = [
    {
        "constraint_name": "pk_orders",
        "constraint_type": "PRIMARY KEY",
        "column_name": "id",
        "ordinal_position": 1,
    }
]


class _BackendStandIn:
    def __init__(self, project="my-project", dataset="my_dataset"):
        self.dialect = BigQueryDialect()
        self.config = BigQueryConnectionConfig(project=project, dataset=dataset)
        self._version = (3, 0, 0)


def _rows_for(sql):
    """The canned rows one question's SQL selects."""
    if "SCHEMATA" in sql:
        return DATASETS_ROWS
    if "TABLE_OPTIONS" in sql:
        return OPTIONS_ROWS
    if "PARTITIONS" in sql:
        return PARTITIONS_ROWS
    if "TABLE_CONSTRAINTS" in sql:
        return CONSTRAINTS_ROWS
    if "COLUMNS" in sql:
        return COLUMNS_ROWS
    if "TABLES" in sql:
        return TABLES_ROWS
    return []


class _CountingExecutor:
    """Answers from :func:`_rows_for`, counting every question."""

    def __init__(self):
        self.questions = []

    def execute(self, sql, params=()):
        self.questions.append(sql)
        return _rows_for(sql)


class _CountingAsyncExecutor(_CountingExecutor):
    async def execute(self, sql, params=()):
        self.questions.append(sql)
        return _rows_for(sql)


@pytest.fixture
def sync_case():
    executor = _CountingExecutor()
    introspector = SyncBigQueryIntrospector(_BackendStandIn(), executor)
    return introspector, executor


@pytest.fixture
def async_case():
    executor = _CountingAsyncExecutor()
    introspector = AsyncBigQueryIntrospector(_BackendStandIn(), executor)
    return introspector, executor


def _walk_sync(introspector):
    """Every question once, the order a caller would ask them in."""
    datasets = introspector.list_datasets()
    tables = introspector.list_tables("my_dataset")
    columns = introspector.list_columns("orders", "my_dataset")
    primary_key = introspector.get_primary_key("orders", "my_dataset")
    table_info = introspector.get_table_info("orders", "my_dataset")
    storage = introspector.get_table_storage_info("orders", "my_dataset")
    database_info = introspector.get_database_info()
    return datasets, tables, columns, primary_key, table_info, storage, database_info


async def _walk_async(introspector):
    datasets = await introspector.list_datasets()
    tables = await introspector.list_tables("my_dataset")
    columns = await introspector.list_columns("orders", "my_dataset")
    primary_key = await introspector.get_primary_key("orders", "my_dataset")
    table_info = await introspector.get_table_info("orders", "my_dataset")
    storage = await introspector.get_table_storage_info("orders", "my_dataset")
    database_info = await introspector.get_database_info()
    return datasets, tables, columns, primary_key, table_info, storage, database_info


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------


def test_cold_pass_asks_each_question_once(sync_case):
    introspector, executor = sync_case
    datasets, tables, columns, primary_key, table_info, storage, info = _walk_sync(introspector)
    assert [d.schema_name for d in datasets] == ["my_dataset"]
    assert [t.name for t in tables] == ["orders", "payments"]
    assert [c.name for c in columns] == ["id", "amount"]
    assert primary_key.name == "pk_orders"
    assert table_info.name == "orders"
    assert storage.partitions[0].partition_id == "20260101"
    assert info.name == "my-project"
    # datasets + tables + columns + primary key + table info (one table
    # question: list_tables is cached, list_columns/list_indexes/
    # list_foreign_keys each add one) + storage's three + database info.
    # The exact number is less load-bearing than the shape: every question
    # appears once and none twice.
    assert len(executor.questions) == len(
        set(executor.questions)
    ), "the same SQL was issued twice on the cold pass"
    cold = len(executor.questions)
    assert cold > 0


def test_warm_pass_asks_nothing(sync_case):
    introspector, executor = sync_case
    _walk_sync(introspector)
    cold = len(executor.questions)
    _walk_sync(introspector)
    assert (
        len(executor.questions) == cold
    ), "the warm pass re-issued questions the cache should have answered"


def test_the_answers_are_the_same_objects_not_new_ones(sync_case):
    introspector, _executor = sync_case
    first = introspector.list_tables("my_dataset")
    second = introspector.list_tables("my_dataset")
    assert first is second


def test_options_and_partitions_do_not_answer_each_other(sync_case):
    introspector, executor = sync_case
    options = introspector.list_table_options("orders", "my_dataset")
    partitions = introspector.list_partitions("orders", "my_dataset")
    storage = introspector.get_table_storage_info("orders", "my_dataset")
    # Three questions, cached separately under their own keys: the options,
    # the partitions, and the columns the storage shape reads for the
    # partitioning and clustering columns.
    assert len(executor.questions) == 3
    assert [o.option_name for o in options] == ["require_partition_filter"]
    assert [p.partition_id for p in partitions] == ["20260101"]
    # The storage shape reuses those two cached answers rather than
    # re-asking them.
    assert storage.options is options
    assert storage.partitions is partitions


def test_a_different_dataset_is_a_different_answer(sync_case):
    introspector, executor = sync_case
    introspector.list_tables("my_dataset")
    introspector.list_tables("other_dataset")
    assert len(executor.questions) == 2


def test_a_different_table_type_is_a_different_table_answer(sync_case):
    introspector, executor = sync_case
    introspector.list_tables("my_dataset")
    introspector.list_tables("my_dataset", table_type="VIEW")
    assert len(executor.questions) == 2


def test_invalidating_drops_what_it_names(sync_case):
    introspector, executor = sync_case
    introspector.list_columns("orders", "my_dataset")
    introspector.invalidate_cache(name="orders")
    introspector.list_columns("orders", "my_dataset")
    assert len(executor.questions) == 2


def test_clearing_drops_everything(sync_case):
    introspector, executor = sync_case
    introspector.list_datasets()
    introspector.list_tables("my_dataset")
    introspector.clear_cache()
    introspector.list_datasets()
    introspector.list_tables("my_dataset")
    assert len(executor.questions) == 4


# ---------------------------------------------------------------------------
# Async
# ---------------------------------------------------------------------------


async def test_cold_and_warm_pass_async(async_case):
    introspector, executor = async_case
    datasets, tables, columns, primary_key, table_info, storage, info = await _walk_async(
        introspector
    )
    assert [d.schema_name for d in datasets] == ["my_dataset"]
    assert [t.name for t in tables] == ["orders", "payments"]
    assert [c.name for c in columns] == ["id", "amount"]
    assert primary_key.name == "pk_orders"
    assert table_info.name == "orders"
    assert storage.partitions[0].partition_id == "20260101"
    assert info.name == "my-project"
    cold = len(executor.questions)
    assert cold > 0
    assert len(executor.questions) == len(set(executor.questions))

    await _walk_async(introspector)
    assert (
        len(executor.questions) == cold
    ), "the warm pass re-issued questions the cache should have answered"


async def test_storage_shape_async_reuses_the_cached_answers(async_case):
    introspector, executor = async_case
    options = await introspector.list_table_options("orders", "my_dataset")
    partitions = await introspector.list_partitions("orders", "my_dataset")
    storage = await introspector.get_table_storage_info("orders", "my_dataset")
    # options + partitions, then the columns question inside the shape.
    assert len(executor.questions) == 3
    assert storage.options is options
    assert storage.partitions is partitions
    assert storage.clustering_columns == []
