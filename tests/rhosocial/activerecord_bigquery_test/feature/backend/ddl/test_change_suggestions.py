# tests/rhosocial/activerecord_bigquery_test/feature/backend/ddl/test_change_suggestions.py
"""BigQuery's four migration change-point suggestions.

The three actionable answers reuse existing nodes and are pinned here by exact
SQL. The other answers are explicit ``False`` states, each with the documented
reason recorded in ``mixins/change_suggestions.py`` and in this module's
docstrings; the capability probes those reasons rest on are asserted alongside
them. Evidence source for all of them:

    https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language

The same points are fed through core's ``resolve_point`` consumer so the
tri-state is checked as a caller sees it, not only as a return value.
"""

import inspect
import re

import pytest

from rhosocial.activerecord.backend.expression import AlterTableStatement, Column
from rhosocial.activerecord.backend.expression.objects import Table
from rhosocial.activerecord.backend.expression.statements.ddl_partition import (
    PartitionByRangeClause,
)
from rhosocial.activerecord.backend.expression.statements.ddl_table import (
    ColumnDefinition,
    CreateTableStatement,
    TableConstraint,
    TableForeignKeyConstraint,
    TablePrimaryKeyConstraint,
)
from rhosocial.activerecord.backend.expression.types import IntegerType
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect
from rhosocial.activerecord.backend.impl.bigquery.expression import (
    BigQueryCreateTableStatement,
    BigQueryTablePartitionByClause,
)
from rhosocial.activerecord.backend.impl.bigquery.mixins import change_suggestions as module
from rhosocial.activerecord.backend.suggestion.definitions import (
    ColumnReorderSuggestion,
    PartitionSchemeChangeSuggestion,
    TableConstraintChangeSuggestion,
    TableIndexChangeSuggestion,
)
from rhosocial.activerecord.backend.suggestion.protocols import (
    ColumnReorderSuggestionSupport,
    PartitionSchemeChangeSuggestionSupport,
    TableConstraintChangeSuggestionSupport,
    TableIndexChangeSuggestionSupport,
)
from rhosocial.activerecord.migration.schema_change import resolve_point


PROTOCOL_METHODS = (
    (ColumnReorderSuggestionSupport, "suggest_column_reorder"),
    (TableConstraintChangeSuggestionSupport, "suggest_table_constraint_change"),
    (TableIndexChangeSuggestionSupport, "suggest_table_index_change"),
    (PartitionSchemeChangeSuggestionSupport, "suggest_partition_scheme_change"),
)


@pytest.fixture
def dialect():
    return BigQueryDialect()


def _fk(dialect, name="fk_a", local=("a",), remote=("id",), table="p", not_enforced=True):
    return TableConstraint(
        dialect,
        branch=TableForeignKeyConstraint(
            dialect, list(local), (Table(dialect, table), list(remote))
        ),
        name=name,
        not_enforced=not_enforced,
    )


def _sql(answer):
    return [operation.to_sql()[0] for operation in answer.operations]


def _create(dialect, *, table="events", partition_by=None, partition=None, schema_name=None):
    return BigQueryCreateTableStatement(
        dialect,
        Table(dialect, table, schema_name=schema_name),
        [ColumnDefinition(dialect, "id", IntegerType(dialect))],
        partition=partition,
        partition_by=partition_by,
    )


_DESTRUCTIVE_DROP_CLASSES = {"DropTableStatement", "DropSchemaStatement"}


def _operation_chain(answer):
    """The expression chain an answer carries; a non-actionable answer has none."""
    operations = answer.operations
    return operations if isinstance(operations, (tuple, list)) else ()


def _assert_no_destructive_drop(answer):
    """Pin the safety rule: no returned expression drops a table or a schema.

    Each expression is checked twice -- by its class name and by its rendered
    SQL -- so a rebuild smuggled in through either route is caught.
    """
    for operation in _operation_chain(answer):
        assert type(operation).__name__ not in _DESTRUCTIVE_DROP_CLASSES
        sql = operation.to_sql()[0]
        for statement in sql.split(";"):
            assert not re.match(r"^\s*DROP\s+(TABLE|SCHEMA)\b", statement, re.IGNORECASE), sql


_SCHEME_NEW_PARTITIONS = (
    lambda d: BigQueryTablePartitionByClause(d, "DATE(ts)"),
    lambda d: _create(
        d, partition_by=BigQueryTablePartitionByClause(d, "DATE(created_at)", ["id"])
    ),
    lambda d: CreateTableStatement(
        d, Table(d, "events"), [ColumnDefinition(d, "id", IntegerType(d))]
    ),
    lambda d: _create(
        d,
        schema_name="app",
        partition_by=BigQueryTablePartitionByClause(d, "DATE(created_at)"),
    ),
    lambda d: _create(d, table="other"),
    lambda d: _create(d, partition=PartitionByRangeClause(d, [Column(d, "ts")])),
    lambda d: ("params", (("partition_expression", "DATE(ts)"),)),
    lambda d: "DATE(ts)",
    lambda d: None,
)
_SCHEME_NEW_PARTITION_IDS = (
    "bigquery-clause",
    "full-rebuild-add-partition",
    "full-rebuild-remove-partition",
    "qualified-full-rebuild",
    "other-table",
    "core-range-clause",
    "frozen",
    "string",
    "missing",
)


