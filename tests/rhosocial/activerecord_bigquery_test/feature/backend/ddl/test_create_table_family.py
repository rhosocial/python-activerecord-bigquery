# tests/rhosocial/activerecord_bigquery_test/feature/backend/ddl/test_create_table_family.py
"""BigQuery CREATE TABLE family tests (LIKE / CLONE / COPY).

BigQuery reuses the generic core TableMixin renderers once the capability
flags are advertised. Pure construction tests — no real instance required.
"""

import pytest

from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect
from rhosocial.activerecord.backend.expression import (
    CreateTableLikeExpression,
    CreateTableCloneExpression,
    CreateTableCloneMode,
)


@pytest.fixture
def dialect():
    return BigQueryDialect()


class TestBigQueryCreateTableFamily:
    """Capability flags and generic rendering for the CREATE TABLE family."""

    def test_capabilities(self, dialect):
        assert dialect.supports_create_table_like() is True
        assert dialect.supports_create_table_clone() is True

    def test_create_table_like(self, dialect):
        sql, params = CreateTableLikeExpression(dialect, "copy", "src").to_sql()
        assert sql == "CREATE TABLE `copy` LIKE `src`"
        assert params == ()

    def test_create_table_clone(self, dialect):
        sql, params = CreateTableCloneExpression(dialect, "clone_t", "src").to_sql()
        assert sql == "CREATE TABLE `clone_t` CLONE `src`"
        assert params == ()

    def test_create_table_copy(self, dialect):
        sql, params = CreateTableCloneExpression(
            dialect, "copy_t", "src", mode=CreateTableCloneMode.COPY
        ).to_sql()
        assert sql == "CREATE TABLE `copy_t` COPY `src`"
        assert params == ()
