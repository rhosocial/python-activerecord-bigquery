# src/rhosocial/activerecord/backend/impl/bigquery/mixins/dql.py
"""BigQuery DQL (Data Query Language) mixin."""
from __future__ import annotations

from typing import Tuple, TYPE_CHECKING

from rhosocial.activerecord.backend.expression.query_sources import SetOperation

if TYPE_CHECKING:
    from rhosocial.activerecord.backend.expression.core import Column

#: The node's operation words mapped to the spelling GoogleSQL needs. Every
#: entry carries the explicit ALL/DISTINCT qualifier the grammar requires --
#: see the method docstring for why none of them can drop it.
_OP_SPELLINGS = {
    "union": "UNION DISTINCT",
    "union_all": "UNION ALL",
    "intersect": "INTERSECT DISTINCT",
    "except": "EXCEPT DISTINCT",
}


class BigQueryDQLMixin:
    """BigQuery DQL formatting overrides."""

    def format_set_operation(self, expr: SetOperation) -> Tuple[str, tuple]:
        """Format a set operation with GoogleSQL's required qualifier.

        BigQuery's grammar has no bare set operator::

            set_operator:
              UNION { ALL | DISTINCT } | INTERSECT DISTINCT | EXCEPT DISTINCT

        The node names the operation with a **word** (``union`` /
        ``union_all`` / ``intersect`` / ``except``) and this method maps each
        word to the spelling this backend writes. Every spelling carries an
        explicit ``ALL`` or ``DISTINCT``, because the grammar has no bare
        form: a bare SQL-standard ``UNION`` means ``UNION DISTINCT`` (the
        Redshift-to-BigQuery migration guide rewrites it that way), and
        emitting the bare operator would be invalid SQL.

        That the qualifier is mandatory is now *structural* rather than a
        refusal this formatter has to raise: the word set has no member that
        asks for an unspelled operator, so "neither set nor a qualifier is
        requested" cannot be written at all. ``union`` and ``union_all`` are
        told apart by the modifier alone.

        The grammar has no ``INTERSECT ALL`` / ``EXCEPT ALL``. That too is now
        structural: there is no ``intersect_all`` / ``except_all`` word, so the
        request cannot be spelled and there is nothing left to refuse by name.

        Args:
            expr: The node exposing ``op`` (a word form), ``left`` and
                ``right``.

        Returns:
            Tuple of (SQL string, parameters tuple), carrying the operands'
            parameters in order.
        """
        def _render(node) -> Tuple[str, list]:
            sql, params = node.to_sql()
            if isinstance(node, SetOperation):
                sql = f"({sql})"
            return sql, list(params)

        left_sql, left_params = _render(expr.left)
        right_sql, right_params = _render(expr.right)
        base_sql = f"{left_sql} {_OP_SPELLINGS[expr.op]} {right_sql}"
        return base_sql, tuple(left_params + right_params)

    def supports_fetch_with_ties(self) -> bool:
        """BigQuery does not support FETCH ... WITH TIES."""
        return False

    def supports_nulls_first_last(self) -> bool:
        """BigQuery does not support explicit NULLS FIRST/LAST ordering."""
        return False

    def supports_column_namespace_qualification(self) -> bool:
        """BigQuery never prefixes a column with a project or a dataset.

        GoogleSQL has no ``dataset.column`` construct. A column is qualified by
        its relation -- ``table.column``, or the fully qualified
        ``project.dataset.table.column`` path when a query reaches across
        datasets -- and the namespace belongs to the relation named in the
        FROM clause. A namespace on the column alone is therefore not
        something this dialect renders.

        Declared rather than assumed, because the distinction is what makes
        the error in :meth:`format_column` possible: leaving the namespace out
        is correct when a table carries it, and indefensible when nothing does.
        """
        return False

    def format_column(self, expr: Column) -> Tuple[str, tuple]:
        """Format a column reference, which BigQuery qualifies by table only.

        Args:
            expr: The column being rendered.

        Returns:
            Tuple of (SQL string, empty params tuple).

        Raises:
            UnsupportedFeatureError: the column carries a dataset but no table.
                There is then no relation for the namespace to qualify, and the
                only two honest outcomes are to render it or to refuse it.
                Emitting a bare ``column`` would silently read a different
                table than the caller named.
        """
        if expr.schema_name and not self.supports_column_namespace_qualification():
            if not expr.table:
                raise UnsupportedFeatureError(
                    self.name,
                    "schema-qualified column references",
                    suggestion=(
                        f"column {expr.name!r} carries "
                        f"schema_name={expr.schema_name!r} but no table, and "
                        f"{self.name} qualifies a column by its relation only; "
                        f"put the dataset on the FROM relation, or pass "
                        f"table=... as well"
                    ),
                )

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

    def format_datetime_diff_expression(self, expr) -> Tuple[str, tuple]:
        """Format ``DATE_DIFF(end, start, part)``.

        BigQuery takes its arguments in the opposite order to everyone else --
        the end date first -- so a generic ``date_diff(unit, start, end)`` has
        to be swapped here or every call would measure the wrong span.

        The parts are not one-to-one either: BigQuery has no WEEK part, so a
        week is seven days, and MONTH/YEAR/QUARTER are the calendar ones rather
        than fixed spans.

        Args:
            expr: The expression carrying ``unit``, ``start`` and ``end``.

        Returns:
            A ``(sql, params)`` tuple.

        Raises:
            UnsupportedFeatureError: For a part BigQuery has no spelling for.
        """
        from rhosocial.activerecord.backend.dialect.exceptions import (
            UnsupportedFeatureError,
        )
        from rhosocial.activerecord.backend.dialect.base import SQLDialectBase

        # The units the framework's IntervalUnit defines. BigQuery's DATE_DIFF
        # has more parts -- WEEKDAY, ISOWEEK, QUARTER -- but a caller cannot
        # name them here, so listing them would be a promise nobody can keep.
        parts = {
            "day": "DAY", "hour": "HOUR", "minute": "MINUTE",
            "second": "SECOND", "month": "MONTH", "year": "YEAR",
            # BigQuery has no week part; a week is exactly seven days.
            "week": None,
        }
        unit = expr.unit.value.lower()
        if unit not in parts:
            raise UnsupportedFeatureError(
                self.name,
                f"date_diff({unit})",
                "BigQuery DATE_DIFF supports year, month, week, day, hour, "
                "minute and second.",
            )
        part = parts[unit] or "DAY"
        start_sql, start_params = expr.start.to_sql()
        end_sql, end_params = expr.end.to_sql()
        if parts[unit] is None:
            sql = f"DATE_DIFF({end_sql}, {start_sql}, DAY) / 7"
        else:
            sql = (
                f"DATE_DIFF({end_sql}, {start_sql}, "
                f"{SQLDialectBase._escape_sql_string(part)})"
            )
        return self.apply_alias(sql, end_params + start_params, expr)


__all__ = ['BigQueryDQLMixin']
