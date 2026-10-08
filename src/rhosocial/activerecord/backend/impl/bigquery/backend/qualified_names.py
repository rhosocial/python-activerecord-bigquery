# src/rhosocial/activerecord/backend/impl/bigquery/backend/qualified_names.py
"""Naming a relation for the backend's own SQL.

Both the sync and the async backend run two internal queries of their own -- the
``MAX(pk) + 1`` probe and the emulator's ``COUNT(*)`` row-count probe -- and
both used to write the relation into the SQL with an f-string:

    f"`{schema_name}`.`{table}`" if schema_name else f"`{table}`"

That is BigQuery's quoting rule restated by hand, in code that never sees the
dialect's own escaping, so a dataset or table name containing a backtick
produced SQL the server refuses. It is also a second opinion about which
identifiers need quoting, which is the kind of duplication this refactor
removes: naming the relation as an object and handing it to the dialect's own
``format_table_object`` leaves one quoting rule for the whole backend.

It lives in a mixin rather than on one backend class because the async backend
has the same two probes and there must be only one answer.
"""

from typing import Optional

from rhosocial.activerecord.backend.expression.objects import Table


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


__all__ = ["BigQueryQualifiedNameMixin"]
