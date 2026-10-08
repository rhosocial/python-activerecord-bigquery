# tests/rhosocial/activerecord_bigquery_test/feature/backend/dialect/test_column_schema_validation.py
"""
C18 -- a bare column carrying `schema_name` is reported, not dropped.

BigQuery never prefixes a column with a project or a dataset: GoogleSQL
qualifies a column through its relation, and the namespace belongs to the
relation named in FROM. So with a table present, leaving the namespace off the
column is the correct rendering, not a lost one.

Without a table there is no relation for the namespace to qualify. That case
used to emit a `UserWarning` and drop the dataset -- the shape this whole
refactor exists to remove, because a warning nobody reads leaves the tests
green and the data gone. It now raises `UnsupportedFeatureError`.
"""

import pytest

from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError
from rhosocial.activerecord.backend.expression.core import Column
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect


class TestBareColumnWithSchema:
    def test_raises_rather_than_dropping_the_dataset(self, dialect):
        with pytest.raises(UnsupportedFeatureError) as exc:
            Column(dialect, "id", schema_name="s").to_sql()
        message = str(exc.value)
        assert "schema-qualified column references" in message
        # The error names what was lost, so the caller can act on it.
        assert "schema_name='s'" in message
        assert "id" in message

    def test_column_is_unqualified_when_a_table_carries_the_dataset(self, dialect):
        """A table present means the namespace is redundant, not lost.

        `dataset.table.column` is a legal GoogleSQL path, but the dialect
        renders the two-part form: the dataset is already on the FROM relation,
        and repeating it here would be a second place to keep it correct.
        """
        sql, params = Column(dialect, "id", table="t", schema_name="s").to_sql()
        assert sql == "`t`.`id`"
        assert params == ()

    def test_bare_column_without_schema_is_untouched(self, dialect):
        sql, params = Column(dialect, "id").to_sql()
        assert sql == "`id`"
        assert params == ()


class TestColumnQualificationCapability:
    """The rule is a declared capability, not an accident of the formatter."""

    def test_capability_is_false(self, dialect):
        assert dialect.supports_column_namespace_qualification() is False

    def test_capability_is_declared_on_the_protocol(self, dialect):
        from rhosocial.activerecord.backend.impl.bigquery.protocols import (
            BigQueryColumnQualificationSupport,
        )

        assert isinstance(dialect, BigQueryColumnQualificationSupport)


@pytest.fixture
def dialect():
    return BigQueryDialect()