# tests/rhosocial/activerecord_bigquery_test/feature/backend/dialect/test_bigquery_materialized_view.py
"""BigQuery MATERIALIZED VIEW DDL tests (SQL generation only, no database).

Covers ``CREATE [OR REPLACE] MATERIALIZED VIEW [IF NOT EXISTS]`` with
``PARTITION BY`` / ``CLUSTER BY`` / ``OPTIONS(...)``, ``ALTER MATERIALIZED VIEW
SET OPTIONS``, ``DROP MATERIALIZED VIEW [IF EXISTS]``, ``AS REPLICA OF``, and
the clauses BigQuery does *not* have (column aliases, TABLESPACE, storage
parameters, ``WITH [NO] DATA``, ``CASCADE``, ``REFRESH``).
"""

import pytest

from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError
from rhosocial.activerecord.backend.expression import Column, QueryExpression
from rhosocial.activerecord.backend.expression.objects import MaterializedView, Table
from rhosocial.activerecord.backend.expression.statements.ddl_view import (
    CreateMaterializedViewExpression,
    DropMaterializedViewExpression,
    RefreshMaterializedViewExpression,
)
from rhosocial.activerecord.backend.impl.bigquery.expression import (
    BigQueryAlterMaterializedViewSetOptionsExpression,
    BigQueryCreateMaterializedViewExpression,
    BigQueryCreateMaterializedViewReplicaExpression,
    BigQueryDropMaterializedViewExpression,
)
from rhosocial.activerecord.backend.impl.bigquery.materialized_view_options import (
    BigQueryMaterializedViewOption,
    BigQueryMaterializedViewOptionValueType,
)
from rhosocial.activerecord.backend.impl.bigquery.protocols import BigQueryMaterializedViewSupport
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect
from rhosocial.activerecord.backend.impl.bigquery.materialized_view_options import (
    resolve_materialized_view_option,
    validate_materialized_view_options,
)


@pytest.fixture
def dialect():
    return BigQueryDialect()


def _query(dialect):
    return QueryExpression(
        dialect=dialect,
        select=[Column(dialect, "product_id")],
        from_=Table(dialect, "sales"),
    )


class TestCapabilities:
    def test_materialized_view_supported(self, dialect):
        assert dialect.supports_materialized_view() is True
        assert dialect.supports_materialized_view_options() is True
        assert dialect.supports_materialized_view_replica() is True

    def test_no_refresh_statement(self, dialect):
        """BigQuery refreshes on a schedule; there is no REFRESH statement."""
        assert dialect.supports_refresh_materialized_view() is False

    def test_generic_refresh_raises(self, dialect):
        expr = RefreshMaterializedViewExpression(
            dialect=dialect, view=MaterializedView(dialect, "mv")
        )
        with pytest.raises(UnsupportedFeatureError):
            expr.to_sql()

    def test_protocol_conformance(self, dialect):
        assert isinstance(dialect, BigQueryMaterializedViewSupport)

    def test_formatter_is_owned_by_bigquery_mixin(self, dialect):
        owner = dialect.format_create_materialized_view_statement.__qualname__
        assert owner.startswith("BigQueryMaterializedViewMixin.")


