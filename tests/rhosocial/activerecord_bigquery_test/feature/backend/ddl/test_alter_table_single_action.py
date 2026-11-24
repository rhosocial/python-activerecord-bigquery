# tests/rhosocial/activerecord_bigquery_test/feature/backend/ddl/test_alter_table_single_action.py
"""BigQuery ALTER TABLE is one action per statement (P0 architecture fix).

GoogleSQL's ALTER TABLE grammar lists its actions as alternatives; it has no
comma-separated action list. Core's generic renderer comma-joins actions when
``supports_multi_action_alter_table()`` is True (its default), so BigQuery must
declare False. These are pure construction tests -- no instance required.
"""

import pytest

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
    """Capability declaration and rendering for multi-action ALTER TABLE."""

    def test_supports_multi_action_alter_table_is_false(self, dialect):
        assert dialect.supports_multi_action_alter_table() is False

    def test_two_actions_are_not_comma_joined(self, dialect):
        expr = AlterTableStatement(
            dialect,
            table=Table(dialect, "t"),
            actions=[
                AddColumnAction(dialect, ColumnDefinition(dialect, "c1", TextType(dialect))),
                DropColumnAction(dialect, column_name="c2"),
            ],
        )
        sql, params = expr.to_sql()

        # Core's False branch emits one ALTER TABLE per action instead of a
        # single comma-joined statement GoogleSQL would reject.
        assert sql.count("ALTER TABLE") == 2
        assert "ADD COLUMN `c1` STRING, DROP COLUMN `c2`" not in sql
        assert "ALTER TABLE `t` ADD COLUMN `c1` STRING" in sql
        assert "ALTER TABLE `t` DROP COLUMN `c2`" in sql
        assert params == ()
