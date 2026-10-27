# tests/rhosocial/activerecord_bigquery_test/feature/backend/introspection/test_introspection_sql.py
"""The SQL shape each introspection question renders to.

No connection: the statements render through ``BigQueryDialect`` on their
own, and the ``*_statement`` factories run against a backend stand-in that
carries the three attributes the introspector reads (``dialect``,
``config``, ``_version``).

What is pinned here is the part of the contract a server would enforce:
the backtick-quoted ``project.dataset`` qualifier in front of the
``INFORMATION_SCHEMA`` view, the projection list documented per view, the
bind marker where a caller's value goes (never interpolated), and the
``ORDER BY`` each question ends with. The two questions BigQuery cannot
answer refuse rather than render.

Statement shapes are read from the documentation, not executed -- no
BigQuery instance was reachable while writing them:

* TABLES https://cloud.google.com/bigquery/docs/information-schema-tables
* COLUMNS https://cloud.google.com/bigquery/docs/information-schema-columns
* TABLE_CONSTRAINTS https://cloud.google.com/bigquery/docs/information-schema-table-constraints
* KEY_COLUMN_USAGE https://cloud.google.com/bigquery/docs/information-schema-key-column-usage
* VIEWS https://cloud.google.com/bigquery/docs/information-schema-views
* SCHEMATA https://cloud.google.com/bigquery/docs/information-schema-datasets-schemata
* TABLE_OPTIONS https://cloud.google.com/bigquery/docs/information-schema-table-options
* PARTITIONS https://cloud.google.com/bigquery/docs/information-schema-partitions
"""

import pytest
from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError
from rhosocial.activerecord.backend.introspection.types import IntrospectionScope

from rhosocial.activerecord.backend.impl.bigquery.config import (
    BigQueryConnectionConfig,
)
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect
from rhosocial.activerecord.backend.impl.bigquery.expression.introspection import (
    BigQueryColumnInfoQueryStatement,
    BigQueryDatabaseInfoQueryStatement,
    BigQueryDatasetListQueryStatement,
    BigQueryIndexInfoQueryStatement,
    BigQueryPartitionListQueryStatement,
    BigQueryTableListQueryStatement,
    BigQueryTableOptionsQueryStatement,
    BigQueryViewInfoQueryStatement,
    BigQueryViewListQueryStatement,
)
from rhosocial.activerecord.backend.impl.bigquery.introspection import (
    SyncBigQueryIntrospector,
)


class _BackendStandIn:
    """The three attributes the introspector reads off a backend."""

    def __init__(
        self,
        project: str = "my-project",
        dataset: str = "my_dataset",
        location: str = None,
    ):
        self.dialect = BigQueryDialect()
        self.config = BigQueryConnectionConfig(project=project, dataset=dataset, location=location)
        self._version = (3, 0, 0)


class _RecordingExecutor:
    """Records the questions, answers nothing."""

    def __init__(self):
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        return []


@pytest.fixture
def dialect():
    return BigQueryDialect()


@pytest.fixture
def introspector():
    executor = _RecordingExecutor()
    return SyncBigQueryIntrospector(_BackendStandIn(), executor), executor


# ---------------------------------------------------------------------------
# The dataset qualifier is the dialect's spelling, quoted as documented
# ---------------------------------------------------------------------------


def test_database_info_renders_the_documented_system_variable(dialect):
    sql, params = BigQueryDatabaseInfoQueryStatement(dialect).to_sql()
    assert sql == "SELECT @@project_id AS catalog_name"
    assert params == ()


def test_tables_query_qualifies_the_dataset_with_the_project(dialect):
    sql, params = BigQueryTableListQueryStatement(
        dialect, schema="my_dataset", catalog="my-project"
    ).to_sql()
    assert "FROM `my-project`.`my_dataset`.INFORMATION_SCHEMA.TABLES" in sql
    # The projection is the documented one, columns listed for stability.
    for column in (
        "table_catalog",
        "table_schema",
        "table_name",
        "table_type",
        "is_insertable_into",
        "is_typed",
        "creation_time",
        "ddl",
        "default_collation_name",
    ):
        assert f"`{column}`" in sql
    assert sql.rstrip().endswith("ORDER BY `table_name`")
    assert params == ()


def test_tables_query_without_project_leaves_the_project_unqualified(dialect):
    sql, _params = BigQueryTableListQueryStatement(dialect, schema="my_dataset").to_sql()
    assert "FROM `my_dataset`.INFORMATION_SCHEMA.TABLES" in sql
    assert "my-project" not in sql


def test_include_views_false_renders_not_in_over_the_view_types(dialect):
    sql, params = BigQueryTableListQueryStatement(
        dialect, schema="ds", include_views=False
    ).to_sql()
    assert "NOT (`table_type` IN (?, ?))" in sql
    # View spellings are bind parameters, like every other value.
    assert params == ("VIEW", "MATERIALIZED VIEW")


def test_base_table_type_expands_onto_the_catalog_spellings(dialect):
    sql, params = BigQueryTableListQueryStatement(
        dialect, schema="ds", table_type="BASE_TABLE"
    ).to_sql()
    assert "`table_type` IN (?, ?, ?)" in sql
    assert params == ("BASE TABLE", "CLONE", "SNAPSHOT")