class TestCreateMaterializedView:
    def test_minimal(self, dialect):
        expr = BigQueryCreateMaterializedViewExpression(
            dialect, MaterializedView(dialect, "sales_summary"), _query(dialect)
        )
        sql, params = expr.to_sql()
        assert sql == (
            "CREATE MATERIALIZED VIEW `sales_summary` AS "
            "SELECT `product_id` FROM `sales`"
        )
        assert params == ()

    def test_or_replace(self, dialect):
        expr = BigQueryCreateMaterializedViewExpression(
            dialect, MaterializedView(dialect, "mv"), _query(dialect), or_replace=True
        )
        assert expr.to_sql()[0].startswith("CREATE OR REPLACE MATERIALIZED VIEW")

    def test_if_not_exists(self, dialect):
        expr = BigQueryCreateMaterializedViewExpression(
            dialect, MaterializedView(dialect, "mv"), _query(dialect), if_not_exists=True
        )
        assert "IF NOT EXISTS" in expr.to_sql()[0]

    def test_or_replace_and_if_not_exists_are_exclusive(self, dialect):
        with pytest.raises(ValueError, match="OR REPLACE"):
            BigQueryCreateMaterializedViewExpression(
                dialect,
                MaterializedView(dialect, "mv"),
                _query(dialect),
                or_replace=True,
                if_not_exists=True,
            )

    def test_partition_by_and_cluster_by(self, dialect):
        expr = BigQueryCreateMaterializedViewExpression(
            dialect,
            MaterializedView(dialect, "mv"),
            _query(dialect),
            partition_by="DATE(_PARTITIONTIME)",
            cluster_by=["product_id", "region"],
        )
        sql, _ = expr.to_sql()
        assert "PARTITION BY DATE(_PARTITIONTIME)" in sql
        assert "CLUSTER BY product_id, region" in sql

    def test_clause_order_matches_google_sql(self, dialect):
        expr = BigQueryCreateMaterializedViewExpression(
            dialect,
            MaterializedView(dialect, "mv"),
            _query(dialect),
            or_replace=True,
            partition_by="DATE(ts)",
            cluster_by=["c1"],
            options={BigQueryMaterializedViewOption.ENABLE_REFRESH: True},
        )
        sql, _ = expr.to_sql()
        assert sql.index("PARTITION BY") < sql.index("CLUSTER BY")
        assert sql.index("CLUSTER BY") < sql.index("OPTIONS(")
        assert sql.index("OPTIONS(") < sql.index(" AS ")

    def test_options_rendering(self, dialect):
        expr = BigQueryCreateMaterializedViewExpression(
            dialect,
            MaterializedView(dialect, "mv"),
            _query(dialect),
            options={
                BigQueryMaterializedViewOption.ENABLE_REFRESH: False,
                BigQueryMaterializedViewOption.REFRESH_INTERVAL_MINUTES: 20,
                BigQueryMaterializedViewOption.FRIENDLY_NAME: "nightly rollup",
            },
        )
        sql, _ = expr.to_sql()
        assert "OPTIONS(enable_refresh = false, refresh_interval_minutes = 20" in sql
        assert "friendly_name = 'nightly rollup')" in sql

    def test_dataset_qualified_name(self, dialect):
        """The dataset is the object's ``schema_name`` slot.

        BigQuery's two namespaces are ``project`` above ``dataset``, which the
        shared object spells ``catalog_name`` above ``schema_name``. Naming the
        view as a dotted string instead made the dataset indistinguishable from
        part of the view's own name: the whole thing was quoted as one
        identifier, ```analytics.sales_summary```, which names no object
        BigQuery has.
        """
        expr = BigQueryCreateMaterializedViewExpression(
            dialect, MaterializedView(dialect, "sales_summary", schema_name="analytics"),
            _query(dialect),
        )
        assert "`analytics`.`sales_summary`" in expr.to_sql()[0]

    def test_project_qualified_name(self, dialect):
        expr = BigQueryCreateMaterializedViewExpression(
            dialect,
            MaterializedView(dialect, "sales_summary", schema_name="analytics", catalog_name="proj"),
            _query(dialect),
        )
        assert "`proj`.`analytics`.`sales_summary`" in expr.to_sql()[0]

    def test_project_without_dataset_refused(self, dialect):
        """A BigQuery path is project.dataset.table, so this cannot render."""
        expr = BigQueryCreateMaterializedViewExpression(
            dialect, MaterializedView(dialect, "sales_summary", catalog_name="proj"),
            _query(dialect),
        )
        with pytest.raises(ValueError, match="project only together with a dataset"):
            expr.to_sql()

    def test_raw_query_string_accepted(self, dialect):
        expr = BigQueryCreateMaterializedViewExpression(
            dialect, MaterializedView(dialect, "mv"), "SELECT 1 AS one"
        )
        assert expr.to_sql()[0].endswith("AS SELECT 1 AS one")

    def test_empty_name_rejected(self, dialect):
        """The object owns the rule, so it raises wherever it is constructed."""
        with pytest.raises(ValueError, match="name must be a non-empty string"):
            MaterializedView(dialect, "  ")

    def test_empty_dataset_rejected(self, dialect):
        with pytest.raises(ValueError, match="schema_name"):
            MaterializedView(dialect, "mv", schema_name="")

    def test_empty_cluster_by_rejected(self, dialect):
        with pytest.raises(ValueError, match="cluster_by"):
            BigQueryCreateMaterializedViewExpression(
                dialect, MaterializedView(dialect, "mv"), _query(dialect), cluster_by=[]
            )