class TestProtocolRegistration:
    @pytest.mark.parametrize("protocol,method", PROTOCOL_METHODS)
    def test_dialect_advertises_every_protocol(self, dialect, protocol, method):
        assert isinstance(dialect, protocol)
        assert callable(getattr(dialect, method))

    @pytest.mark.parametrize("protocol,method", PROTOCOL_METHODS)
    def test_answers_are_declared_in_this_backend(self, dialect, protocol, method):
        declaring = next(cls for cls in type(dialect).__mro__ if method in cls.__dict__)
        assert declaring.__module__.startswith(
            "rhosocial.activerecord.backend.impl.bigquery"
        )

    def test_module_records_the_evidence_for_each_answer(self):
        doc = inspect.getdoc(module) or ""
        for phrase in (
            "no position\n  marker",
            "Only a\n  table-level foreign key is nameable",
            "CREATE SEARCH INDEX",
            "there is no statement that alters a table's partitioning scheme",
        ):
            assert phrase in doc, f"the module must record the evidence: {phrase!r}"


class TestColumnReorder:
    def test_reorder_is_explicitly_unsupported(self, dialect):
        """GoogleSQL has no FIRST / AFTER / BEFORE clause and no reorder node."""
        point = ColumnReorderSuggestion(
            table_name="t",
            old_order=("a", "b"),
            new_order=("b", "a"),
            reordered_columns=("a", "b"),
        )
        answer = dialect.suggest_column_reorder(point)
        assert isinstance(answer, ColumnReorderSuggestion)
        assert answer.label == "column_reorder"
        assert answer.operations is False
        assert answer.state == "unaddressable"
        assert resolve_point(point, dialect).state == "unsupported"


class TestConstraintChange:
    def test_adds_a_named_foreign_key(self, dialect):
        """Existing nodes render the documented ADD FOREIGN KEY production."""
        point = TableConstraintChangeSuggestion(table_name="t", new_constraints=(_fk(dialect),))
        answer = dialect.suggest_table_constraint_change(point)
        assert answer.state == "actions"
        assert _sql(answer) == [
            "ALTER TABLE `t` ADD CONSTRAINT `fk_a` FOREIGN KEY (`a`) "
            "REFERENCES `p`(`id`) NOT ENFORCED"
        ]
        assert all(isinstance(op, AlterTableStatement) for op in answer.operations)
        assert all(len(op.actions) == 1 for op in answer.operations)
        assert resolve_point(point, dialect).state == "actions"

    def test_drops_a_named_foreign_key(self, dialect):
        """DROP CONSTRAINT IF EXISTS is the documented mirror of ADD."""
        point = TableConstraintChangeSuggestion(
            table_name="t", old_constraints=(_fk(dialect),)
        )
        answer = dialect.suggest_table_constraint_change(point)
        assert _sql(answer) == ["ALTER TABLE `t` DROP CONSTRAINT IF EXISTS `fk_a`"]
        assert all(len(op.actions) == 1 for op in answer.operations)

    def test_redefinition_drops_before_adding(self, dialect):
        """There is no ALTER CONSTRAINT, so a changed FK is drop then add."""
        point = TableConstraintChangeSuggestion(
            table_name="t",
            old_constraints=(_fk(dialect, local=("a",)),),
            new_constraints=(_fk(dialect, local=("b",)),),
        )
        answer = dialect.suggest_table_constraint_change(point)
        assert _sql(answer) == [
            "ALTER TABLE `t` DROP CONSTRAINT IF EXISTS `fk_a`",
            "ALTER TABLE `t` ADD CONSTRAINT `fk_a` FOREIGN KEY (`b`) "
            "REFERENCES `p`(`id`) NOT ENFORCED",
        ]
        assert all(len(op.actions) == 1 for op in answer.operations)

    def test_unchanged_foreign_key_is_no_answer(self, dialect):
        """Equal declarations need no statement: the third tri-state value."""
        point = TableConstraintChangeSuggestion(
            table_name="t",
            old_constraints=(_fk(dialect),),
            new_constraints=(_fk(dialect),),
        )
        answer = dialect.suggest_table_constraint_change(point)
        assert answer.operations is None
        assert answer.state == "absent"

    def test_frozen_projections_are_unsupported(self, dialect):
        """The planner's frozen shapes are not decoded into expression nodes."""
        point = TableConstraintChangeSuggestion(
            table_name="t",
            old_constraints=(("params", (("name", "fk_a"),)),),
        )
        answer = dialect.suggest_table_constraint_change(point)
        assert answer.operations is False
        assert resolve_point(point, dialect).state == "unsupported"

    def test_non_foreign_key_kinds_are_unsupported(self, dialect):
        """ALTER can add and drop a foreign key only, never a primary key."""
        point = TableConstraintChangeSuggestion(
            table_name="t",
            new_constraints=(
                TableConstraint(dialect, branch=TablePrimaryKeyConstraint(dialect, ["a"])),
            ),
        )
        answer = dialect.suggest_table_constraint_change(point)
        assert answer.operations is False

    def test_missing_not_enforced_is_unsupported(self, dialect):
        """The mandatory marker cannot be supplied by inventing a new node."""
        point = TableConstraintChangeSuggestion(
            table_name="t", new_constraints=(_fk(dialect, not_enforced=False),)
        )
        answer = dialect.suggest_table_constraint_change(point)
        assert answer.operations is False

    def test_grammar_facts_are_the_pinned_probes(self, dialect):
        """Evidence for the supported half, already verified in this package."""
        assert dialect.supports_add_constraint() is True
        assert dialect.supports_table_add_foreign_key_constraint() is True
        assert dialect.supports_table_add_primary_key_constraint() is False
        assert dialect.supports_drop_constraint() is True
        assert dialect.supports_drop_constraint_if_exists() is True
        assert dialect.supports_table_rename_constraint() is False