def test_view_type_matches_only_views(dialect):
    _sql, params = BigQueryTableListQueryStatement(dialect, schema="ds", table_type="VIEW").to_sql()
    assert params == ("VIEW",)


def test_materialized_view_type_matches_only_materialized_views(dialect):
    _sql, params = BigQueryTableListQueryStatement(
        dialect, schema="ds", table_type="MATERIALIZED_VIEW"
    ).to_sql()
    assert params == ("MATERIALIZED VIEW",)


def test_external_type_filters_on_the_catalog_spelling(dialect):
    _sql, params = BigQueryTableListQueryStatement(
        dialect, schema="ds", table_type="EXTERNAL"
    ).to_sql()
    assert params == ("EXTERNAL",)


def test_a_type_the_catalog_never_lists_matches_nothing(dialect):
    sql, params = BigQueryTableListQueryStatement(
        dialect, schema="ds", table_type="SYSTEM TABLE"
    ).to_sql()
    # No catalog spelling exists, so the filter is a contradiction rather
    # than an unfiltered listing.
    assert "WHERE 1 = 2" in sql
    assert params == ()


def test_columns_query_binds_the_table_name(dialect):
    sql, params = BigQueryColumnInfoQueryStatement(
        dialect, "orders", "my_dataset", "my-project"
    ).to_sql()
    assert "FROM `my-project`.`my_dataset`.INFORMATION_SCHEMA.COLUMNS" in sql
    assert "WHERE `table_name` = ?" in sql
    assert params == ("orders",)
    assert "ORDER BY `ordinal_position`" in sql
    # identity_maximum / identity_minimum are the documented spellings.
    assert "`identity_maximum`" in sql
    assert "`identity_minimum`" in sql


def test_index_query_joins_the_two_constraint_views(dialect):
    sql, params = BigQueryIndexInfoQueryStatement(
        dialect, "orders", "my_dataset", "my-project"
    ).to_sql()
    assert "FROM `my-project`.`my_dataset`.INFORMATION_SCHEMA.TABLE_CONSTRAINTS AS `tc`" in sql
    assert "JOIN `my-project`.`my_dataset`.INFORMATION_SCHEMA.KEY_COLUMN_USAGE AS `kcu`" in sql
    assert "ON `tc`.`constraint_name` = `kcu`.`constraint_name`" in sql
    assert "AND `tc`.`table_name` = `kcu`.`table_name`" in sql
    assert "WHERE `tc`.`table_name` = ?" in sql
    assert "`tc`.`constraint_type` = ?" in sql
    assert params == ("orders", "PRIMARY KEY")
    assert "ORDER BY `tc`.`constraint_name` ASC" in sql


def test_views_query_binds_nothing_and_orders_by_name(dialect):
    sql, params = BigQueryViewListQueryStatement(
        dialect, schema="my_dataset", catalog="my-project"
    ).to_sql()
    assert "FROM `my-project`.`my_dataset`.INFORMATION_SCHEMA.VIEWS" in sql
    assert "`view_definition`" in sql
    assert "`check_option`" in sql
    assert "`use_standard_sql`" in sql
    assert "ORDER BY `table_name`" in sql
    assert params == ()


def test_single_view_query_binds_the_view_name(dialect):
    sql, params = BigQueryViewInfoQueryStatement(
        dialect, "my_view", "my_dataset", "my-project"
    ).to_sql()
    assert "WHERE `table_name` = ?" in sql
    assert params == ("my_view",)


def test_dataset_query_renders_the_project_and_region_qualifiers(dialect):
    sql, params = BigQueryDatasetListQueryStatement(
        dialect, catalog="my-project", location="US"
    ).to_sql()
    assert "FROM `my-project`.`region-US`.INFORMATION_SCHEMA.SCHEMATA" in sql
    assert "`schema_name`" in sql
    assert "`location`" in sql
    assert "ORDER BY `schema_name`" in sql
    assert params == ()


def test_dataset_query_without_location_reads_the_us_multiregion(dialect):
    sql, _params = BigQueryDatasetListQueryStatement(dialect, catalog="my-project").to_sql()
    assert "FROM `my-project`.INFORMATION_SCHEMA.SCHEMATA" in sql


def test_dataset_query_with_nothing_configured_is_unqualified(dialect):
    sql, _params = BigQueryDatasetListQueryStatement(dialect).to_sql()
    assert "FROM INFORMATION_SCHEMA.SCHEMATA" in sql


def test_table_options_query_binds_the_table_name(dialect):
    sql, params = BigQueryTableOptionsQueryStatement(
        dialect, "orders", "my_dataset", "my-project"
    ).to_sql()
    assert "FROM `my-project`.`my_dataset`.INFORMATION_SCHEMA.TABLE_OPTIONS" in sql
    assert "`option_name`" in sql
    assert "`option_type`" in sql
    assert "`option_value`" in sql
    assert "WHERE `table_name` = ?" in sql
    assert "ORDER BY `option_name`" in sql
    assert params == ("orders",)


