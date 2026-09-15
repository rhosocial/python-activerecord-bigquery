# tests/rhosocial/activerecord_bigquery_test/feature/backend/test_bigquery_ddl_improvements.py
"""Tests for BigQuery DDL improvements: capability gating, UnsupportedFeatureError."""
import pytest
from unittest.mock import patch, PropertyMock

from rhosocial.activerecord.backend.expression import (
    Column,
    TableExpression,
    QueryExpression,
    CreateViewExpression,
    DropViewExpression,
)
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect
from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError


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

    def test_materialized_view_not_supported(self):
        """BigQuery does not support materialized views via CREATE MATERIALIZED VIEW."""
        dialect = BigQueryDialect()
        assert dialect.supports_materialized_view() is False


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
