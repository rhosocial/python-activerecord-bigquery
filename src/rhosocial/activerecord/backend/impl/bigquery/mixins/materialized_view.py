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
from rhosocial.activerecord.backend.expression.objects import MaterializedView

from ..materialized_view_options import resolve_materialized_view_option

if TYPE_CHECKING:  # pragma: no cover
    from rhosocial.activerecord.backend.expression.statements.ddl_view import (
        CreateMaterializedViewExpression,
        DropMaterializedViewExpression,
    )

    from ..expression.materialized_view import (
        BigQueryAlterMaterializedViewSetOptionsExpression,
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
        self, expr: "CreateMaterializedViewExpression"
    ) -> Tuple[str, tuple]:
        """Format ``CREATE [OR REPLACE] MATERIALIZED VIEW [IF NOT EXISTS]``.

        Args:
            expr: BigQuery or generic create expression, carrying the view it
                acts on.

        Returns:
            Tuple of (SQL string, params tuple) from the defining query.

        Raises:
            TypeError: ``expr.view`` is not a MaterializedView. Another object
                kind would have had its own name rendered as the view's, and the
                statement would still be well-formed SQL.
            UnsupportedFeatureError: for clauses BigQuery does not have.
        """
        self._require_materialized_view(expr, "CreateMaterializedViewExpression")
        self._reject_unsupported_clauses(expr, "CREATE MATERIALIZED VIEW")

        parts = ["CREATE"]
        if getattr(expr, "or_replace", False):
            parts.append("OR REPLACE")
        parts.append("MATERIALIZED VIEW")
        if getattr(expr, "if_not_exists", False):
            parts.append("IF NOT EXISTS")
        parts.append(self._materialized_view_name_sql(expr))

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

    def format_drop_materialized_view_statement(
        self, expr: "DropMaterializedViewExpression"
    ) -> Tuple[str, tuple]:
        """Format ``DROP MATERIALIZED VIEW [IF EXISTS]``.

        Args:
            expr: BigQuery or generic drop expression, carrying the view.

        Raises:
            TypeError: ``expr.view`` is not a MaterializedView.
            UnsupportedFeatureError: BigQuery has no ``CASCADE`` here.
        """
        self._require_materialized_view(expr, "DropMaterializedViewExpression")
        if getattr(expr, "cascade", False):
            raise UnsupportedFeatureError(
                self.name, "DROP MATERIALIZED VIEW CASCADE"
            )
        parts = ["DROP MATERIALIZED VIEW"]
        if getattr(expr, "if_exists", False):
            parts.append("IF EXISTS")
        parts.append(self._materialized_view_name_sql(expr))
        return " ".join(parts), ()

    def format_alter_materialized_view_set_options_statement(
        self, expr: "BigQueryAlterMaterializedViewSetOptionsExpression"
    ) -> Tuple[str, tuple]:
        """Format ``ALTER MATERIALIZED VIEW [IF EXISTS] ... SET OPTIONS(...)``.

        Raises:
            TypeError: ``expr.view`` is not a MaterializedView.
        """
        self._require_materialized_view(
            expr, "BigQueryAlterMaterializedViewSetOptionsExpression"
        )
        parts = ["ALTER MATERIALIZED VIEW"]
        if getattr(expr, "if_exists", False):
            parts.append("IF EXISTS")
        parts.append(self._materialized_view_name_sql(expr))
        options = self._format_materialized_view_options(expr.options)
        parts.append(f"SET OPTIONS({options})")
        return " ".join(parts), ()

    def format_create_materialized_view_replica_statement(
        self, expr: "BigQueryCreateMaterializedViewReplicaExpression"
    ) -> Tuple[str, tuple]:
        """Format ``CREATE MATERIALIZED VIEW replica ... AS REPLICA OF source``.

        Two objects, checked separately: a replica usually lives in a different
        dataset from the view it mirrors, so the two are chosen independently
        and either could be the wrong kind.

        Raises:
            TypeError: ``expr.replica`` or ``expr.source_view`` is not a
                MaterializedView.
        """
        for label, candidate in (
            ("replica", expr.replica),
            ("source_view", expr.source_view),
        ):
            if not isinstance(candidate, MaterializedView):
                raise TypeError(
                    f"BigQueryCreateMaterializedViewReplicaExpression.{label} must "
                    f"be a MaterializedView, got {type(candidate).__name__}"
                )
        replica_sql, _ = expr.replica.to_sql()
        source_sql, _ = expr.source_view.to_sql()
        parts = ["CREATE MATERIALIZED VIEW", replica_sql]
        interval = expr.replication_interval_seconds
        if interval is not None:
            parts.append(
                "OPTIONS(replication_interval_seconds = " f"{int(interval)})"
            )
        parts.append(f"AS REPLICA OF {source_sql}")
        return " ".join(parts), ()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _require_materialized_view(expr: Any, statement: str) -> None:
        """Refuse a statement whose target is not a materialized view.

        Every one of these four formatters is reached by name -- a view's
        ``format_method`` says which formatter renders it -- so nothing about the
        dispatch tells them whether the object they were handed is the kind the
        statement acts on. Left unchecked, ``CreateMaterializedViewExpression``
        given a ``Table`` renders ``CREATE MATERIALIZED VIEW`orders` ...``: the
        object's own ``format_table_object`` produces valid SQL, so the result
        is a well-formed statement about the wrong object and nothing says so.

        The check lives here, where the four statements meet, rather than
        repeated in each. The message names the statement, because which of the
        four refused is what tells a caller where the wrong object came from.
        """
        if not isinstance(expr.view, MaterializedView):
            raise TypeError(
                f"{statement}.view must be a MaterializedView, "
                f"got {type(expr.view).__name__}"
            )

    def _materialized_view_name_sql(self, expr: Any) -> str:
        """The one place a materialized view's own name becomes SQL.

        The statement holds the object, and the object renders itself through
        ``format_materialized_view_object``. ``CREATE``, ``DROP`` and
        ``ALTER ... SET OPTIONS`` all read that one object, so a qualified form
        cannot reach one statement and miss the next.
        """
        name_sql, _params = expr.view.to_sql()
        return name_sql

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