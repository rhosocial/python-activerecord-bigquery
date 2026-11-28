# src/rhosocial/activerecord/backend/impl/bigquery/expression/statements/partition.py
"""BigQuery ``CREATE TABLE`` statement extended with a table partition clause.

Core's ``partition`` slot is typed to its own RANGE / LIST / HASH node, so a
BigQuery partition clause cannot be passed through it. This derived statement
carries the proprietary clause in its own ``partition_by`` slot and hands the
rest of the statement to core's renderer unchanged. The clause itself lives in
:mod:`..query_parts.partition`; the decorator-carrying table reference in
:mod:`..objects.table`.
"""

from rhosocial.activerecord.backend.expression.statements.ddl_table import (
    CreateTableStatement,
)


__all__ = [
    "BigQueryCreateTableStatement",
]


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
