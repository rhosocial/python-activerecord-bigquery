# src/rhosocial/activerecord/backend/impl/bigquery/backend/qualified_names.py
"""Naming a relation, and the two statements the backend runs, through nodes.

Both the sync and the async backend run two internal queries of their own -- the
``MAX(pk) + 1`` probe and the emulator's ``COUNT(*)`` row-count probe -- and
both used to write the whole statement with an f-string:

    f"SELECT COALESCE(MAX(`{pk_column}`), 0) + 1 AS next_id FROM {qualified}"

That is SQL text assembled at the call site, which the org rules make the
formatter's business (§16.2): the backend may name a relation, but the SELECT,
its projection, its aggregate and its alias belong to expression nodes. The
consequence was not hypothetical -- the quoting rule was restated by hand, in
code that never saw the dialect's escaping, so a dataset or table name
containing a backtick produced SQL the server refuses.

So this module owns both statements as nodes. The projections and the relation
are built here, ``to_sql()`` renders them, and the caller executes the text and
parameters it gets back. It lives in a mixin rather than on one backend class
because the async backend runs the same two probes and there must be only one
answer.
"""

from typing import Any, Optional

from rhosocial.activerecord.backend.expression.core import Column, Literal, RowCountWildcard
from rhosocial.activerecord.backend.expression.functions.aggregate import (
    CountFunction,
    MaxFunction,
)
from rhosocial.activerecord.backend.expression.functions.string import CoalesceFunction
from rhosocial.activerecord.backend.expression.objects import Table
from rhosocial.activerecord.backend.expression.operators import ArithmeticOperation
from rhosocial.activerecord.backend.expression.query_parts import WhereClause
from rhosocial.activerecord.backend.expression.sources import NamedRelationRef
from rhosocial.activerecord.backend.expression.statements.dql import QueryStatement


class BigQueryQualifiedNameMixin:
    """Renders a relation named by ``options`` through the dialect."""

    def _relation_object(
        self, table: str, schema_name: Optional[str]
    ) -> Table:
        """Name a relation as an object, with its dataset in the schema slot.

        Args:
            table: The relation's own name.
            schema_name: The dataset, or ``None`` for the connection default.
                ``None`` is not a special case -- it is the default dataset --
                so there is one construction and not two.

        Returns:
            The ``Table`` object. Render it with ``to_sql()``.
        """
        return Table(self.dialect, table, schema_name=schema_name)

    def _render_relation(self, table: str, schema_name: Optional[str]) -> str:
        """Render a relation for a statement this backend assembles itself.

        Args:
            table: The relation's own name.
            schema_name: The dataset, or ``None`` for the connection default.

        Returns:
            The rendered ``dataset.table``, or ``table`` when no dataset was
            given and the connection default applies.
        """
        qualified_sql, _params = self._relation_object(table, schema_name).to_sql()
        return qualified_sql

    def _next_pk_expression(
        self, table: str, schema_name: Optional[str], pk_column: str
    ) -> QueryStatement:
        """``SELECT COALESCE(MAX(pk), 0) + 1 AS next_id FROM <relation>``.

        The expression behind :meth:`_next_pk_value`. The zero and the one are
        :class:`~...expression.core.Literal` values marked ``inline=True``: they
        are constants of the statement rather than caller data, and inlining
        keeps the rendered text what the f-string used to produce.
        """
        dialect = self.dialect
        highest = MaxFunction(dialect, Column(dialect, pk_column))
        next_value = ArithmeticOperation(
            dialect,
            "add",
            CoalesceFunction(dialect, highest, Literal(dialect, 0, inline=True)),
            Literal(dialect, 1, inline=True),
        )
        return QueryStatement(
            dialect,
            select=[next_value.as_("next_id")],
            from_=NamedRelationRef(dialect, self._relation_object(table, schema_name)),
        )

    def _count_expression(
        self, table: str, schema_name: Optional[str], where: Any
    ) -> QueryStatement:
        """``SELECT COUNT(*) AS n FROM <relation> WHERE <condition>``.

        The expression behind :meth:`_count_matching`. ``where`` is the caller's
        ``WhereClause`` as the update/delete options carry it, so its condition
        is rendered by the clause rather than by a prefix strip: the previous
        version read the rendered text back and cut ``"WHERE "`` off the front,
        which is a formatter's job being done by string surgery.
        """
        dialect = self.dialect
        return QueryStatement(
            dialect,
            select=[CountFunction(dialect, RowCountWildcard(dialect)).as_("n")],
            from_=NamedRelationRef(dialect, self._relation_object(table, schema_name)),
            where=where if isinstance(where, WhereClause) else WhereClause(dialect, where),
        )


__all__ = ["BigQueryQualifiedNameMixin"]
