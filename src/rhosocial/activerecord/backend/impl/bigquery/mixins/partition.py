# src/rhosocial/activerecord/backend/impl/bigquery/mixins/partition.py
"""BigQuery table-partition DDL formatter mixin.

This is the backend-named feature group for the proprietary partition clause
in ``impl.bigquery.expression.partition``. Core has no counterpart, so this
mixin owns the one formatter the clause declares through ``format_method``.
"""

import re
from typing import Tuple, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from ..expression.partition import (
        BigQueryCreateTableStatement,
        BigQueryPartitionDecoratedTable,
        BigQueryTablePartitionByClause,
    )


_BARE_IDENTIFIER = r"[A-Za-z_][A-Za-z0-9_]*"
_QUOTED_IDENTIFIER = r"`[A-Za-z_][A-Za-z0-9_]*`"
_IDENTIFIER = rf"(?:{_QUOTED_IDENTIFIER}|{_BARE_IDENTIFIER})"
_TRUNCATION = (
    r"(?:DATE|TIMESTAMP|DATETIME)(?:_TRUNC)?\s*\(\s*"
    + _IDENTIFIER
    + r"(?:\s*,\s*(?:DAY|WEEK|MONTH|QUARTER|YEAR))?\s*\)"
)
_RANGE_BUCKET = (
    r"RANGE_BUCKET\s*\(\s*"
    + _IDENTIFIER
    + r"\s*,\s*GENERATE_ARRAY\s*\(\s*-?\d+\s*,\s*-?\d+\s*,\s*[1-9]\d*\s*\)\s*\)"
)
_PARTITION_EXPRESSION = re.compile(
    rf"(?:{_TRUNCATION}|{_RANGE_BUCKET})", re.IGNORECASE
)
_CLUSTER_COLUMN = re.compile(_IDENTIFIER, re.IGNORECASE)
_MAX_CLUSTER_COLUMNS = 4
_PARTITION_DECORATOR = re.compile(r"(?:\d{8}|__NULL__|__UNPARTITIONED__)")


class BigQueryPartitionMixin:
    """Format BigQuery's proprietary table-level partition clause."""

    def format_bigquery_table_partition_by_clause(
        self, expr: "BigQueryTablePartitionByClause"
    ) -> Tuple[str, tuple]:
        """Render ``PARTITION BY ...`` and/or ``CLUSTER BY ...``.

        Args:
            expr: the clause carrying a partitioning expression and optional
                clustering columns.

        Returns:
            The SQL fragment with a leading space, ready to append to a
            ``CREATE TABLE`` statement, and an empty parameter tuple.

        Raises:
            ValueError: if the collected expression or columns are empty or
                use a spelling GoogleSQL does not accept. The offending value
                is named in the message.
        """
        expression = expr.partition_expression
        cluster_by = expr.cluster_by
        parts = []

        if expression is not None:
            if not isinstance(expression, str) or not expression.strip():
                raise ValueError(
                    "BigQuery PARTITION BY expression must be a non-empty string, "
                    f"got {expression!r}"
                )
            spec = expression.strip()
            if not _PARTITION_EXPRESSION.fullmatch(spec):
                raise ValueError(
                    f"unsupported BigQuery PARTITION BY expression {spec!r}; "
                    "expected DATE/TIMESTAMP/DATETIME truncation or "
                    "RANGE_BUCKET(col, GENERATE_ARRAY(start, end, step))"
                )
            parts.append(f" PARTITION BY {spec}")

        if cluster_by is not None:
            if isinstance(cluster_by, str) or not cluster_by:
                raise ValueError(
                    "BigQuery CLUSTER BY must be a non-empty sequence of column "
                    f"names, got {cluster_by!r}"
                )
            rendered = []
            seen = set()
            for column in cluster_by:
                if not isinstance(column, str) or not _CLUSTER_COLUMN.fullmatch(
                    column.strip()
                ):
                    raise ValueError(
                        f"unsupported BigQuery CLUSTER BY column {column!r}"
                    )
                name = column.strip()
                folded = name.lower()
                if folded in seen:
                    raise ValueError(f"duplicate BigQuery CLUSTER BY column {name!r}")
                seen.add(folded)
                rendered.append(name)
            if len(rendered) > _MAX_CLUSTER_COLUMNS:
                raise ValueError(
                    f"BigQuery CLUSTER BY accepts at most {_MAX_CLUSTER_COLUMNS} columns, "
                    f"got {len(rendered)}"
                )
            parts.append(f" CLUSTER BY {', '.join(rendered)}")

        if not parts:
            raise ValueError(
                "BigQuery partition clause requires a partition expression or "
                "CLUSTER BY columns"
            )
        return "".join(parts), ()

    def format_bigquery_partition_decorated_table(
        self, expr: "BigQueryPartitionDecoratedTable"
    ) -> Tuple[str, tuple]:
        """Render a table name with a BigQuery partition decorator.

        GoogleSQL addresses a partition by appending ``$<decorator>``: an
        eight-digit date (``$20260101``), or the sentinels ``$__NULL__`` /
        ``$__UNPARTITIONED__``. The base name is rendered by this dialect's
        standard table formatter; the decorator is validated here.

        Args:
            expr: the decorated table reference.

        Returns:
            The decorated name and its parameters.

        Raises:
            ValueError: if the decorator is empty or uses a spelling BigQuery
                does not accept.
        """
        decorator = expr.partition
        if not isinstance(decorator, str) or not decorator.strip():
            raise ValueError(
                f"BigQuery partition decorator must be a non-empty string, "
                f"got {decorator!r}"
            )
        spec = decorator.strip()
        if not _PARTITION_DECORATOR.fullmatch(spec):
            raise ValueError(
                f"unsupported BigQuery partition decorator {spec!r}; expected "
                "an eight-digit date (YYYYMMDD) or __NULL__ / __UNPARTITIONED__"
            )
        base_sql, params = self.format_table_object(expr)
        return f"{base_sql}${spec}", params

    def format_bigquery_create_table_statement(
        self, expr: "BigQueryCreateTableStatement"
    ) -> Tuple[str, tuple]:
        """Render core's ``CREATE TABLE`` and append BigQuery's partition clause.

        Args:
            expr: the BigQuery create-table statement carrying an optional
                ``partition_by`` clause.

        Returns:
            The full SQL statement and its bind parameters.
        """
        sql, params = super().format_create_table_statement(expr)
        clause = expr.partition_by
        if clause is not None:
            clause_sql, clause_params = clause.to_sql()
            if clause_sql:
                sql = sql + clause_sql
                params = tuple(params) + tuple(clause_params)
        return sql, params


__all__ = ["BigQueryPartitionMixin"]
