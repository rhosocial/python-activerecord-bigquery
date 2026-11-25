# src/rhosocial/activerecord/backend/impl/bigquery/mixins/change_suggestions.py
"""BigQuery's answers for the four migration change points.

Every answer here is read off the official GoogleSQL DDL reference and the
capability probes this backend already declares. No expression class or SQL
string is invented: an actionable answer reuses existing core statements and
actions (or this backend's own partition nodes), and an unsupported answer is
the explicit ``False`` tri-state. The reason for each ``False`` is recorded
next to the answer and pinned by the tests; no constructor is handed SQL text
assembled by this module.

Source of the grammar quoted below (transcribed and verified by the existing
capability modules and tests, not re-measured here):
    https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language

* Column reorder: ``ALTER TABLE`` has ADD COLUMN / DROP COLUMN / ALTER COLUMN /
  RENAME COLUMN / SET OPTIONS actions, and ``column_schema`` has no position
  marker (no FIRST / AFTER / BEFORE). Column order is fixed at CREATE time and
  cannot be changed by a statement this dialect can render, so reorder is
  explicitly unsupported.
* Table constraint change: the only constraint lifecycle statements are
  ``ALTER TABLE ... ADD [CONSTRAINT [IF NOT EXISTS] name] FOREIGN KEY ... NOT
  ENFORCED`` and ``ALTER TABLE ... DROP CONSTRAINT [IF EXISTS] name``. Only a
  table-level foreign key is nameable, so only a named foreign key can be
  added or dropped. The existing ``AlterTableStatement``,
  ``AddTableConstraintAction`` and ``DropTableConstraintAction`` nodes render
  exactly those two statements; every other kind is unsupported.
* Table index change: the reference has CREATE SEARCH INDEX / DROP SEARCH INDEX
  / ALTER SEARCH INDEX (and preview AI INDEX), but no plain CREATE INDEX or
  DROP INDEX. Those families are unmodelled by the shared index expressions,
  and the dialect's index probes and formatters refuse plain index DDL by
  name, so an index change is explicitly unsupported.
* Partition scheme change: partitioning is declared at CREATE time through
  ``PARTITION BY`` / ``CLUSTER BY`` and partitions are addressed by decorators;
  there is no statement that alters a table's partitioning scheme. A real
  chain exists only when the point carries a complete rebuild statement built
  from this dialect's existing nodes: drop the old table, then create the new
  one with its new partition clause. A bare partition clause cannot recreate a
  table, so it is not enough to make the point actionable.
"""

from typing import Any

from rhosocial.activerecord.backend.expression import AlterTableStatement
from rhosocial.activerecord.backend.expression.bases import BaseExpression
from rhosocial.activerecord.backend.expression.objects import Table
from rhosocial.activerecord.backend.expression.statements import DropTableStatement
from rhosocial.activerecord.backend.expression.statements.ddl_alter import (
    AddTableConstraintAction,
    DropTableConstraintAction,
)
from rhosocial.activerecord.backend.expression.statements.ddl_table import (
    CreateTableStatement,
    TableConstraint,
    TableForeignKeyConstraint,
)
from rhosocial.activerecord.backend.suggestion.definitions import (
    ColumnReorderSuggestion,
    PartitionSchemeChangeSuggestion,
    TableConstraintChangeSuggestion,
    TableIndexChangeSuggestion,
)

from ..expression.partition import (
    BigQueryCreateTableStatement,
    BigQueryTablePartitionByClause,
)


__all__ = [
    "BigQueryColumnReorderSuggestionMixin",
    "BigQueryTableConstraintChangeSuggestionMixin",
    "BigQueryTableIndexChangeSuggestionMixin",
    "BigQueryPartitionSchemeChangeSuggestionMixin",
]


def _signature(value: Any) -> Any:
    """Comparable, SQL-free form of a frozen declaration value.

    ``BaseExpression`` has no value equality, so two separately constructed
    constraints have to be compared through their declared parameters. Nested
    expressions are expanded the same way, which keeps the comparison tied to
    the nodes' own data rather than to their identity or to rendered SQL.
    """
    if isinstance(value, BaseExpression):
        items = tuple(sorted((str(k), _signature(v)) for k, v in value.get_params().items()))
        return (type(value).__name__, items)
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(sorted((_signature(item) for item in value), key=repr))
    if isinstance(value, dict):
        return tuple(sorted((str(k), _signature(v)) for k, v in value.items()))
    return value


class BigQueryColumnReorderSuggestionMixin:
    """Column order is fixed at CREATE time; GoogleSQL has no position clause."""

    def suggest_column_reorder(
        self, point: ColumnReorderSuggestion
    ) -> ColumnReorderSuggestion:
        """Refuse to reorder: neither a statement nor a declaration node exists.

        ``ColumnReorderSuggestion`` carries only names and orders. Rebuilding a
        table to change its column order would need the full column
        declarations, which the point does not carry, and a rebuilt table is
        not a reorder of the existing one anyway. ``False`` is therefore the
        honest answer without inventing a node or SQL.
        """
        return ColumnReorderSuggestion(operations=False)


