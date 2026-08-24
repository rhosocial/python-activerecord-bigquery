"""BigQuery backend feature tests - protocol conformance."""
import pytest

from rhosocial.activerecord.backend.impl.bigquery import (
    BigQueryBackend, BigQueryConnectionConfig,
    BigQueryDialect,
)


@pytest.mark.requires_protocol
class TestBigQueryStructProtocol:
    def test_supports_struct_true(self):
        dialect = BigQueryDialect()
        assert dialect.supports_struct() is True


@pytest.mark.requires_protocol
class TestBigQueryArrayProtocol:
    def test_supports_array_true(self):
        dialect = BigQueryDialect()
        assert dialect.supports_array() is True


@pytest.mark.requires_protocol
class TestBigQueryJSONProtocol:
    def test_supports_json_true(self):
        dialect = BigQueryDialect()
        assert dialect.supports_json() is True


@pytest.mark.requires_protocol
class TestBigQueryGeographyProtocol:
    def test_supports_geography_true(self):
        dialect = BigQueryDialect()
        assert dialect.supports_geography() is True


@pytest.mark.requires_protocol
class TestBigQueryDialectFormatting:
    def test_backtick_identifier(self):
        dialect = BigQueryDialect()
        assert dialect.format_identifier("table_name") == "`table_name`"

    def test_named_parameter_placeholder(self):
        dialect = BigQueryDialect()
        # Positional `?` placeholders are used because the expression system
        # emits every placeholder with the default index; unique named
        # parameters would collide.
        assert dialect.get_parameter_placeholder(0) == "?"
