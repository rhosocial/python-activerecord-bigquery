# src/rhosocial/activerecord/backend/impl/bigquery/protocols/partition.py
"""BigQuery table-partition protocol.

GoogleSQL's table-level ``PARTITION BY`` / ``CLUSTER BY`` has no counterpart in
core, so the feature group is owned and named by this backend. The protocol
declares the single formatter for the proprietary clause; the matching mixin
lives in ``impl.bigquery.mixins.partition``.
"""

from typing import Any, Protocol, runtime_checkable, Tuple


@runtime_checkable
class BigQueryPartitionSupport(Protocol):
    """Back-named protocol for BigQuery's proprietary partition clause."""

    def format_bigquery_table_partition_by_clause(self, expr: Any) -> Tuple[str, tuple]:
        """Format the table-level ``PARTITION BY`` / ``CLUSTER BY`` clause."""
        ...

    def format_bigquery_partition_decorated_table(
        self, expr: Any
    ) -> Tuple[str, tuple]:
        """Render a table name with a ``$<decorator>`` partition suffix."""
        ...


__all__ = ["BigQueryPartitionSupport"]
