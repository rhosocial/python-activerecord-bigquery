# src/rhosocial/activerecord/backend/impl/bigquery/mixins/partition.py
"""BigQuery table-partition DDL formatter mixin.

This is the backend-named feature group for the proprietary partition clause
in ``impl.bigquery.expression.partition``.  It composes core's
``PartitionMixin`` -- the capability surface (``supports_table_partitioning``,
``partition_capability`` and the per-strategy gates) -- and adds the one
formatter core has no counterpart for: the BigQuery-specific
``PARTITION BY`` / ``CLUSTER BY`` clause.

The generic ``PARTITION BY <method> (<keys>)`` shape is not GoogleSQL, so the
inherited per-strategy gates all answer ``False`` and the inherited formatters
refuse by name.  BigQuery's partitioning is expressed through
``PARTITION BY <partition_expression>``: time-unit column partitioning
(``DATE`` / ``TIMESTAMP_TRUNC`` / ``DATETIME_TRUNC``) and integer range
partitioning (``RANGE_BUCKET(col, GENERATE_ARRAY(start, end, step))``).  Those
spellings belong to :class:`BigQueryTablePartitionByClause`, which this mixin
renders; they are not the generic clause's operator-key grammar.
"""

import re
from typing import Tuple, TYPE_CHECKING

from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError
from rhosocial.activerecord.backend.dialect.mixins.partition import PartitionMixin

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


class BigQueryPartitionMixin(PartitionMixin):
    """Format BigQuery's partition clause and declare its capability surface.

    Inherits core's ``PartitionMixin`` so the ``PartitionSupport`` protocol is
    complete: without that base the dialect raised ``AttributeError`` for
    ``supports_table_partitioning`` and ``partition_capability`` even though
    it already rendered ``PARTITION BY``.
    """

    def supports_table_partitioning(self) -> bool:
        """Whether table partitioning is supported at the database level.

        ``True``: the ``CREATE TABLE`` grammar carries
        ``[ PARTITION BY partition_expression ]``, and a partition is
        addressable by name through the table decorator
        ``table_name$partition_id`` (``table$YYYYMMDD`` is the daily form this
        backend's decorator node renders).  Both mechanisms are already
        modelled.

        ``partition_capability()`` therefore derives ``NATIVE``; BigQuery does
        not need the ``AUTOMATIC`` override, because partition DDL exists and
        partitions can be targeted.

        References (fetched 2026-11-25):
        https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language#create_table_statement
        https://cloud.google.com/bigquery/docs/partitioned-tables
        """
        return True

    def supports_partitioned_table_creation(self) -> bool:
        """Whether ``CREATE TABLE`` can create partitioned tables.

        ``True``: ``CREATE TABLE ... PARTITION BY partition_expression`` is
        the documented grammar, and the proprietary clause formatter
        (:class:`BigQueryTablePartitionByClause`) already renders it.

        Reference (fetched 2026-11-25):
        https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language#create_table_statement
        """
        return True

    def supports_partition_metadata_introspection(self) -> bool:
        """Whether partition metadata can be introspected.

        ``True``: ``INFORMATION_SCHEMA.PARTITIONS`` contains one row per
        partition, and this backend's introspector already reads it
        (``list_partitions`` / ``parse_partitions``).

        Reference (fetched 2026-11-25):
        https://cloud.google.com/bigquery/docs/information-schema-partitions
        """
        return True

    def supports_range_table_partitioning(self) -> bool:
        """Whether the generic ``PARTITION BY RANGE (...)`` form is supported.

        ``False``.  BigQuery *does* support integer range partitioning, but it
        is spelled ``PARTITION BY RANGE_BUCKET(column,
        GENERATE_ARRAY(start, end, step))`` and is rendered by
        :class:`BigQueryTablePartitionByClause`.  Core's generic RANGE clause
        spells ``PARTITION BY RANGE (<keys>)``, which GoogleSQL does not
        accept, so this gate must refuse it rather than render it.  The
        inherited ``format_partition_clause`` raises by name.

        References (fetched 2026-11-25):
        https://cloud.google.com/bigquery/docs/partitioned-tables
        https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language#create_table_statement
        """
        return False

    def supports_list_table_partitioning(self) -> bool:
        """Whether ``LIST`` table partitioning is supported.

        ``False``: the documented partitioning types are integer range,
        time-unit column, and ingestion-time.  There is no ``PARTITION BY
        LIST (...)`` production.  The inherited formatter refuses it by name.

        Reference (fetched 2026-11-25):
        https://cloud.google.com/bigquery/docs/partitioned-tables
        """
        return False

    def supports_hash_table_partitioning(self) -> bool:
        """Whether ``HASH`` table partitioning is supported.

        ``False``: there is no ``PARTITION BY HASH (...)`` production.  The
        inherited formatter refuses it by name.

        Reference (fetched 2026-11-25):
        https://cloud.google.com/bigquery/docs/partitioned-tables
        """
        return False

    def supports_subpartitioning(self) -> bool:
        """Whether table subpartitioning is supported.

        ``False``: ``CREATE TABLE`` carries at most one ``PARTITION BY``
        clause and the grammar has no subpartition definition; the documented
        partitioning types (integer range, time-unit column, ingestion-time)
        do not include a composite form.  The inherited
        ``format_subpartition_definition_expression`` refuses it by name.

        Reference (fetched 2026-11-25):
        https://cloud.google.com/bigquery/docs/partitioned-tables
        """
        return False

    def format_partition_clause(self, expr) -> Tuple[str, tuple]:
        """Refuse core's generic ``PARTITION BY`` clause shapes.

        BigQuery's clause takes a partition expression, not the generic
        ``PARTITION BY <method> (<keys>)`` form.  The inherited per-method
        refusals already name LIST and HASH; RANGE gets a BigQuery-specific
        message because the engine does have integer range partitioning
        spelled ``RANGE_BUCKET``, and a caller asking for the generic spelling
        needs to be pointed at that node.

        Raises:
            UnsupportedFeatureError: always on this dialect.
        """
        method = str(expr.method).upper()
        if method == "RANGE":
            raise UnsupportedFeatureError(
                self.name,
                "RANGE partitioning",
                "BigQuery's integer range partitioning is spelled PARTITION BY "
                "RANGE_BUCKET(column, GENERATE_ARRAY(start, end, step)) and is "
                "rendered by BigQueryTablePartitionByClause; the generic "
                "PARTITION BY RANGE (...) form is not GoogleSQL.",
            )
        return super().format_partition_clause(expr)

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
        # ``self`` rather than ``super()`` so the dialect's header guard
        # (OR REPLACE cannot accompany IF NOT EXISTS) runs before core's
        # renderer; ``self.format_create_table_statement`` resolves through
        # BigQueryCapabilityMixin and then to core's implementation.
        sql, params = self.format_create_table_statement(expr)
        clause = expr.partition_by
        if clause is not None:
            clause_sql, clause_params = clause.to_sql()
            if clause_sql:
                sql = sql + clause_sql
                params = tuple(params) + tuple(clause_params)
        return sql, params


__all__ = ["BigQueryPartitionMixin"]