class BigQueryTableConstraintChangeSuggestionMixin:
    """Named foreign keys can be added and dropped; nothing else can."""

    def suggest_table_constraint_change(
        self, point: TableConstraintChangeSuggestion
    ) -> TableConstraintChangeSuggestion:
        """Return one-action ``ALTER TABLE`` statements for changed named FKs.

        The chain is available only when the point carries real
        ``TableConstraint`` instances with a ``TableForeignKeyConstraint``
        branch, a name, and ``not_enforced=True`` -- the shape the ADD
        production requires. The planner's frozen ``("params", ...)``
        projections are deliberately not decoded: doing so would mean
        reconstructing expression nodes from a snapshot, which is outside this
        contract. Changed names are dropped before new ones are added, and
        every statement carries exactly one action because GoogleSQL permits
        one action per ``ALTER TABLE``.
        """
        old = tuple(point.old_constraints or ())
        new = tuple(point.new_constraints or ())
        if not old and not new:
            return TableConstraintChangeSuggestion(operations=None)

        candidates = old + new
        if any(not isinstance(item, TableConstraint) for item in candidates):
            return TableConstraintChangeSuggestion(operations=False)
        if any(not isinstance(item.branch, TableForeignKeyConstraint) for item in candidates):
            return TableConstraintChangeSuggestion(operations=False)
        if any(not isinstance(item.name, str) or not item.name.strip() for item in candidates):
            return TableConstraintChangeSuggestion(operations=False)
        # NOT ENFORCED is inside the ADD production. Adding a constraint
        # without that marker would render SQL the grammar does not accept.
        if any(item.enforced or not item.not_enforced for item in new):
            return TableConstraintChangeSuggestion(operations=False)

        table_name = point.table_name
        if not isinstance(table_name, str) or not table_name.strip():
            return TableConstraintChangeSuggestion(operations=False)
        table = Table(self, table_name)

        old_by_name = {item.name: item for item in old}
        new_by_name = {item.name: item for item in new}
        chain = []
        for constraint in old:
            kept = new_by_name.get(constraint.name)
            if kept is None or _signature(kept) != _signature(constraint):
                action = DropTableConstraintAction(self, constraint.name, if_exists=True)
                chain.append(AlterTableStatement(self, table, [action]))
        for constraint in new:
            previous = old_by_name.get(constraint.name)
            if previous is None or _signature(previous) != _signature(constraint):
                action = AddTableConstraintAction(self, constraint)
                chain.append(AlterTableStatement(self, table, [action]))
        operations = tuple(chain)
        if not operations:
            return TableConstraintChangeSuggestion(operations=None)
        return TableConstraintChangeSuggestion(operations=operations)


class BigQueryTableIndexChangeSuggestionMixin:
    """BigQuery has no plain index DDL the shared nodes could express."""

    def suggest_table_index_change(
        self, point: TableIndexChangeSuggestion
    ) -> TableIndexChangeSuggestion:
        """Refuse an index change: only SEARCH / AI INDEX exist, and unmodelled.

        The frozen point names indexes, not search-index declarations, so even
        the family BigQuery does have could not be constructed from it without
        inventing parameters and SQL.
        """
        return TableIndexChangeSuggestion(operations=False)


class BigQueryPartitionSchemeChangeSuggestionMixin:
    """A scheme change is a table rebuild, never an in-place ALTER."""

    def suggest_partition_scheme_change(
        self, point: PartitionSchemeChangeSuggestion
    ) -> PartitionSchemeChangeSuggestion:
        """Return a drop/recreate chain when the point carries the new table.

        The new projection must be a complete ``CreateTableStatement`` (this
        dialect's partition-aware subclass included) whose target is the point's
        table. Its partition clause must be this backend's own
        ``BigQueryTablePartitionByClause``; a core RANGE / LIST / HASH clause
        has no GoogleSQL spelling here. The old declaration needs no rendering
        because dropping the table removes it. A bare clause, a frozen
        projection, or a statement for another table cannot be turned into a
        chain without inventing a declaration, so those answer ``False``.
        """
        table_name = point.table_name
        if not isinstance(table_name, str) or not table_name.strip():
            return PartitionSchemeChangeSuggestion(operations=False)
        new = point.new_partition
        if not isinstance(new, CreateTableStatement):
            return PartitionSchemeChangeSuggestion(operations=False)
        # Core's generic partition clause has no GoogleSQL spelling on this
        # dialect; the BigQuery subclass puts its clause in ``partition_by``.
        if getattr(new, "partition", None) is not None:
            return PartitionSchemeChangeSuggestion(operations=False)
        if isinstance(new, BigQueryCreateTableStatement):
            clause = new.partition_by
            if clause is not None and not isinstance(clause, BigQueryTablePartitionByClause):
                return PartitionSchemeChangeSuggestion(operations=False)
        target = getattr(new, "table", None)
        if not isinstance(target, Table) or target.name != table_name:
            return PartitionSchemeChangeSuggestion(operations=False)

        old_table = Table(
            self,
            target.name,
            catalog_name=target.catalog_name,
            schema_name=target.schema_name,
        )
        operations = (
            DropTableStatement(self, old_table),
            new,
        )
        return PartitionSchemeChangeSuggestion(operations=operations)
