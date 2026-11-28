# src/rhosocial/activerecord/backend/impl/bigquery/expression/query_parts/partition.py
"""BigQuery's table-level ``PARTITION BY`` / ``CLUSTER BY`` clause.

GoogleSQL's ``CREATE TABLE`` grammar carries a table-level partitioning
expression and a clustering column list::

    CREATE TABLE [IF NOT EXISTS] table_name
        [PARTITION BY partition_expression]
        [CLUSTER BY clustering_column_list]
        [OPTIONS(table_option_list)]
        AS query_expression

Core has no node for this form: its ``PartitionClause`` family renders the
RANGE / LIST / HASH partitioning of other engines, which BigQuery does not
accept here. Under the absent-expression case this backend therefore owns a
proprietary node with its own name and its own ``kind()`` payload id; nothing
here is re-exported from core.
"""

from typing import TYPE_CHECKING

from rhosocial.activerecord.backend.expression.bases.bases import BaseExpression

if TYPE_CHECKING:  # pragma: no cover
    from ...dialect import BigQueryDialect


__all__ = [
    "BigQueryTablePartitionByClause",
]


class BigQueryTablePartitionByClause(BaseExpression):
    """Collect BigQuery's table-level partitioning and clustering parameters.

    Args:
        dialect: the BigQuery dialect instance; may be ``None`` and bound later.
        partition_expression: the GoogleSQL partitioning expression, kept as
            written by the caller.
        cluster_by: optional clustering column names.
    """

    def __init__(
        self,
        dialect: "BigQueryDialect",
        partition_expression=None,
        cluster_by=None,
    ):
        super().__init__(dialect)
        self.partition_expression = partition_expression
        self.cluster_by = cluster_by

    @property
    def format_method(self) -> str:
        """The dialect formatting method that renders this expression."""
        return "format_bigquery_table_partition_by_clause"
