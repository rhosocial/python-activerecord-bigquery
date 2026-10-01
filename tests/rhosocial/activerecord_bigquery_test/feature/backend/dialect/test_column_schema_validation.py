# tests/rhosocial/activerecord_bigquery_test/feature/backend/dialect/test_column_schema_validation.py
"""
C18 -- a bare column carrying `schema_name` cannot be qualified.

The core dialect raises here. BigQuery qualifies by *database* rather than schema,
so a schema on a table-less column is meaningless rather than dangerous, and
this backend warns instead of raising. That keeps a single model definition
usable against both PostgreSQL and BigQuery.
"""

import warnings

import pytest

from rhosocial.activerecord.backend.expression.core import Column
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect


class TestBareColumnWithSchema:
    def test_warns_when_schema_dropped(self, dialect):
        with pytest.warns(UserWarning, match="no table was given"):
            sql, params = Column(dialect, "id", schema_name="s").to_sql()
        assert sql in ('"${}"'.format("id"), "`id`")
        assert params == ()

    def test_no_warning_when_table_present(self, dialect):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            Column(dialect, "id", table="t", schema_name="s").to_sql()
        assert not [w for w in caught if "no table was given" in str(w.message)]

    def test_bare_column_without_schema_is_silent(self, dialect):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            Column(dialect, "id").to_sql()
        assert not [w for w in caught if "no table was given" in str(w.message)]


@pytest.fixture
def dialect():
    return BigQueryDialect()
