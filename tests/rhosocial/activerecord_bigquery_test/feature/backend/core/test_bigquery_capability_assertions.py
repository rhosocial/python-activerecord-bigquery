# tests/rhosocial/activerecord_bigquery_test/feature/backend/core/test_bigquery_capability_assertions.py
"""Explicit BigQuery DDL capability + rendering assertions.

BigQuery relies on the generic core formatters for CREATE TABLE, views,
TRUNCATE and DROP TABLE; these tests pin the capability bits and verify the
generic renderers produce BigQuery-compatible SQL.
"""

import pytest

from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError
from rhosocial.activerecord.backend.expression import (
    AlterTableStatement,
    ArithmeticOperation,
    Column,
    CreateTableStatement,
    CreateViewStatement,
    QueryStatement,
)
from rhosocial.activerecord.backend.expression.objects import Table, View
from rhosocial.activerecord.backend.expression.statements import (
    ColumnDefinition,
    ColumnGeneratedConstraint,
    DropTableStatement,
    GeneratedColumnType,
    TruncateStatement,
)
from rhosocial.activerecord.backend.expression.statements.ddl_alter import (
    DropTableConstraintAction,
    RenameColumnAction,
)
from rhosocial.activerecord.backend.expression.types import IntegerType
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect


@pytest.fixture
def dialect():
    return BigQueryDialect()


def test_generated_column_capabilities(dialect):
    assert dialect.supports_generated_columns() is True
    assert dialect.supports_stored_generated_columns() is True
    assert dialect.supports_virtual_generated_columns() is False


def test_identity_column_capabilities(dialect):
    """BigQuery identity columns (Preview, 2026-08-31): documented option by option.

    ``START WITH`` / ``INCREMENT BY`` are in the ``identity_column`` grammar;
    ``MINVALUE`` / ``MAXVALUE`` / ``CYCLE`` / ``ORDER`` / ``CACHE`` are not, so
    those probes decline. Each declined option is a pair now (``cycle`` /
    ``no_cycle`` and so on); the probe answers for the option and the formatter
    refuses each requested spelling by name.
    These are documentation answers, not execution results -- no BigQuery
    instance is available.
    """
    assert dialect.supports_identity_column() is True
    assert dialect.supports_identity_generation_always() is True
    assert dialect.supports_identity_start() is True
    assert dialect.supports_identity_increment() is True
    assert dialect.supports_identity_minvalue() is False
    assert dialect.supports_identity_maxvalue() is False
    assert dialect.supports_identity_cycle() is False
    assert dialect.supports_identity_order() is False
    assert dialect.supports_identity_cache() is False


def test_auto_increment_column_capability(dialect):
    """BigQuery has no ``AUTO_INCREMENT`` keyword; the marker is declined.

    The old ``supports_auto_increment()`` answered ``True`` for the standard
    clause without any renderer reading it; it is deleted from core and must
    not linger here as dead code.
    """
    assert dialect.supports_auto_increment_column() is False
    assert not hasattr(dialect, "supports_auto_increment")


def test_generated_stored_column_renders(dialect):
    column = ColumnDefinition(
        dialect,
        "total",
        IntegerType(dialect),
        generated_expression=ColumnGeneratedConstraint(
            dialect,
            ArithmeticOperation(dialect, "add", Column(dialect, "a"), Column(dialect, "b")),
            storage_type=GeneratedColumnType.STORED,
        ),
    )
    sql, _ = CreateTableStatement(dialect, Table(dialect, "t"), [column]).to_sql()
    assert "GENERATED ALWAYS AS (`a` + `b`) STORED" in sql


def test_virtual_generated_column_rejected(dialect):
    column = ColumnDefinition(
        dialect,
        "total",
        IntegerType(dialect),
        generated_expression=ColumnGeneratedConstraint(
            dialect,
            Column(dialect, "a"),
            storage_type=GeneratedColumnType.VIRTUAL,
        ),
    )
    with pytest.raises(UnsupportedFeatureError, match="VIRTUAL"):
        CreateTableStatement(dialect, Table(dialect, "t"), [column]).to_sql()


