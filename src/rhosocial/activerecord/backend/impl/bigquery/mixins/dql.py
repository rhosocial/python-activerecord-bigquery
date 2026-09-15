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
