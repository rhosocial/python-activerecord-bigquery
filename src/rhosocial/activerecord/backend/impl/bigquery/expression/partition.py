# src/rhosocial/activerecord/backend/impl/bigquery/expression/partition.py
"""BigQuery table-level ``PARTITION BY`` / ``CLUSTER BY`` DDL clause.

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

from rhosocial.activerecord.backend.expression.bases import BaseExpression
from rhosocial.activerecord.backend.expression.objects import Table
from rhosocial.activerecord.backend.expression.statements.ddl_table import (
    CreateTableStatement,
)

if TYPE_CHECKING:  # pragma: no cover
    from ..dialect import BigQueryDialect


__all__ = [
    "BigQueryCreateTableStatement",
    "BigQueryTablePartitionByClause",
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


class BigQueryCreateTableStatement(CreateTableStatement):
    """Core ``CREATE TABLE`` extended with BigQuery's partition clause.

    Core's ``partition`` slot is typed to its own RANGE / LIST / HASH node, so a
    BigQuery partition clause cannot be passed through it. This derived
    statement carries the proprietary clause in its own ``partition_by`` slot
    and hands the rest of the statement to core's renderer unchanged.
    """

    def __init__(
        self,
        dialect,
        table,
        columns,
        indexes=None,
        table_constraints=None,
        temporary=False,
        if_not_exists=False,
        inherits=None,
        tablespace=None,
        storage_options=None,
        *,
        partition=None,
        table_options=None,
        partition_by=None,
    ):
        super().__init__(
            dialect,
            table,
            columns,
            indexes=indexes,
            table_constraints=table_constraints,
            temporary=temporary,
            if_not_exists=if_not_exists,
            inherits=inherits,
            tablespace=tablespace,
            storage_options=storage_options,
            partition=partition,
            table_options=table_options,
        )
        self.partition_by = partition_by

    @property
    def format_method(self) -> str:
        """The dialect formatting method that renders this expression."""
        return "format_bigquery_create_table_statement"
