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

from typing import Tuple, TYPE_CHECKING

from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError
from rhosocial.activerecord.backend.dialect.mixins.partition import PartitionMixin

from .._scan import Scanner

if TYPE_CHECKING:  # pragma: no cover
    from ..expression.partition import (
        BigQueryCreateTableStatement,
        BigQueryPartitionDecoratedTable,
        BigQueryTablePartitionByClause,
    )


#: The words that open a time-unit column partition expression: the bare
#: column functions and their ``_TRUNC`` forms.  A word outside this set is
#: refused before any parenthesis is read, which is how the expression this
#: replaces behaved: ``DATE_TIME(ts)`` was a misspelled word, not an
#: unsupported function.
_TRUNCATION_WORDS = frozenset(
    {
        "DATE",
        "DATE_TRUNC",
        "TIMESTAMP",
        "TIMESTAMP_TRUNC",
        "DATETIME",
        "DATETIME_TRUNC",
    }
)
#: The optional second argument of a truncation: the time granularity.
_GRANULARITY_WORDS = frozenset({"DAY", "WEEK", "MONTH", "QUARTER", "YEAR"})
_MAX_CLUSTER_COLUMNS = 4
_PARTITION_DECORATOR_SENTINELS = frozenset({"__NULL__", "__UNPARTITIONED__"})


def _scan_truncation(scanner: Scanner) -> bool:
    """Recognise ``DATE(col)`` / ``TIMESTAMP_TRUNC(col, DAY)`` and siblings."""
    word = scanner.take_word()
    if word is None or word.upper() not in _TRUNCATION_WORDS:
        return False
    if not scanner.take_char("("):
        return False
    if scanner.take_identifier() is None:
        return False
    if scanner.take_char(","):
        granularity = scanner.take_word()
        if granularity is None or granularity.upper() not in _GRANULARITY_WORDS:
            return False
    return scanner.take_char(")")


def _scan_range_bucket(scanner: Scanner) -> bool:
    """Recognise ``RANGE_BUCKET(col, GENERATE_ARRAY(start, end, step))``.

    The step is ``[1-9]<digits>``: positive and without a leading zero, so
    ``GENERATE_ARRAY(0, 100, 0)`` and ``... , 010)`` are refused.  Whether
    *start* and *end* are ordered is arithmetic, not syntax, and the server
    checks it.
    """
    word = scanner.take_word()
    if word is None or word.upper() != "RANGE_BUCKET":
        return False
    if not scanner.take_char("("):
        return False
    if scanner.take_identifier() is None:
        return False
    if not scanner.take_char(","):
        return False
    word = scanner.take_word()
    if word is None or word.upper() != "GENERATE_ARRAY":
        return False
    if not scanner.take_char("("):
        return False
    if scanner.take_signed_digits() is None:
        return False
    if not scanner.take_char(","):
        return False
    if scanner.take_signed_digits() is None:
        return False
    if not scanner.take_char(","):
        return False
    if scanner.take_digits(first_digits="123456789") is None:
        return False
    if not scanner.take_char(")"):
        return False
    return scanner.take_char(")")


def _is_partition_expression(spec: str) -> bool:
    """Whether *spec* is one of the two documented partition expressions."""
    scanner = Scanner(spec)
    if _scan_truncation(scanner) and scanner.at_end():
        return True
    scanner = Scanner(spec)
    if _scan_range_bucket(scanner) and scanner.at_end():
        return True
    return False


def _is_cluster_column(spec: str) -> bool:
    """Whether *spec* is one bare or backtick-quoted column name."""
    scanner = Scanner(spec)
    return scanner.take_identifier() is not None and scanner.at_end()


def _is_numeric_decorator(spec: str) -> bool:
    """Whether *spec* is a run of decimal digits, as ``\\d+`` asked."""
    scanner = Scanner(spec)
    return scanner.take_digits() is not None and scanner.at_end()


