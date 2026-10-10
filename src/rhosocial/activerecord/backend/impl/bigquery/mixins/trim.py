# src/rhosocial/activerecord/backend/impl/bigquery/mixins/trim.py
"""BigQuery's TRIM spelling: the direction is the function name.

BigQuery has no ANSI ``TRIM(BOTH ... FROM ...)`` form. Its ``TRIM`` takes the
value and an optional character set and always removes from both ends, and the
direction is carried by separate ``LTRIM`` / ``RTRIM`` functions, so the shared
default renderer's output is not merely differently spelled -- it is syntax the
server rejects. The mapping is a substitution of the function name:

    BOTH     -> ``TRIM(x[, chars])``
    LEADING  -> ``LTRIM(x[, chars])``
    TRAILING -> ``RTRIM(x[, chars])``

Everything else about the node (the operands' parameters in order, the
optional alias) is the default's, so only the name differs.

BigQuery documents trimming of the leading and trailing occurrences of the
given characters, which is the ANSI ``BOTH`` case; the ``LEADING`` /
``TRAILING`` spellings are the two one-sided functions, which take the same
optional character set. This mixin does not attempt to gate on the BigQuery
release because the dialect has no mechanism for it.
"""
from typing import Tuple, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from ...expression.advanced_functions import TrimExpression


class BigQueryTrimMixin:
    """Mixin rendering the TRIM family as BigQuery's TRIM/LTRIM/RTRIM."""

    _TRIM_FUNCTIONS = {"BOTH": "TRIM", "LEADING": "LTRIM", "TRAILING": "RTRIM"}

    def format_trim_expression(self, expr: "TrimExpression") -> Tuple[str, Tuple]:
        """Format a TRIM node in BigQuery's form.

        Args:
            expr: Trim expression exposing ``expr``, ``chars``, ``direction``
                and an optional ``alias``.

        Returns:
            Tuple of (SQL string, parameters tuple), carrying the operands'
            parameters in order.

        Raises:
            ValueError: ``expr.direction`` is not one of the three the node
                allows.
        """
        target_sql, target_params = expr.expr.to_sql()
        function = self._TRIM_FUNCTIONS.get(expr.direction)
        if function is None:
            raise ValueError(
                f"Unsupported trim direction {expr.direction!r}; expected one of "
                f"{sorted(self._TRIM_FUNCTIONS)}"
            )
        if expr.chars is not None:
            chars_sql, chars_params = expr.chars.to_sql()
            sql = f"{function}({target_sql}, {chars_sql})"
            params = tuple(target_params) + tuple(chars_params)
        else:
            sql = f"{function}({target_sql})"
            params = tuple(target_params)
        if expr.alias:
            sql = f"{sql} AS {self.format_identifier(expr.alias)}"
        return sql, params


__all__ = ['BigQueryTrimMixin']