class TestCreateRejectsNonBigQueryClauses:
    """Clauses BigQuery lacks must be refused, never silently dropped."""

    def test_generic_column_aliases_rejected(self, dialect):
        expr = CreateMaterializedViewExpression(
            dialect=dialect,
            view=MaterializedView(dialect, "mv"),
            query=_query(dialect),
            column_aliases=["alias"],
        )
        with pytest.raises(UnsupportedFeatureError) as exc:
            expr.to_sql()
        assert "COLUMN ALIASES" in str(exc.value)

    def test_generic_tablespace_rejected(self, dialect):
        expr = CreateMaterializedViewExpression(
            dialect=dialect,
            view=MaterializedView(dialect, "mv"),
            query=_query(dialect),
            tablespace="fast_ssd",
        )
        with pytest.raises(UnsupportedFeatureError) as exc:
            expr.to_sql()
        assert "TABLESPACE" in str(exc.value)

    def test_generic_storage_options_rejected(self, dialect):
        expr = CreateMaterializedViewExpression(
            dialect=dialect,
            view=MaterializedView(dialect, "mv"),
            query=_query(dialect),
            storage_options={"fillfactor": 70},
        )
        with pytest.raises(UnsupportedFeatureError):
            expr.to_sql()

    def test_generic_with_no_data_rejected(self, dialect):
        expr = CreateMaterializedViewExpression(
            dialect=dialect,
            view=MaterializedView(dialect, "mv"),
            query=_query(dialect),
            with_data=False,
        )
        with pytest.raises(UnsupportedFeatureError) as exc:
            expr.to_sql()
        assert "WITH NO DATA" in str(exc.value)

    def test_drop_cascade_rejected(self, dialect):
        expr = DropMaterializedViewExpression(
            dialect=dialect,
            view=MaterializedView(dialect, "mv"),
            if_exists=True,
            cascade=True,
        )
        with pytest.raises(UnsupportedFeatureError) as exc:
            expr.to_sql()
        assert "CASCADE" in str(exc.value)


class TestDropMaterializedView:
    def test_plain(self, dialect):
        expr = BigQueryDropMaterializedViewExpression(dialect, MaterializedView(dialect, "mv"))
        assert expr.to_sql()[0] == "DROP MATERIALIZED VIEW `mv`"

    def test_if_exists(self, dialect):
        expr = BigQueryDropMaterializedViewExpression(
            dialect, MaterializedView(dialect, "mv"), if_exists=True
        )
        assert expr.to_sql()[0] == "DROP MATERIALIZED VIEW IF EXISTS `mv`"

    def test_cascade_rejected_at_construction(self, dialect):
        with pytest.raises(ValueError, match="CASCADE"):
            BigQueryDropMaterializedViewExpression(
                dialect, MaterializedView(dialect, "mv"), cascade=True
            )

    def test_generic_expression_renders(self, dialect):
        expr = DropMaterializedViewExpression(
            dialect=dialect, view=MaterializedView(dialect, "mv")
        )
        assert expr.to_sql()[0] == "DROP MATERIALIZED VIEW `mv`"


class TestAlterMaterializedViewSetOptions:
    def test_basic(self, dialect):
        expr = BigQueryAlterMaterializedViewSetOptionsExpression(
            dialect,
            MaterializedView(dialect, "mv"),
            {BigQueryMaterializedViewOption.REFRESH_INTERVAL_MINUTES: 20},
        )
        sql, params = expr.to_sql()
        assert sql == (
            "ALTER MATERIALIZED VIEW `mv` "
            "SET OPTIONS(refresh_interval_minutes = 20)"
        )
        assert params == ()

    def test_if_exists(self, dialect):
        expr = BigQueryAlterMaterializedViewSetOptionsExpression(
            dialect,
            MaterializedView(dialect, "mv"),
            {BigQueryMaterializedViewOption.ENABLE_REFRESH: False},
            if_exists=True,
        )
        assert "ALTER MATERIALIZED VIEW IF EXISTS `mv`" in expr.to_sql()[0]

    def test_empty_options_rejected(self, dialect):
        with pytest.raises(ValueError, match="options"):
            BigQueryAlterMaterializedViewSetOptionsExpression(
                dialect, MaterializedView(dialect, "mv"), {}
            )

    def test_undocumented_option_rejected(self, dialect):
        with pytest.raises(ValueError, match="does not document"):
            BigQueryAlterMaterializedViewSetOptionsExpression(
                dialect, MaterializedView(dialect, "mv"), {"enable_reffresh": True}
            )