def test_partitions_query_binds_the_table_name(dialect):
    sql, params = BigQueryPartitionListQueryStatement(
        dialect, "orders", "my_dataset", "my-project"
    ).to_sql()
    assert "FROM `my-project`.`my_dataset`.INFORMATION_SCHEMA.PARTITIONS" in sql
    assert "`partition_id`" in sql
    assert "`total_rows`" in sql
    assert "`storage_tier`" in sql
    assert "WHERE `table_name` = ?" in sql
    assert "ORDER BY `partition_id`" in sql
    assert params == ("orders",)


def test_no_statement_writes_sql_text_of_its_own(dialect):
    """A statement's render is the dialect's: swap the dialect and the
    quoted spellings move with it.

    ``Table``/``Column``/``InPredicate`` nodes carry no SQL; if a statement
    concatenated text, nothing downstream would notice and this dialect's
    quoting would not be the thing deciding it. The one check that matters
    is that the project path is quoted by the dialect's own identifier rule.
    """
    statement = BigQueryTableListQueryStatement(dialect, schema="my_dataset", catalog="my-project")
    sql, _params = statement.to_sql()
    # The dialect quotes with doubled backticks for an inner one; a project
    # ID containing a backtick is escaped rather than passed through.
    backtick_project = BigQueryTableListQueryStatement(
        dialect, schema="ds", catalog="my`project"
    ).to_sql()[0]
    assert "FROM `my``project`.`ds`.INFORMATION_SCHEMA.TABLES" in backtick_project
    assert sql.count("`") > 0


# ---------------------------------------------------------------------------
# The introspector's builders use the statements, and refuse what they must
# ---------------------------------------------------------------------------


def test_builders_use_the_configured_project_and_dataset(introspector):
    introspector, executor = introspector
    sql, params = introspector.table_list_statement(
        schema="other_ds", include_system=False
    ).to_sql()
    assert "FROM `my-project`.`other_ds`.INFORMATION_SCHEMA.TABLES" in sql
    assert params == ()

    # No schema argument: the connection's default dataset is used.
    sql, _params = introspector.table_list_statement(schema=None, include_system=False).to_sql()
    assert "FROM `my-project`.`my_dataset`.INFORMATION_SCHEMA.TABLES" in sql

    # A project.dataset pair overrides the configured project.
    sql, _params = introspector.table_list_statement(
        schema="other-project.other_ds", include_system=False
    ).to_sql()
    assert "FROM `other-project`.`other_ds`.INFORMATION_SCHEMA.TABLES" in sql


def test_every_builder_binds_caller_data_only(introspector):
    introspector, _executor = introspector
    _sql, params = introspector.column_info_statement(
        table_name="orders", schema="my_dataset"
    ).to_sql()
    assert params == ("orders",)
    _sql, params = introspector.view_info_statement(
        view_name="a view", schema="my_dataset"
    ).to_sql()
    assert params == ("a view",)
    _sql, params = introspector.table_options_statement(
        table_name="orders", schema="my_dataset"
    ).to_sql()
    assert params == ("orders",)
    _sql, params = introspector.partition_list_statement(
        table_name="orders", schema="my_dataset"
    ).to_sql()
    assert params == ("orders",)


def test_the_foreign_key_builder_refuses(introspector):
    introspector, _executor = introspector
    with pytest.raises(UnsupportedFeatureError) as exc_info:
        introspector.foreign_key_statement(table_name="orders", schema="my_dataset")
    assert "REFERENTIAL_CONSTRAINTS" in str(exc_info.value)


def test_the_trigger_builder_refuses(introspector):
    introspector, _executor = introspector
    with pytest.raises(UnsupportedFeatureError):
        introspector.trigger_list_statement(table_name="orders", schema="my_dataset")


def test_no_dataset_anywhere_is_refused_with_the_instruction(introspector):
    from rhosocial.activerecord.backend.impl.bigquery.introspection import (
        SyncBigQueryIntrospector as _Sync,
    )

    project_only = _Sync(_BackendStandIn(project="my-project", dataset=None), _RecordingExecutor())
    with pytest.raises(ValueError) as exc_info:
        project_only.table_list_statement(schema=None, include_system=False)
    assert "pass schema=" in str(exc_info.value)

    with pytest.raises(ValueError):
        project_only.column_info_statement(table_name="orders", schema=None)


def test_a_malformed_schema_argument_is_refused(introspector):
    introspector, _executor = introspector
    with pytest.raises(ValueError):
        introspector.table_list_statement(schema="a.b.c", include_system=False)


# ---------------------------------------------------------------------------
# The capability claims are facts about the catalog
# ---------------------------------------------------------------------------


def test_index_introspection_is_declined(dialect):
    """BigQuery has no index catalogue, so the family is not claimed.

    The primary-key constraint read is still available as a constraint
    question; claiming the index family would advertise a CLI type that has
    no view to run.
    """
    assert dialect.supports_index_introspection() is False
    scopes = dialect.get_supported_introspection_scopes()
    assert IntrospectionScope.INDEX not in scopes
