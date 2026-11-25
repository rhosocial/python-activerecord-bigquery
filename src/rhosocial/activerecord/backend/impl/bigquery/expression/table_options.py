# src/rhosocial/activerecord/backend/impl/bigquery/expression/table_options.py
"""BigQuery ``ALTER TABLE`` option DDL expressions.

GoogleSQL syntax (BigQuery Standard SQL DDL reference)::

    ALTER TABLE [ IF EXISTS ] table_name SET OPTIONS ( table_set_options_list )
    ALTER TABLE [ IF EXISTS ] table_name UNSET OPTIONS ( option_name, ... )

The ``table_name`` is a core
:class:`~rhosocial.activerecord.backend.expression.objects.Table`: the dataset
rides in its ``schema_name`` slot and the project in its ``catalog_name`` slot.
One object, rendered by its own ``format_table_object``, is the only thing that
turns those slots into SQL, so a qualified table cannot reach one option
statement and miss the other.

Nothing here validates. Per the backend's node contract these constructors only
collect parameters; the dialect mixin owns the option-name catalogue, the value
shapes, the capability checks and every refusal. In particular no SQL string is
built here -- there is no place to hide an unescaped value or a bind parameter.

Options representation
----------------------
``options`` is a frozen sequence of ``(name, value)`` pairs. A name is a
:class:`~..table_option_catalog.BigQueryTableOption` member or its documented
string spelling. A value is a JSON scalar (``str``, ``bool``, ``int``, ``float``
or ``None`` for documented NULL clearing), plus exactly two documented nested
shapes: an INTERVAL pair ``(amount, qualifier)`` for ``max_staleness`` and a
sequence of ``(key, value)`` string pairs for ``labels`` / ``tags``. DDL cannot
carry bind markers, so no expression node or arbitrary nested container is
accepted as a value.

Evidence
--------
The ``SET OPTIONS`` production and the ``table_set_options_list`` vocabulary
are documented in the official DDL reference (fetched 2026-11-25):
https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language#alter_table_set_options_statement

The ``UNSET OPTIONS`` spelling is the one supplied with the migration task; the
reference page fetched above does not list that statement and documents
clearing instead as ``SET OPTIONS(option_name = NULL)``. The node is modelled
because the task specifies the server syntax, and the capability probe records
that evidence level explicitly rather than presenting it as verified.
"""
from typing import Any, TYPE_CHECKING

from rhosocial.activerecord.backend.expression.bases import BaseExpression
from rhosocial.activerecord.backend.expression.objects import Table

if TYPE_CHECKING:  # pragma: no cover
    from ..dialect import BigQueryDialect


__all__ = [
    "BigQueryAlterTableSetOptionsStatement",
    "BigQueryAlterTableUnsetOptionsStatement",
]


class BigQueryAlterTableSetOptionsStatement(BaseExpression):
    """``ALTER TABLE [IF EXISTS] table_name SET OPTIONS(options)``.

    Args:
        dialect: the BigQuery dialect instance.
        table: the table being reconfigured, carrying dataset and project.
        options: a sequence of ``(name, value)`` pairs; validated by the
            formatter, never here.
        if_exists: emit ``IF EXISTS``.
    """

    def __init__(
        self,
        dialect: "BigQueryDialect",
        table: Table,
        options: Any,
        if_exists: bool = False,
    ):
        super().__init__(dialect)
        self.table = table
        self.options = options
        self.if_exists = if_exists

    @property
    def format_method(self) -> str:
        """The dialect formatting method that renders this expression."""
        return "format_bigquery_alter_table_set_options_statement"


class BigQueryAlterTableUnsetOptionsStatement(BaseExpression):
    """``ALTER TABLE [IF EXISTS] table_name UNSET OPTIONS(option_names)``.

    Args:
        dialect: the BigQuery dialect instance.
        table: the table being reconfigured, carrying dataset and project.
        option_names: a sequence of documented option names; validated by the
            formatter, never here.
        if_exists: emit ``IF EXISTS``.
    """

    def __init__(
        self,
        dialect: "BigQueryDialect",
        table: Table,
        option_names: Any,
        if_exists: bool = False,
    ):
        super().__init__(dialect)
        self.table = table
        self.option_names = option_names
        self.if_exists = if_exists

    @property
    def format_method(self) -> str:
        """The dialect formatting method that renders this expression."""
        return "format_bigquery_alter_table_unset_options_statement"