class TestMaterializedViewReplica:
    def test_basic(self, dialect):
        expr = BigQueryCreateMaterializedViewReplicaExpression(
            dialect,
            MaterializedView(dialect, "mv_replica"),
            MaterializedView(dialect, "mv_source"),
        )
        assert expr.to_sql()[0] == (
            "CREATE MATERIALIZED VIEW `mv_replica` AS REPLICA OF `mv_source`"
        )

    def test_replica_and_source_may_live_in_different_datasets(self, dialect):
        """The two views carry their own dataset.

        A replica normally sits in a different dataset from the view it
        mirrors. Reusing one namespace for both made that inexpressible.
        """
        expr = BigQueryCreateMaterializedViewReplicaExpression(
            dialect,
            MaterializedView(dialect, "mv_replica", schema_name="warehouse"),
            MaterializedView(dialect, "mv_source", schema_name="sales"),
        )
        assert expr.to_sql()[0] == (
            "CREATE MATERIALIZED VIEW `warehouse`.`mv_replica` "
            "AS REPLICA OF `sales`.`mv_source`"
        )

    def test_a_bare_string_never_renders(self, dialect):
        """The kind check is a real one now, and it names the field it refused.

        ``replica`` is annotated ``MaterializedView``, so a string cannot say
        which dataset the replica lives in. It used to reach ``AttributeError``
        by accident, on the missing attribute the formatter happened to read
        next -- an error that would not have distinguished a wrong object from
        a missing one. The formatter now checks the kind before rendering, so the
        refusal names the parameter and says what it wanted instead.
        """
        expr = BigQueryCreateMaterializedViewReplicaExpression(
            dialect, "mv_replica", MaterializedView(dialect, "mv_source")
        )
        with pytest.raises(TypeError) as exc_info:
            expr.to_sql()
        assert (
            "BigQueryCreateMaterializedViewReplicaExpression.replica must be a "
            "MaterializedView, got str" in str(exc_info.value)
        )

    def test_a_bare_string_source_view_is_refused_too(self, dialect):
        """The two objects are chosen independently, so both are checked.

        The source view is the second of the pair, and a replica usually lives in
        a different dataset from the view it mirrors -- which is exactly why the
        two are separate parameters and each has to be right.
        """
        expr = BigQueryCreateMaterializedViewReplicaExpression(
            dialect, MaterializedView(dialect, "mv_replica"), "mv_source"
        )
        with pytest.raises(TypeError) as exc_info:
            expr.to_sql()
        assert (
            "BigQueryCreateMaterializedViewReplicaExpression.source_view must be "
            "a MaterializedView, got str" in str(exc_info.value)
        )

    def test_with_interval(self, dialect):
        expr = BigQueryCreateMaterializedViewReplicaExpression(
            dialect,
            MaterializedView(dialect, "mv_replica"),
            MaterializedView(dialect, "mv_source"), replication_interval_seconds=600
        )
        assert "OPTIONS(replication_interval_seconds = 600)" in expr.to_sql()[0]

    @pytest.mark.parametrize("seconds", [59, 3601, 0, -1])
    def test_interval_bounds_enforced(self, dialect, seconds):
        """Documented range is 60..3600 inclusive."""
        with pytest.raises(ValueError, match="replication_interval_seconds"):
            BigQueryCreateMaterializedViewReplicaExpression(
                dialect,
                MaterializedView(dialect, "mv_replica"),
                MaterializedView(dialect, "mv_source"), replication_interval_seconds=seconds
            )

    def test_documented_defaults(self):
        expr_cls = BigQueryCreateMaterializedViewReplicaExpression
        assert expr_cls.MIN_REPLICATION_INTERVAL_SECONDS == 60
        assert expr_cls.MAX_REPLICATION_INTERVAL_SECONDS == 3600
        assert expr_cls.DEFAULT_REPLICATION_INTERVAL_SECONDS == 300


class TestMaterializedViewOptionCatalogue:
    """Option names are validated against the documented catalogue."""

    def test_catalogue_contents(self):
        values = {member.value for member in BigQueryMaterializedViewOption}
        assert values == {
            "enable_refresh",
            "refresh_interval_minutes",
            "expiration_timestamp",
            "max_staleness",
            "allow_non_incremental_definition",
            "kms_key_name",
            "friendly_name",
            "description",
            "labels",
            "tags",
        }

    def test_lookup_by_name_and_member(self):
        assert resolve_materialized_view_option("enable_refresh") is (
            BigQueryMaterializedViewOption.ENABLE_REFRESH
        )
        assert resolve_materialized_view_option(
            BigQueryMaterializedViewOption.LABELS
        ) is BigQueryMaterializedViewOption.LABELS
        assert resolve_materialized_view_option("enable_reffresh") is None
        assert resolve_materialized_view_option(None) is None

    def test_value_types(self):
        assert (
            BigQueryMaterializedViewOption.ENABLE_REFRESH.value_type
            is BigQueryMaterializedViewOptionValueType.BOOLEAN
        )
        assert (
            BigQueryMaterializedViewOption.REFRESH_INTERVAL_MINUTES.value_type
            is BigQueryMaterializedViewOptionValueType.FLOAT64
        )
        assert (
            BigQueryMaterializedViewOption.LABELS.value_type
            is BigQueryMaterializedViewOptionValueType.LABEL_ARRAY
        )

    def test_documented_defaults(self):
        assert BigQueryMaterializedViewOption.ENABLE_REFRESH.default == "true"
        assert BigQueryMaterializedViewOption.REFRESH_INTERVAL_MINUTES.default == "30"
        assert BigQueryMaterializedViewOption.LABELS.default is None

    def test_validate_rejects_undocumented(self):
        with pytest.raises(ValueError, match="does not document"):
            validate_materialized_view_options({"refresh_every": "1h"})

    def test_validate_requires_mapping(self):
        with pytest.raises(TypeError):
            validate_materialized_view_options(["enable_refresh"])
