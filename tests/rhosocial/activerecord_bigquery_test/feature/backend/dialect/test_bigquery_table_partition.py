# tests/rhosocial/activerecord_bigquery_test/feature/backend/dialect/test_bigquery_table_partition.py
"""BigQuery's proprietary table-level PARTITION BY / CLUSTER BY clause.

Core has no node for BigQuery's table-level partitioning grammar: its
PartitionClause family spells RANGE / LIST / HASH, which GoogleSQL rejects
here. This is the absent-expression case, so the backend owns the node and
names it itself. These tests pin the rendered GoogleSQL, the formatter-time
validation, and the boundary that keeps the node out of core.
"""

import pytest

from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError
from rhosocial.activerecord.backend.dialect.partition_capability import (
    PartitionCapability,
)
from rhosocial.activerecord.backend.dialect.protocols.ddl.partition import (
    PartitionSupport,
)
from rhosocial.activerecord.backend.expression import BaseExpression
from rhosocial.activerecord.backend.expression.core import Column
from rhosocial.activerecord.backend.expression.objects import Table
from rhosocial.activerecord.backend.expression.statements.ddl_partition import (
    PartitionByHashClause,
    PartitionByListClause,
    PartitionByRangeClause,
    PartitionDefinitionExpression,
    PartitionOptionsExpression,
    SubpartitionDefinitionExpression,
)
from rhosocial.activerecord.backend.expression.statements.ddl_table import (
    ColumnDefinition,
)
from rhosocial.activerecord.backend.expression.types import IntegerType
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect
from rhosocial.activerecord.backend.impl.bigquery.expression import (
    BigQueryCreateTableStatement,
    BigQueryPartitionDecoratedTable,
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


class TestPartitionDecoratedTable:
    """A table name addresses one partition by appending ``$<decorator>``."""

    @pytest.mark.parametrize(
        "decorator,expected",
        (
            ("2021071205", "`events`$2021071205"),  # hourly YYYYMMDDHH
            ("20210712", "`events`$20210712"),  # daily YYYYMMDD
            ("202107", "`events`$202107"),  # monthly YYYYMM
            ("2021", "`events`$2021"),  # yearly YYYY
            (40, "`events`$40"),  # integer range_start, int form
            ("40", "`events`$40"),  # integer range_start, string form
            ("123456789012345", "`events`$123456789012345"),  # multi-digit range_start
            ("__NULL__", "`events`$__NULL__"),
            ("__UNPARTITIONED__", "`events`$__UNPARTITIONED__"),
        ),
        ids=(
            "hourly",
            "daily",
            "monthly",
            "yearly",
            "range-start-int",
            "range-start-string",
            "range-start-multidigit",
            "null-sentinel",
            "unpartitioned-sentinel",
        ),
    )
    def test_documented_decorator_forms_render(self, decorator, expected, dialect):
        ref = BigQueryPartitionDecoratedTable(dialect, "events", decorator)
        assert ref.to_sql() == (expected, ())

    def test_project_dataset_table(self, dialect):
        ref = BigQueryPartitionDecoratedTable(
            dialect, "events", "20260101", catalog_name="proj", schema_name="ds"
        )
        sql, _ = ref.to_sql()
        assert sql.endswith("$20260101")
        assert "events" in sql

    @pytest.mark.parametrize("blank", ("", "  "))
    def test_blank_decorator_is_refused_by_name(self, blank, dialect):
        ref = BigQueryPartitionDecoratedTable(dialect, "events", blank)
        with pytest.raises(ValueError, match="must not be blank"):
            ref.to_sql()

    @pytest.mark.parametrize("negative", (-10, "-10"))
    def test_negative_range_start_is_refused_by_name(self, negative, dialect):
        ref = BigQueryPartitionDecoratedTable(dialect, "events", negative)
        with pytest.raises(ValueError, match="must be non-negative"):
            ref.to_sql()

    @pytest.mark.parametrize(
        "bad",
        (1.5, True, "NULL", "__null__", "2026-01-01", "x; DROP", "+40"),
    )
    def test_non_decorator_values_are_refused_by_name(self, bad, dialect):
        ref = BigQueryPartitionDecoratedTable(dialect, "events", bad)
        with pytest.raises(ValueError, match="partition decorator"):
            ref.to_sql()

    @pytest.mark.parametrize("value", ("20211301", "202113", "2021130100"))
    def test_numeric_form_is_accepted_without_a_calendar_check(self, value, dialect):
        """A numeral may be an integer ``range_start``; only the server knows.

        The node carries no partitioning type, so ``20211301`` (month 13) is
        still a syntactically valid integer-range decorator.  The reference
        leaves that semantic check to the target table's definition.
        """
        ref = BigQueryPartitionDecoratedTable(dialect, "events", value)
        assert ref.to_sql()[0] == f"`events`${value}"


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


#: Every core ``PartitionSupport`` member this dialect must expose.  The
#: proprietary mixin used to be a bare ``object`` class, so these raised
#: ``AttributeError`` even though partition rendering already worked.
PARTITION_SUPPORT_MEMBERS = (
    "supports_table_partitioning",
    "partition_capability",
    "supports_partitioned_table_creation",
    "supports_partition_metadata_introspection",
    "supports_range_table_partitioning",
    "supports_list_table_partitioning",
    "supports_hash_table_partitioning",
    "supports_subpartitioning",
    "format_partition_clause",
    "format_partition_definition_expression",
    "format_subpartition_definition_expression",
    "format_partition_options_expression",
)


class TestCorePartitionCapabilitySurface:
    """The core ``PartitionSupport`` protocol reaches the dialect."""

    @pytest.mark.parametrize("member", PARTITION_SUPPORT_MEMBERS)
    def test_member_exists(self, member, dialect):
        assert hasattr(dialect, member), f"BigQueryDialect has no {member}"

    def test_core_partition_protocol_is_satisfied(self, dialect):
        assert isinstance(dialect, PartitionSupport)

    def test_table_partitioning_is_native(self, dialect):
        """BigQuery has partition DDL and addresses partitions by decorator."""
        assert dialect.supports_table_partitioning() is True
        assert dialect.partition_capability() is PartitionCapability.NATIVE
        assert str(dialect.partition_capability()) == "native"

    def test_creation_and_metadata_introspection_are_supported(self, dialect):
        """``CREATE TABLE ... PARTITION BY`` and ``INFORMATION_SCHEMA.PARTITIONS``."""
        assert dialect.supports_partitioned_table_creation() is True
        assert dialect.supports_partition_metadata_introspection() is True

    def test_generic_strategy_gates_are_declined(self, dialect):
        """The generic RANGE/LIST/HASH grammar is not GoogleSQL."""
        assert dialect.supports_range_table_partitioning() is False
        assert dialect.supports_list_table_partitioning() is False
        assert dialect.supports_hash_table_partitioning() is False
        assert dialect.supports_subpartitioning() is False


class TestGenericPartitionActionsAreRefused:
    """Each generic partition node refuses by name instead of inventing SQL."""

    @pytest.mark.parametrize(
        "clause_cls,feature",
        (
            (PartitionByRangeClause, "RANGE partitioning"),
            (PartitionByListClause, "LIST partitioning"),
            (PartitionByHashClause, "HASH partitioning"),
        ),
        ids=("range", "list", "hash"),
    )
    def test_generic_partition_clause_refused(self, clause_cls, feature, dialect):
        expression = clause_cls(dialect, [Column(dialect, "dt")])
        with pytest.raises(UnsupportedFeatureError) as caught:
            expression.to_sql()
        assert caught.value.feature_name == feature

    def test_partition_definition_refused(self, dialect):
        expression = PartitionDefinitionExpression(
            dialect, "p0", less_than=[Column(dialect, "dt")]
        )
        with pytest.raises(UnsupportedFeatureError) as caught:
            expression.to_sql()
        assert caught.value.feature_name == "partition definition"

    def test_subpartition_definition_refused(self, dialect):
        expression = SubpartitionDefinitionExpression(
            dialect, "sp0", less_than=[Column(dialect, "dt")]
        )
        with pytest.raises(UnsupportedFeatureError) as caught:
            expression.to_sql()
        assert caught.value.feature_name == "subpartition definition"

    def test_partition_options_refused(self, dialect):
        expression = PartitionOptionsExpression(dialect, {"engine": "x"})
        with pytest.raises(UnsupportedFeatureError) as caught:
            expression.to_sql()
        assert caught.value.feature_name == "partition options"

    def test_range_refusal_points_at_range_bucket(self, dialect):
        """Integer range partitioning exists, spelled RANGE_BUCKET."""
        expression = PartitionByRangeClause(dialect, [Column(dialect, "id")])
        with pytest.raises(UnsupportedFeatureError, match="RANGE_BUCKET"):
            expression.to_sql()
