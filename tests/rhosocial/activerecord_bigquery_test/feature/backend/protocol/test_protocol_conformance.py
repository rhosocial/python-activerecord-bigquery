"""Protocol conformance tests for BigQuery backend."""
import pytest

from rhosocial.activerecord.backend.impl.bigquery import (
    BigQueryStructSupport,
    BigQueryArraySupport,
    BigQueryJSONSupport,
    BigQueryGeographySupport,
)


class TestBigQueryStructSupport:
    def test_supports_struct(self):
        from rhosocial.activerecord.backend.impl.bigquery.mixins import BigQueryStructMixin
        mixin = BigQueryStructMixin()
        assert mixin.supports_struct() is True


class TestBigQueryArraySupport:
    def test_supports_array(self):
        from rhosocial.activerecord.backend.impl.bigquery.mixins import BigQueryArrayMixin
        mixin = BigQueryArrayMixin()
        assert mixin.supports_array() is True


class TestBigQueryJSONSupport:
    def test_supports_json(self):
        from rhosocial.activerecord.backend.impl.bigquery.mixins import BigQueryJSONMixin
        mixin = BigQueryJSONMixin()
        assert mixin.supports_json() is True


class TestBigQueryGeographySupport:
    def test_supports_geography(self):
        from rhosocial.activerecord.backend.impl.bigquery.mixins import BigQueryGeographyMixin
        mixin = BigQueryGeographyMixin()
        assert mixin.supports_geography() is True


class TestBigQueryDialectProtocols:
    def test_dialect_has_protocol_methods(self):
        from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect
        dialect = BigQueryDialect()
        assert dialect.supports_struct() is True
        assert dialect.supports_array() is True
        assert dialect.supports_json() is True
        assert dialect.supports_geography() is True
