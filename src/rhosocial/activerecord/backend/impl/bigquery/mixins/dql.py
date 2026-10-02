# src/rhosocial/activerecord/backend/impl/bigquery/mixins/dql.py
"""BigQuery DQL (Data Query Language) mixin."""
from __future__ import annotations

from typing import Tuple, TYPE_CHECKING

from rhosocial.activerecord.backend.expression.query_sources import SetOperationExpression

if TYPE_CHECKING:
    from rhosocial.activerecord.backend.expression.core import Column, WildcardExpression


class BigQueryDQLMixin:
    """BigQuery DQL formatting overrides."""

    def format_set_operation_expression(self, expr: SetOperationExpression) -> Tuple[str, tuple]:
        def _render(node) -> Tuple[str, list]:
            sql, params = node.to_sql()
            if isinstance(node, SetOperationExpression):
                sql = f"({sql})"
            return sql, list(params)

        left_sql, left_params = _render(expr.left)
        right_sql, right_params = _render(expr.right)
        qualifier = " ALL" if expr.all_ else " DISTINCT"
        base_sql = f"{left_sql} {expr.operation}{qualifier} {right_sql}"
        all_params = left_params + right_params
        sql_parts = [base_sql]
        if expr.alias:
            sql_parts.append(f"AS {self.format_identifier(expr.alias)}")
        if expr.for_update_clause:
            from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError

            raise UnsupportedFeatureError(
                self.name,
                "FOR UPDATE in set operations",
                "BigQuery does not support FOR UPDATE in a set operation.",
            )
        for clause in (expr.order_by_clause, expr.limit_offset_clause):
            if clause:
                clause_sql, clause_params = clause.to_sql()
                sql_parts.append(clause_sql)
                all_params.extend(clause_params)
        return " ".join(sql_parts), tuple(all_params)

    def supports_fetch_with_ties(self) -> bool:
        """BigQuery does not support FETCH ... WITH TIES."""
        return False

    def supports_nulls_first_last(self) -> bool:
        """BigQuery does not support explicit NULLS FIRST/LAST ordering."""
        return False

    def format_column(self, expr: Column) -> Tuple[str, tuple]:
        """Column references are never schema-qualified in BigQuery."""
        from rhosocial.activerecord.backend.dialect.protocols import SchemaSupport

        if isinstance(self, SchemaSupport):
            self.validate_schema_name(expr)

        if expr.schema_name and not expr.table:
            # A column reference cannot be qualified without a table. The core
            # dialect raises here; BigQuery never schema-qualifies columns at
            # all, so this is meaningless rather than dangerous. Warn instead
            # of raising so one model definition can still target both
            # PostgreSQL and BigQuery.
            _warn_qualification_dropped(self.name, expr, "BigQuery")
        if expr.table:
            col_sql = (
                f"{self.format_identifier(expr.table, expr.table_need_quote)}."
                f"{self.format_identifier(expr.name, expr.name_need_quote)}"
            )
        else:
            col_sql = self.format_identifier(expr.name, expr.name_need_quote)
        if expr.alias:
            col_sql = f"{col_sql} AS {self.format_identifier(expr.alias, expr.alias_need_quote)}"
        return col_sql, ()

    def format_wildcard(self, expr: WildcardExpression) -> Tuple[str, tuple]:
        """Wildcard references in BigQuery use the (2-part) table name only."""
        if expr.table:
            return f"{self.format_identifier(expr.table, expr.table_need_quote)}.*", ()
        return "*", ()


__all__ = ['BigQueryDQLMixin']


def _warn_qualification_dropped(dialect_name: str, expr, label: str) -> None:
    """Warn that a supplied ``schema_name`` cannot be rendered on a bare column."""
    import warnings

    warnings.warn(
        f"{label}: dropping schema_name={expr.schema_name!r} from column "
        f"{expr.name!r} because no table was given; a column reference needs "
        "a table to be qualified",
        UserWarning,
        stacklevel=3,
    )
