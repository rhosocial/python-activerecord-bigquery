# src/rhosocial/activerecord/backend/impl/bigquery/expression/objects/table.py
"""A BigQuery table reference carrying a partition decorator."""

from typing import TYPE_CHECKING

from rhosocial.activerecord.backend.expression.objects import Table

if TYPE_CHECKING:  # pragma: no cover
    from ...dialect import BigQueryDialect


__all__ = [
    "BigQueryPartitionDecoratedTable",
]


class BigQueryPartitionDecoratedTable(Table):
    """A BigQuery table reference carrying a partition decorator.

    BigQuery addresses a single partition by appending ``$<decorator>`` to the
    table name.  The documented decorator forms are:

    * ``YYYYMMDDHH`` -- hourly; time-unit column partitioning on a
      ``TIMESTAMP`` / ``DATETIME`` column, or ingestion-time partitioning with
      hour granularity,
    * ``YYYYMMDD`` -- daily,
    * ``YYYYMM`` -- monthly,
    * ``YYYY`` -- yearly,
    * an integer ``range_start`` -- integer-range partitioning,
    * ``__NULL__`` -- the partition holding rows whose partition key is NULL,
    * ``__UNPARTITIONED__`` -- the partition holding rows outside an integer
      range.

    The node only collects the decorator: it does not know the target table's
    partitioning type, so it accepts any documented syntactic form and the
    formatter validates syntax.  The server performs the semantic check (for
    example, whether a ``$YYYYMM`` decorator is legal depends on the table
    being time-unit or ingestion-time partitioned rather than integer-range
    partitioned).

    The constructor accepts either the string form or a non-negative integer
    for ``range_start``; validation and normalisation happen in
    :meth:`BigQueryPartitionMixin.format_bigquery_partition_decorated_table`.
    """

    __slots__ = ("partition",)

    def __init__(
        self,
        dialect: "BigQueryDialect",
        name,
        partition,
        *,
        catalog_name=None,
        schema_name=None,
    ):
        super().__init__(
            dialect,
            name,
            catalog_name=catalog_name,
            schema_name=schema_name,
        )
        self.partition = partition

    @property
    def format_method(self) -> str:
        """The dialect formatting method that renders the decorated name."""
        return "format_bigquery_partition_decorated_table"