class TestIndexChange:
    def test_index_change_is_explicitly_unsupported(self, dialect):
        """Only SEARCH / AI INDEX exist, and no node models them."""
        point = TableIndexChangeSuggestion(
            table_name="t", new_indexes=(("params", (("name", "i"),)),)
        )
        answer = dialect.suggest_table_index_change(point)
        assert isinstance(answer, TableIndexChangeSuggestion)
        assert answer.operations is False
        assert answer.state == "unaddressable"
        assert resolve_point(point, dialect).state == "unsupported"

    def test_the_refusal_rests_on_the_verified_index_probes(self, dialect):
        assert dialect.supports_create_index() is False
        assert dialect.supports_drop_index() is False
        assert dialect.supports_alter_table_index_actions() is False
        for formatter in (
            "format_create_search_index_statement",
            "format_drop_search_index_statement",
        ):
            assert not hasattr(dialect, formatter)


class TestPartitionSchemeChange:
    """Safety: no answer may offer a destructive table rebuild.

    ``resolve_suggestions`` appends returned expressions verbatim to the
    executable statement list, so a ``DROP TABLE`` + ``CREATE TABLE`` chain
    would delete every row when applied. The refusal is therefore total, not
    conditional on the shape of the point.
    """

    @pytest.mark.parametrize(
        "factory", _SCHEME_NEW_PARTITIONS, ids=_SCHEME_NEW_PARTITION_IDS
    )
    def test_every_scheme_change_point_is_explicitly_unaddressable(self, dialect, factory):
        """Each answer is ``False`` / ``unaddressable``, even a full rebuild."""
        point = PartitionSchemeChangeSuggestion(
            table_name="events",
            old_partition=BigQueryTablePartitionByClause(dialect, "DATE(ts)"),
            new_partition=factory(dialect),
        )
        answer = dialect.suggest_partition_scheme_change(point)
        assert isinstance(answer, PartitionSchemeChangeSuggestion)
        assert answer.operations is False
        assert answer.state == "unaddressable"
        assert resolve_point(point, dialect).state == "unsupported"

    @pytest.mark.parametrize(
        "factory", _SCHEME_NEW_PARTITIONS, ids=_SCHEME_NEW_PARTITION_IDS
    )
    def test_no_answer_contains_a_destructive_drop(self, dialect, factory):
        """No returned expression chain drops a TABLE or SCHEMA, by name or SQL."""
        point = PartitionSchemeChangeSuggestion(
            table_name="events", new_partition=factory(dialect)
        )
        answer = dialect.suggest_partition_scheme_change(point)
        assert answer.operations is False
        assert _operation_chain(answer) == ()
        _assert_no_destructive_drop(answer)

    def test_complete_rebuild_projection_is_refused_without_a_drop(self, dialect):
        """The shape that used to render DROP + CREATE now refuses outright."""
        new = _create(
            dialect,
            partition_by=BigQueryTablePartitionByClause(dialect, "DATE(created_at)", ["id"]),
        )
        point = PartitionSchemeChangeSuggestion(
            table_name="events",
            old_partition=BigQueryTablePartitionByClause(dialect, "DATE(ts)"),
            new_partition=new,
        )
        answer = dialect.suggest_partition_scheme_change(point)
        assert answer.operations is False
        assert answer.state == "unaddressable"
        assert _operation_chain(answer) == ()
        _assert_no_destructive_drop(answer)

    def test_docstring_states_the_safety_rationale(self, dialect):
        """The refusal documents why the destructive rebuild is not offered."""
        doc = inspect.getdoc(dialect.suggest_partition_scheme_change) or ""
        for phrase in (
            "BigQuery has no in-place ALTER of the partition scheme",
            "``DROP TABLE`` + ``CREATE TABLE``",
            "destructive",
            "data-preserving rebuild must be a separate",
            "explicitly authorized migration plan",
        ):
            assert phrase in doc, f"the refusal must be documented: {phrase!r}"
