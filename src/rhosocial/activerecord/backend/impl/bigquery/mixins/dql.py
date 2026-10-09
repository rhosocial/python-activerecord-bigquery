# src/rhosocial/activerecord/backend/impl/bigquery/mixins/dql.py
"""BigQuery DQL (Data Query Language) mixin."""
from __future__ import annotations

from typing import Tuple, TYPE_CHECKING

from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError
from rhosocial.activerecord.backend.expression.query_sources import SetOperationExpression

if TYPE_CHECKING:
    from rhosocial.activerecord.backend.expression.core import Column, WildcardExpression


class BigQueryDQLMixin:
    """BigQuery DQL formatting overrides."""

    def format_set_operation_expression(self, expr: SetOperationExpression) -> Tuple[str, tuple]:
        """Format a set operation with GoogleSQL's required qualifier.

        BigQuery's grammar has no bare set operator::

            set_operator:
              UNION { ALL | DISTINCT } | INTERSECT DISTINCT | EXCEPT DISTINCT

        so the pair is consumed three ways, not two:

        * ``all_`` -> `` ALL``, and only for ``UNION``: the grammar has no
          ``INTERSECT ALL`` / ``EXCEPT ALL``, so those requests are refused by
          name rather than emitted;
        * ``distinct`` -> `` DISTINCT``;
        * neither -> `` DISTINCT`` as well.  BigQuery cannot spell the absence
          of the qualifier, and ``DISTINCT`` is the standard's default for a
          bare ``UNION`` (the Redshift migration guide rewrites a bare
          ``UNION`` as ``UNION DISTINCT``); the audit records this dialect
          property as "BigQuery: falsy forces DISTINCT, so 'unspecified' is
          unreachable there".  Emitting the bare operator would be invalid
          SQL, and refusing would break every ORM ``union()`` call that leaves
          the qualifier unset, so the dialect spells its required default.

        The two requests are distinguishable at the API (one sets a
        parameter); they cannot be distinguished in SQL on this dialect
        because there is no second spelling for "no qualifier".

        Raises:
            UnsupportedFeatureError: ``all_`` requested for an operation
                whose grammar is DISTINCT-only.
        """
        def _render(node) -> Tuple[str, list]:
            sql, params = node.to_sql()
            if isinstance(node, SetOperationExpression):
                sql = f"({sql})"
            return sql, list(params)

        left_sql, left_params = _render(expr.left)
        right_sql, right_params = _render(expr.right)
        operation = expr.operation
        if expr.all_:
            if operation.strip().upper() != "UNION":
                raise UnsupportedFeatureError(
                    self.name,
                    f"{operation} ALL",
                    suggestion=(
                        "BigQuery's set-operator grammar is "
                        "UNION { ALL | DISTINCT } | INTERSECT DISTINCT | "
                        "EXCEPT DISTINCT."
                    ),
                )
            qualifier = " ALL"
        elif expr.distinct:
            qualifier = " DISTINCT"
        else:
            # See the docstring: the dialect's grammar requires a qualifier,
            # and DISTINCT is the default spelling of the unqualified request.
            qualifier = " DISTINCT"
        base_sql = f"{left_sql} {operation}{qualifier} {right_sql}"
        all_params = left_params + right_params
        sql_parts = [base_sql]
        if expr.alias:
            sql_parts.append(f"AS {self.format_identifier(expr.alias)}")
        if expr.for_update_clause:
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

    def format_wildcard(self, expr: WildcardExpression) -> Tuple[str, tuple]:
        """Wildcard references in BigQuery use the (2-part) table name only."""
        if expr.table:
            return f"{self.format_identifier(expr.table, expr.table_need_quote)}.*", ()
        return "*", ()


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
