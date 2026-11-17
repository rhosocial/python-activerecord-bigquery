# tests/rhosocial/activerecord_bigquery_test/feature/backend/expression/test_expressions.py
"""Expression/SQL formatting feature tests."""


def test_expression_format_identifier():
    from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect
    dialect = BigQueryDialect()
    assert dialect.format_identifier("users") == "`users`"


def test_expression_type_mapping_exists():
    from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect
    dialect = BigQueryDialect()
    mappings = dialect.get_type_mappings()
    assert "INTEGER" in mappings
    assert mappings["INTEGER"] == "INT64"