def _partition_decorator_spec(value) -> str:
    """Validate and normalise a ``$<decorator>`` segment.

    The documented forms are:

    * ``YYYYMMDDHH`` -- hourly (time-unit column or ingestion-time with hour
      granularity; not available to ``DATE`` partitioning columns),
    * ``YYYYMMDD`` -- daily,
    * ``YYYYMM`` -- monthly,
    * ``YYYY`` -- yearly,
    * an integer ``range_start`` -- integer-range partitioning only,
    * ``__NULL__`` -- the partition holding rows whose partition key is NULL,
    * ``__UNPARTITIONED__`` -- the partition holding rows outside an integer
      range.

    Apart from the two sentinels, every form is a non-negative decimal
    integer, so this function validates syntax only.  Whether a given numeral
    is a date decorator or an integer ``range_start`` depends on the target
    table's partitioning type, which a bare table reference does not know; the
    server performs that semantic check.

    Args:
        value: a non-negative ``int`` or the string form of one of the forms
            above.

    Returns:
        The decorator segment, without the leading ``$``.

    Raises:
        ValueError: for a Boolean, float, negative, blank, or otherwise
            unparseable value.  The offending value is named in the message.
    """
    if isinstance(value, bool):
        raise ValueError(
            "BigQuery partition decorator must be a non-negative integer or "
            f"a documented string form, got {value!r}"
        )
    if isinstance(value, int):
        if value < 0:
            raise ValueError(
                "BigQuery partition decorator range_start must be non-negative, "
                f"got {value}"
            )
        return str(value)
    if not isinstance(value, str):
        raise ValueError(
            "BigQuery partition decorator must be a non-negative integer or "
            f"a documented string form, got {value!r}"
        )
    spec = value.strip()
    if not spec:
        raise ValueError(
            "BigQuery partition decorator must not be blank, got "
            f"{value!r}"
        )
    if spec in _PARTITION_DECORATOR_SENTINELS:
        return spec
    if spec.startswith("-"):
        raise ValueError(
            "BigQuery partition decorator range_start must be non-negative, "
            f"got {spec!r}"
        )
    if _is_numeric_decorator(spec):
        return spec
    raise ValueError(
        f"unsupported BigQuery partition decorator {spec!r}; expected an "
        "hourly (YYYYMMDDHH), daily (YYYYMMDD), monthly (YYYYMM), yearly "
        "(YYYY) or integer range (range_start) decorator, or __NULL__ / "
        "__UNPARTITIONED__"
    )


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
        (``get_partition_state`` / ``parse_partition_state``, with
        ``parse_partitions`` keeping the finer per-partition shape).

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

    # ------------------------------------------------------------------
    # The action family: what a plan may ask to do to a partition
    # ------------------------------------------------------------------
    # A BigQuery partition is a property of the table, not an object a plan
    # creates, moves or drops: the engine derives it from the value in each
    # row's partition column. Every action below is therefore a definite
    # False -- the statement does not exist -- rather than a gap in the
    # implementation. A backend with no such action says so, so a caller can
    # enumerate the vocabulary and get one answer per name.

    def supports_add_partition(self) -> bool:
        """False: partitions appear as rows arrive; there is no ADD PARTITION."""
        return False

    def supports_drop_partition(self) -> bool:
        """False: no DROP PARTITION; rows are deleted or expired by policy."""
        return False

    def supports_truncate_partition(self) -> bool:
        """False: there is no TRUNCATE PARTITION statement."""
        return False

    def supports_attach_partition(self) -> bool:
        """False: a partition is not a standalone table that can be attached."""
        return False

    def supports_detach_partition(self) -> bool:
        """False: a partition is not a standalone table that can be detached."""
        return False

    def supports_split_partition(self) -> bool:
        """False: boundaries come from the partitioning expression; no SPLIT."""
        return False

    def supports_merge_partition(self) -> bool:
        """False: no MERGE PARTITION statement."""
        return False

    def supports_exchange_partition(self) -> bool:
        """False: no partition can be swapped with a standalone table."""
        return False

    def supports_reorganize_partition(self) -> bool:
        """False: MySQL's REORGANIZE PARTITION has no BigQuery counterpart."""
        return False

    def supports_coalesce_partition(self) -> bool:
        """False: the partition count is not a hash modulus that can be reduced."""
        return False

    def supports_move_partition(self) -> bool:
        """False: no MOVE PARTITION statement."""
        return False

    def supports_analyze_partition(self) -> bool:
        """False: no ANALYZE PARTITION; the service maintains statistics."""
        return False

    def supports_check_partition(self) -> bool:
        """False: no CHECK PARTITION statement."""
        return False

    def supports_optimize_partition(self) -> bool:
        """False: no OPTIMIZE PARTITION statement."""
        return False

    def supports_rebuild_partition(self) -> bool:
        """False: no REBUILD PARTITION statement."""
        return False

    def supports_repair_partition(self) -> bool:
        """False: no REPAIR PARTITION statement."""
        return False

    def supports_remove_partitioning(self) -> bool:
        """False: partitioning cannot be removed in place; the table is recreated."""
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
            if not _is_partition_expression(spec):
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
                if not isinstance(column, str) or not _is_cluster_column(
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

        GoogleSQL addresses a partition by appending ``$<decorator>``.  The
        verified forms are hourly ``YYYYMMDDHH``, daily ``YYYYMMDD``, monthly
        ``YYYYMM``, yearly ``YYYY``, an integer ``range_start``, and the
        sentinels ``__NULL__`` / ``__UNPARTITIONED__``.  The base name is
        rendered by this dialect's standard table formatter; the decorator is
        validated here.

        Only syntax is checked.  Whether a numeral is a date decorator or an
        integer ``range_start`` -- and therefore whether it is legal for the
        target table -- depends on that table's partitioning type, which this
        reference does not carry.  The server performs the semantic check.

        Args:
            expr: the decorated table reference.

        Returns:
            The decorated name and its parameters.

        Raises:
            ValueError: for a Boolean, float, negative, blank, or otherwise
                unparseable decorator.  The offending value is named.
        """
        base_sql, params = self.format_table_object(expr)
        spec = _partition_decorator_spec(expr.partition)
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
