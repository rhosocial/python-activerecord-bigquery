# tests/rhosocial/activerecord_bigquery_test/feature/backend/ddl/test_alter_table_single_action.py
"""BigQuery ALTER TABLE is one action per statement (P0 architecture fix).

GoogleSQL's ALTER TABLE grammar lists its actions as alternatives; it has no
comma-separated action list. Core's generic renderer comma-joins actions when
``supports_multi_action_alter_table()`` is True (its default), so BigQuery must
declare False. On a dialect declaring False, core now fails fast with
``UnsupportedFeatureError`` instead of semicolon-joining actions into one
unexecutable string: one expression must render as exactly one SQL statement.
Single-action statements still render normally. These are pure construction
tests -- no instance required.
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
    """Capability declaration and fail-fast rendering for multi-action ALTER TABLE."""

    def test_supports_multi_action_alter_table_is_false(self, dialect):
        assert dialect.supports_multi_action_alter_table() is False

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