def test_truncate_and_drop_table(dialect):
    assert dialect.supports_truncate_table_keyword() is True
    assert dialect.supports_if_exists_table() is True
    # The dataset rides in the table object's own slot, so an unqualified
    # truncate and a dataset-qualified one are one construction each.
    assert TruncateStatement(dialect, Table(dialect, "t")).to_sql()[0] == (
        "TRUNCATE TABLE `t`"
    )
    assert TruncateStatement(
        dialect, Table(dialect, "t", schema_name="app")
    ).to_sql()[0] == "TRUNCATE TABLE `app`.`t`"
    assert DropTableStatement(dialect, Table(dialect, "t"), if_exists=True).to_sql()[0] == (
        "DROP TABLE IF EXISTS `t`"
    )


def test_views_supported_and_render(dialect):
    assert dialect.supports_views() is True
    query = QueryStatement(
        dialect, select=[Column(dialect, "id")], from_=Table(dialect, "t")
    )
    sql, _ = CreateViewStatement(dialect, view=View(dialect, "v"), query=query).to_sql()
    assert sql.startswith("CREATE VIEW `v`")
    assert "SELECT `id` FROM `t`" in sql


def test_if_exists_family_probes(dialect):
    """Pin the IF [NOT] EXISTS answers this dialect owns.

    Each ``True`` below is read off the official DDL grammar (fetched
    2026-11-25):
    https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language

    The two index switches stay ``False``: BigQuery has no plain
    ``CREATE INDEX`` / ``DROP INDEX`` statement.  Its only index DDL is
    ``CREATE SEARCH INDEX`` / ``DROP SEARCH INDEX``, a different statement
    with its own ``ON table`` syntax, which the generic index expressions do
    not model.
    """
    assert dialect.supports_if_not_exists_table() is True
    assert dialect.supports_add_column_if_not_exists() is True
    assert dialect.supports_drop_column_if_exists() is True
    assert dialect.supports_if_exists_table() is True
    assert dialect.supports_schema_if_not_exists() is True
    assert dialect.supports_schema_if_exists() is True
    assert dialect.supports_index_if_not_exists() is False
    assert dialect.supports_index_if_exists() is False


def test_create_table_if_not_exists_renders(dialect):
    column = ColumnDefinition(dialect, "id", IntegerType(dialect))
    sql, params = CreateTableStatement(
        dialect, Table(dialect, "t"), [column], if_not_exists=True
    ).to_sql()
    assert sql == "CREATE TABLE IF NOT EXISTS `t` (`id` INT64)"
    assert params == ()


def test_rename_column_renders(dialect):
    """The grammar is ``RENAME COLUMN column_name TO new_column_name``.

    BigQuery has supported it since 2022-08-19 (preview), generally available
    since 2023-02-21:
    https://cloud.google.com/bigquery/docs/release-notes-archive
    """
    assert dialect.supports_rename_column() is True
    expression = AlterTableStatement(
        dialect,
        table=Table(dialect, "t"),
        actions=[RenameColumnAction(dialect, "old", "new")],
    )
    sql, params = expression.to_sql()
    assert sql == "ALTER TABLE `t` RENAME COLUMN `old` TO `new`"
    assert params == ()


def test_drop_constraint_if_exists_renders(dialect):
    """BigQuery's DDL page does contain constraint DDL, foreign keys only.

    ``ALTER TABLE ... DROP CONSTRAINT [ IF EXISTS ] constraint_name``:
    https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language#alter_table_drop_constraint_statement
    """
    assert dialect.supports_drop_constraint() is True
    assert dialect.supports_drop_constraint_if_exists() is True
    expression = AlterTableStatement(
        dialect,
        table=Table(dialect, "t"),
        actions=[
            DropTableConstraintAction(dialect, "fk", if_exists=True),
        ],
    )
    sql, params = expression.to_sql()
    assert sql == "ALTER TABLE `t` DROP CONSTRAINT IF EXISTS `fk`"
    assert params == ()
