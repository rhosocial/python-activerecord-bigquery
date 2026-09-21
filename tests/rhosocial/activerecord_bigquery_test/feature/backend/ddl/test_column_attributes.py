# tests/rhosocial/activerecord_bigquery_test/feature/backend/ddl/test_column_attributes.py
"""BigQuery rendering of the dialect-free column-attribute channel."""

from rhosocial.activerecord.backend.expression.statements import ColumnDefinition
from rhosocial.activerecord.backend.expression.types import IntegerType
from rhosocial.activerecord.base.ddl.attributes import CollationAttribute, IdentityAttribute
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect


def _column(dialect, attrs):
    col = ColumnDefinition(dialect, "id", IntegerType(dialect))
    col.attributes = dialect.select_column_attributes(attrs)
    return col


def test_collation_is_quoted_string_literal():
    dialect = BigQueryDialect()
    col = _column(dialect, [CollationAttribute(name="und:ci")])
    assert col.to_sql()[0] == "`id` INT64 COLLATE 'und:ci'"


def test_identity_is_not_selected():
    dialect = BigQueryDialect()
    col = _column(dialect, [IdentityAttribute(generation="BY DEFAULT")])
    assert col.attributes == []
    assert col.to_sql()[0] == "`id` INT64"
