# src/rhosocial/activerecord/backend/impl/bigquery/mixins/materialized_view.py
"""BigQuery materialized view formatters.

BigQuery's materialized view DDL diverges from the SQL-standard statement in
ways that must not be papered over — see
:mod:`..expression.materialized_view` for the grammar. Anything the generic
expressions carry that BigQuery cannot express is rejected with
``UnsupportedFeatureError`` instead of being silently dropped.
"""
from typing import Any, Tuple, TYPE_CHECKING

from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError

from ..materialized_view_options import resolve_materialized_view_option

if TYPE_CHECKING:  # pragma: no cover
    from ..expression.materialized_view import (
        BigQueryAlterMaterializedViewSetOptionsExpression,
        BigQueryCreateMaterializedViewExpression,
        BigQueryCreateMaterializedViewReplicaExpression,
    )


class BigQueryMaterializedViewMixin:
    """BigQuery MATERIALIZED VIEW support.

    Must be listed before the core ``ViewMixin`` in ``BigQueryDialect`` so these
    formatters take precedence.
    """

    def supports_materialized_view(self) -> bool:
        """BigQuery has native materialized views."""
        return True

    def supports_refresh_materialized_view(self) -> bool:
        """BigQuery has no ``REFRESH MATERIALIZED VIEW`` statement.

        Refresh is scheduled through ``OPTIONS(enable_refresh=…,
        refresh_interval_minutes=…)``; use
        ``format_alter_materialized_view_set_options_statement`` to change it.
        """
        return False

    def supports_materialized_view_options(self) -> bool:
        """BigQuery configures materialized views through ``OPTIONS(...)``."""
        return True

    def supports_materialized_view_replica(self) -> bool:
        """BigQuery can create a replica of a materialized view."""
        return True

    # ------------------------------------------------------------------
    # Formatters
    # ------------------------------------------------------------------

    def format_create_materialized_view_statement(
        self, expr: "BigQueryCreateMaterializedViewExpression"
    ) -> Tuple[str, tuple]:
        """Format ``CREATE [OR REPLACE] MATERIALIZED VIEW [IF NOT EXISTS]``.

        Args:
            expr: BigQuery (or generic) create expression.

        Returns:
            Tuple of (SQL string, params tuple) from the defining query.

        Raises:
            UnsupportedFeatureError: for clauses BigQuery does not have.
        """
        self._reject_unsupported_clauses(expr, "CREATE MATERIALIZED VIEW")

        parts = ["CREATE"]
        if getattr(expr, "or_replace", False):
            parts.append("OR REPLACE")
        parts.append("MATERIALIZED VIEW")
        if getattr(expr, "if_not_exists", False):
            parts.append("IF NOT EXISTS")
        parts.append(self.format_identifier(expr.view_name))

        partition_by = getattr(expr, "partition_by", None)
        if partition_by:
            parts.append(f"PARTITION BY {partition_by}")

        cluster_by = getattr(expr, "cluster_by", None)
        if cluster_by:
            cols = ", ".join(str(column) for column in cluster_by)
            parts.append(f"CLUSTER BY {cols}")

        options = self._format_materialized_view_options(getattr(expr, "options", None))
        if options:
            parts.append(f"OPTIONS({options})")

        query_sql, query_params = self._materialized_view_query_sql(expr)
        parts.append(f"AS {query_sql}")
        return " ".join(parts), query_params

    def format_drop_materialized_view_statement(self, expr: Any) -> Tuple[str, tuple]:
        """Format ``DROP MATERIALIZED VIEW [IF EXISTS]``."""
        if getattr(expr, "cascade", False):
            raise UnsupportedFeatureError(
                self.name, "DROP MATERIALIZED VIEW CASCADE"
            )
        parts = ["DROP MATERIALIZED VIEW"]
        if getattr(expr, "if_exists", False):
            parts.append("IF EXISTS")
        parts.append(self.format_identifier(expr.view_name))
        return " ".join(parts), ()

    def format_alter_materialized_view_set_options_statement(
        self, expr: "BigQueryAlterMaterializedViewSetOptionsExpression"
    ) -> Tuple[str, tuple]:
        """Format ``ALTER MATERIALIZED VIEW [IF EXISTS] ... SET OPTIONS(...)``."""
        parts = ["ALTER MATERIALIZED VIEW"]
        if getattr(expr, "if_exists", False):
            parts.append("IF EXISTS")
        parts.append(self.format_identifier(expr.view_name))
        options = self._format_materialized_view_options(expr.options)
        parts.append(f"SET OPTIONS({options})")
        return " ".join(parts), ()

    def format_create_materialized_view_replica_statement(
        self, expr: "BigQueryCreateMaterializedViewReplicaExpression"
    ) -> Tuple[str, tuple]:
        """Format ``CREATE MATERIALIZED VIEW replica ... AS REPLICA OF source``."""
        parts = ["CREATE MATERIALIZED VIEW", self.format_identifier(expr.replica_name)]
        interval = getattr(expr, "replication_interval_seconds", None)
        if interval is not None:
            parts.append(
                "OPTIONS(replication_interval_seconds = " f"{int(interval)})"
            )
        parts.append(f"AS REPLICA OF {self.format_identifier(expr.source_view_name)}")
        return " ".join(parts), ()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _reject_unsupported_clauses(self, expr: Any, feature: str) -> None:
        """Reject generic-expression clauses BigQuery cannot express."""
        if getattr(expr, "column_aliases", None):
            raise UnsupportedFeatureError(
                self.name,
                f"{feature} COLUMN ALIASES",
                "BigQuery materialized views take their column names from the query.",
            )
        if getattr(expr, "tablespace", None):
            raise UnsupportedFeatureError(self.name, f"{feature} TABLESPACE")
        if getattr(expr, "storage_options", None):
            raise UnsupportedFeatureError(
                self.name,
                f"{feature} STORAGE PARAMETERS",
                "BigQuery configures materialized views through OPTIONS(...).",
            )
        if getattr(expr, "with_data", True) is False:
            raise UnsupportedFeatureError(
                self.name,
                f"{feature} WITH NO DATA",
                "BigQuery populates the view at creation time.",
            )

    def _materialized_view_query_sql(self, expr: Any) -> Tuple[str, tuple]:
        """Return the defining query SQL, accepting an expression or raw SQL."""
        query = getattr(expr, "query", None)
        if query is None:
            raise ValueError("CREATE MATERIALIZED VIEW requires a defining query")
        if isinstance(query, str):
            return query, ()
        return query.to_sql()

    def _format_materialized_view_options(self, options: Any) -> str:
        """Render ``OPTIONS(...)`` entries using documented option names."""
        if not options:
            return ""
        rendered = []
        for name, value in options.items():
            option = resolve_materialized_view_option(name)
            key = option.value if option is not None else str(name)
            if isinstance(value, bool):
                literal = "true" if value else "false"
            elif isinstance(value, str):
                # _escape_sql_string escapes the body; the quotes are ours.
                literal = f"'{self._escape_sql_string(value)}'"
            else:
                literal = str(value)
            rendered.append(f"{key} = {literal}")
        return ", ".join(rendered)
