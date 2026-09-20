# tests/rhosocial/activerecord_bigquery_test/feature/backend/test_bigquery_capability_assertions.py
"""Explicit BigQuery DDL capability + rendering assertions.

BigQuery relies on the generic core formatters for CREATE TABLE, views,
TRUNCATE and DROP TABLE; these tests pin the capability bits and verify the
generic renderers produce BigQuery-compatible SQL.
"""

import pytest

from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError
from rhosocial.activerecord.backend.expression import (
    Column,
    CreateTableExpression,
    CreateViewExpression,
    QueryExpression,
    TableExpression,
)
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


def test_generated_stored_column_renders(dialect):
    column = ColumnDefinition(
        dialect,
        "total",
        IntegerType(dialect),
        generated_expression=GeneratedColumnExpression(
            dialect,
            Column(dialect, "a") + Column(dialect, "b"),
            storage_type=GeneratedColumnType.STORED,
        ),
    )
    sql, _ = CreateTableExpression(dialect, "t", [column]).to_sql()
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
        CreateTableExpression(dialect, "t", [column]).to_sql()


def test_truncate_and_drop_table(dialect):
    assert dialect.supports_truncate_table_keyword() is True
    assert dialect.supports_if_exists_table() is True
    assert TruncateExpression(dialect, "t").to_sql()[0] == "TRUNCATE TABLE `t`"
    assert DropTableExpression(dialect, "t", if_exists=True).to_sql()[0] == (
        "DROP TABLE IF EXISTS `t`"
    )


def test_views_supported_and_render(dialect):
    assert dialect.supports_views() is True
    query = QueryExpression(
        dialect, select=[Column(dialect, "id")], from_=TableExpression(dialect, "t")
    )
    sql, _ = CreateViewExpression(dialect, view_name="v", query=query).to_sql()
    assert sql.startswith("CREATE VIEW `v`")
    assert "SELECT `id` FROM `t`" in sql
