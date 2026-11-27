# tests/rhosocial/activerecord_bigquery_test/feature/backend/ddl/test_alter_table_single_action.py
"""BigQuery ALTER TABLE is one action per statement.

GoogleSQL's ALTER TABLE grammar lists its actions as alternatives; it has no
comma-separated action list. The framework reaches the same shape everywhere:
one expression renders one action, and a statement carrying two fails fast with
``UnsupportedFeatureError`` instead of comma-joining them. Comma-joining would
hide the second action from the caller's plan -- its own phase, permission and
destructive check -- and semicolon-joining would emit two statements from one
expression. BigQuery's grammar and the framework rule agree here, but the test
asserts the rule, not only the spelling. These are pure construction tests --
no instance required.
"""

import pytest

from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError
from rhosocial.activerecord.backend.expression import AlterTableStatement
from rhosocial.activerecord.backend.expression.objects import Table
from rhosocial.activerecord.backend.expression.statements import ColumnDefinition
from rhosocial.activerecord.backend.expression.statements.ddl_alter import (
    AddColumnAction,
    DropColumnAction,
)
from rhosocial.activerecord.backend.expression.types import TextType
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect


@pytest.fixture
def dialect():
    return BigQueryDialect()


class TestBigQueryAlterTableSingleAction:
    """Fail-fast rendering for a multi-action ALTER TABLE."""

    def test_two_actions_fail_fast(self, dialect):
        expr = AlterTableStatement(
            dialect,
            table=Table(dialect, "t"),
            actions=[
                AddColumnAction(dialect, ColumnDefinition(dialect, "c1", TextType(dialect))),
                DropColumnAction(dialect, column_name="c2"),
            ],
        )

        # Core refuses to emit two statements from one expression: the caller
        # (migration planner) must split into one AlterTableStatement per action.
        with pytest.raises(UnsupportedFeatureError, match="multiple actions"):
            expr.to_sql()

    def test_single_action_renders_one_alter_table(self, dialect):
        expr = AlterTableStatement(
            dialect,
            table=Table(dialect, "t"),
            actions=[AddColumnAction(dialect, ColumnDefinition(dialect, "c1", TextType(dialect)))],
        )
        sql, params = expr.to_sql()

        assert sql.count("ALTER TABLE") == 1
        assert sql == "ALTER TABLE `t` ADD COLUMN `c1` STRING"
        assert params == ()
