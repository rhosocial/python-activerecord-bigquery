"""Dialect tests for BigQuery backend."""


def test_dialect_quote_identifier():
    from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect
    dialect = BigQueryDialect()
    assert dialect.format_identifier("my_table") == "`my_table`"
