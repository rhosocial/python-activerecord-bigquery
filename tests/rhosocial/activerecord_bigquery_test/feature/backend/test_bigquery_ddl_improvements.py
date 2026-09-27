# tests/rhosocial/activerecord_bigquery_test/feature/backend/test_bigquery_ddl_improvements.py
"""Tests for BigQuery DDL improvements: capability gating, UnsupportedFeatureError."""
import pytest

from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError
from rhosocial.activerecord.backend.expression import CreateTableExpression
from rhosocial.activerecord.backend.expression.statements import ColumnDefinition
from rhosocial.activerecord.backend.expression.types import IntegerType
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect


class TestBigQueryViewCapabilityGating:
    """Tests for BigQuery VIEW DDL capability gating."""

    def test_create_or_replace_view_supported(self):
        """BigQuery supports CREATE OR REPLACE VIEW."""
        dialect = BigQueryDialect()
        assert dialect.supports_create_or_replace_view() is True

    def test_create_view_if_not_exists_not_supported(self):
        """BigQuery does not support CREATE VIEW IF NOT EXISTS."""
        dialect = BigQueryDialect()
        assert dialect.supports_if_not_exists_view() is False

    def test_drop_view_if_exists_not_supported(self):
        """BigQuery does not support DROP VIEW IF EXISTS."""
        dialect = BigQueryDialect()
        assert dialect.supports_if_exists_view() is False

    def test_materialized_view_supported(self):
        """BigQuery has native materialized views.

        Refresh is option-driven (``OPTIONS(enable_refresh=…,
        refresh_interval_minutes=…)``) because BigQuery has no
        ``REFRESH MATERIALIZED VIEW`` statement.
        """
        dialect = BigQueryDialect()
        assert dialect.supports_materialized_view() is True
        assert dialect.supports_refresh_materialized_view() is False


class TestBigQuerySchemaCapabilityGating:
    """Tests for BigQuery SCHEMA DDL capability gating."""

    def test_create_schema_supported(self):
        """BigQuery supports CREATE SCHEMA (CREATE DATASET)."""
        dialect = BigQueryDialect()
        assert dialect.supports_create_schema() is True

    def test_drop_schema_supported(self):
        """BigQuery supports DROP SCHEMA (DROP DATASET)."""
        dialect = BigQueryDialect()
        assert dialect.supports_drop_schema() is True

    def test_schema_if_not_exists_supported(self):
        """BigQuery supports CREATE SCHEMA IF NOT EXISTS."""
        dialect = BigQueryDialect()
        assert dialect.supports_schema_if_not_exists() is True

    def test_schema_if_exists_supported(self):
        """BigQuery supports DROP SCHEMA IF EXISTS."""
        dialect = BigQueryDialect()
        assert dialect.supports_schema_if_exists() is True

    def test_schema_cascade_not_supported(self):
        """BigQuery does not support DROP SCHEMA CASCADE."""
        dialect = BigQueryDialect()
        assert dialect.supports_schema_cascade() is False


class TestBigQueryTableDeclarationGating:
    def test_table_declaration_defaults_are_absent(self):
        dialect = BigQueryDialect()
        expression = CreateTableExpression(
            dialect,
            "plain_table_defaults",
            [ColumnDefinition(dialect, "id", IntegerType(dialect))],
        )
        sql, params = expression.to_sql()
        assert expression.inherits == []
        assert expression.tablespace is None
        assert "plain_table_defaults" in sql.lower()
        assert "id" in sql.lower()
        assert params == ()

    def test_table_inherits_is_propagated_and_rejected(self):
        dialect = BigQueryDialect()
        assert dialect.supports_table_inheritance() is False
        expression = CreateTableExpression(
            dialect,
            "inherited",
            [ColumnDefinition(dialect, "id", IntegerType(dialect))],
            inherits=["parent_a", "parent_b"],
        )
        assert expression.inherits == ["parent_a", "parent_b"]
        with pytest.raises(UnsupportedFeatureError, match="INHERITS"):
            expression.to_sql()

    def test_table_tablespace_is_propagated_and_rejected(self):
        dialect = BigQueryDialect()
        assert dialect.supports_table_tablespace() is False
        expression = CreateTableExpression(
            dialect,
            "tablespaced",
            [ColumnDefinition(dialect, "id", IntegerType(dialect))],
            tablespace="ts_data",
        )
        assert expression.tablespace == "ts_data"
        with pytest.raises(UnsupportedFeatureError, match="TABLESPACE"):
            expression.to_sql()
