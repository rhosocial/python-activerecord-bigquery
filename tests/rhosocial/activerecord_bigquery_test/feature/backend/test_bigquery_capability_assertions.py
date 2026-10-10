# tests/rhosocial/activerecord_bigquery_test/feature/backend/test_bigquery_capability_assertions.py
"""Explicit BigQuery DDL capability + rendering assertions.

BigQuery relies on the generic core formatters for CREATE TABLE, views,
TRUNCATE and DROP TABLE; these tests pin the capability bits and verify the
generic renderers produce BigQuery-compatible SQL.
"""

import pytest

from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError
from rhosocial.activerecord.backend.expression import (
    BinaryArithmeticExpression,
    Column,
    CreateTableExpression,
    CreateViewExpression,
    QueryExpression,
)
from rhosocial.activerecord.backend.expression.objects import Table, View
from rhosocial.activerecord.backend.expression.statements import (
    ColumnDefinition,
    DropTableExpression,
    GeneratedColumnExpression,
    GeneratedColumnType,
    TruncateExpression,
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
        generated_expression=GeneratedColumnExpression(
            dialect,
            BinaryArithmeticExpression(dialect, "+", Column(dialect, "a"), Column(dialect, "b")),
            storage_type=GeneratedColumnType.STORED,
        ),
    )
    sql, _ = CreateTableExpression(dialect, Table(dialect, "t"), [column]).to_sql()
    assert "GENERATED ALWAYS AS (`a` + `b`) STORED" in sql


def test_virtual_generated_column_rejected(dialect):
    column = ColumnDefinition(
        dialect,
        "total",
        IntegerType(dialect),
        generated_expression=GeneratedColumnExpression(
            dialect,
            Column(dialect, "a"),
            storage_type=GeneratedColumnType.VIRTUAL,
        ),
    )
    with pytest.raises(UnsupportedFeatureError, match="VIRTUAL"):
        CreateTableExpression(dialect, Table(dialect, "t"), [column]).to_sql()


def test_truncate_and_drop_table(dialect):
    assert dialect.supports_truncate_table_keyword() is True
    assert dialect.supports_if_exists_table() is True
    # The dataset rides in the table object's own slot, so an unqualified
    # truncate and a dataset-qualified one are one construction each.
    assert TruncateExpression(dialect, Table(dialect, "t")).to_sql()[0] == (
        "TRUNCATE TABLE `t`"
    )
    assert TruncateExpression(
        dialect, Table(dialect, "t", schema_name="app")
    ).to_sql()[0] == "TRUNCATE TABLE `app`.`t`"
    assert DropTableExpression(dialect, Table(dialect, "t"), if_exists=True).to_sql()[0] == (
        "DROP TABLE IF EXISTS `t`"
    )


def test_views_supported_and_render(dialect):
    assert dialect.supports_views() is True
    query = QueryExpression(
        dialect, select=[Column(dialect, "id")], from_=Table(dialect, "t")
    )
    sql, _ = CreateViewExpression(dialect, view=View(dialect, "v"), query=query).to_sql()
    assert sql.startswith("CREATE VIEW `v`")
    assert "SELECT `id` FROM `t`" in sql
