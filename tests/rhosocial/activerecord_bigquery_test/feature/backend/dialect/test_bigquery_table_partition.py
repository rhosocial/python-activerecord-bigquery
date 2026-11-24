# tests/rhosocial/activerecord_bigquery_test/feature/backend/dialect/test_bigquery_table_partition.py
"""BigQuery's proprietary table-level PARTITION BY / CLUSTER BY clause.

Core has no node for BigQuery's table-level partitioning grammar: its
PartitionClause family spells RANGE / LIST / HASH, which GoogleSQL rejects
here. This is the absent-expression case, so the backend owns the node and
names it itself. These tests pin the rendered GoogleSQL, the formatter-time
validation, and the boundary that keeps the node out of core.
"""

import pytest

from rhosocial.activerecord.backend.expression import BaseExpression
from rhosocial.activerecord.backend.expression.objects import Table
from rhosocial.activerecord.backend.expression.statements.ddl_table import (
    ColumnDefinition,
)
from rhosocial.activerecord.backend.expression.types import IntegerType
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect
from rhosocial.activerecord.backend.impl.bigquery.expression import (
    BigQueryCreateTableStatement,
    BigQueryTablePartitionByClause,
)
from rhosocial.activerecord.backend.impl.bigquery.protocols import (
    BigQueryPartitionSupport,
)


@pytest.fixture
def dialect():
    return BigQueryDialect()


class TestProprietaryIdentity:
    def test_node_is_a_backend_owned_expression(self):
        assert issubclass(BigQueryTablePartitionByClause, BaseExpression)
        assert BigQueryTablePartitionByClause.__module__.startswith(
            "rhosocial.activerecord.backend.impl.bigquery.expression"
        )
        assert BigQueryTablePartitionByClause.kind() == "bigquery_table_partition_by_clause"
        assert BigQueryTablePartitionByClause.format_method.fget(None) == (
            "format_bigquery_table_partition_by_clause"
        )

    def test_the_backend_owns_the_formatter(self, dialect):
        assert isinstance(dialect, BigQueryPartitionSupport)
        assert (
            dialect.format_bigquery_table_partition_by_clause.__qualname__
            == "BigQueryPartitionMixin.format_bigquery_table_partition_by_clause"
        )

    def test_no_core_export(self):
        import rhosocial.activerecord.backend.expression as core_expression

        assert not hasattr(core_expression, "BigQueryTablePartitionByClause")


class TestRenderValidGoogleSQL:
    def test_partition_by_date_truncation(self, dialect):
        clause = BigQueryTablePartitionByClause(dialect, "DATE(ts)")
        assert clause.to_sql() == (" PARTITION BY DATE(ts)", ())

    def test_partition_by_timestamp_truncation_with_granularity(self, dialect):
        clause = BigQueryTablePartitionByClause(dialect, "TIMESTAMP_TRUNC(ts, DAY)")
        assert clause.to_sql()[0] == " PARTITION BY TIMESTAMP_TRUNC(ts, DAY)"

    def test_partition_by_range_bucket(self, dialect):
        clause = BigQueryTablePartitionByClause(
            dialect, "RANGE_BUCKET(id, GENERATE_ARRAY(0, 100, 10))"
        )
        assert clause.to_sql() == (
            " PARTITION BY RANGE_BUCKET(id, GENERATE_ARRAY(0, 100, 10))",
            (),
        )

    def test_cluster_by_two_columns(self, dialect):
        clause = BigQueryTablePartitionByClause(dialect, cluster_by=["a", "b"])
        assert clause.to_sql() == (" CLUSTER BY a, b", ())

    def test_partition_and_cluster_together(self, dialect):
        clause = BigQueryTablePartitionByClause(dialect, "DATE(ts)", ["a", "b"])
        assert clause.to_sql() == (" PARTITION BY DATE(ts) CLUSTER BY a, b", ())

    def test_quoted_cluster_columns(self, dialect):
        clause = BigQueryTablePartitionByClause(dialect, cluster_by=["`a`", "b"])
        assert clause.to_sql()[0] == " CLUSTER BY `a`, b"


class TestFormatterValidation:
    """The node collects parameters; the formatter alone refuses bad ones."""

    @pytest.mark.parametrize(
        "spec",
        ["", "   ", "ts", "DATE(ts); DROP TABLE x", "RANGE_BUCKET(id)"],
    )
    def test_invalid_partition_expression_fails_at_render_time(self, dialect, spec):
        clause = BigQueryTablePartitionByClause(dialect, spec)
        with pytest.raises(ValueError, match="PARTITION BY"):
            clause.to_sql()

    @pytest.mark.parametrize("columns", [[], "a", ["a", ""], ["a", "b; DROP"]])
    def test_invalid_cluster_columns_fail_at_render_time(self, dialect, columns):
        clause = BigQueryTablePartitionByClause(dialect, cluster_by=columns)
        with pytest.raises(ValueError, match="CLUSTER BY"):
            clause.to_sql()

    def test_empty_clause_fails_at_render_time(self, dialect):
        clause = BigQueryTablePartitionByClause(dialect)
        with pytest.raises(ValueError, match="requires a partition expression"):
            clause.to_sql()

    def test_too_many_cluster_columns_fails_at_render_time(self, dialect):
        clause = BigQueryTablePartitionByClause(dialect, cluster_by=list("abcde"))
        with pytest.raises(ValueError, match="at most 4"):
            clause.to_sql()


class TestCreateTableAttachment:
    def test_clause_is_appended_to_create_table(self, dialect):
        statement = BigQueryCreateTableStatement(
            dialect,
            Table(dialect, "events"),
            [ColumnDefinition(dialect, "id", IntegerType(dialect))],
            partition_by=BigQueryTablePartitionByClause(dialect, "DATE(ts)", ["a", "b"]),
        )
        sql, params = statement.to_sql()
        assert sql == (
            "CREATE TABLE `events` (`id` INT64) PARTITION BY DATE(ts) CLUSTER BY a, b"
        )
        assert params == ()

    def test_create_table_without_clause_is_unchanged(self, dialect):
        statement = BigQueryCreateTableStatement(
            dialect,
            Table(dialect, "events"),
            [ColumnDefinition(dialect, "id", IntegerType(dialect))],
        )
        assert statement.to_sql()[0] == "CREATE TABLE `events` (`id` INT64)"
