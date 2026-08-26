# tests/rhosocial/activerecord_bigquery_test/feature/backend/test_schema_support.py
"""Tests for the SchemaSupport capability declared on the BigQuery dialect.

BigQuery qualifies tables with datasets, so ``supports_schema()`` is True.
Granular schema DDL capability bits are not wired up yet and stay False.
"""
from rhosocial.activerecord.backend.dialect.protocols import SchemaSupport
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect


class TestSchemaCapability:
    """Umbrella flag and granular schema DDL capability bits."""

    def _dialect(self) -> BigQueryDialect:
        return BigQueryDialect()

    def test_supports_schema_is_true(self):
        assert self._dialect().supports_schema() is True

    def test_implements_schema_support_protocol(self):
        assert isinstance(self._dialect(), SchemaSupport)

    def test_granular_ddl_flags_currently_false(self):
        """Documents current state until CREATE/DROP SCHEMA DDL is wired up."""
        d = self._dialect()
        assert d.supports_create_schema() is False
        assert d.supports_drop_schema() is False
