# tests/rhosocial/activerecord_bigquery_test/feature/backend/dialect/test_generated_value_suggestion.py
"""BigQuery's generated-value suggestion is a plain, no-clause DDL answer."""

import pytest
from rhosocial.activerecord.backend.expression.types import IntegerType
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect
from rhosocial.activerecord.backend.impl.bigquery.mixins import (
    BigQueryGeneratedValueSuggestionMixin,
)
from rhosocial.activerecord.backend.suggestion.protocols import (
    GeneratedValueSuggestionSupport,
)


@pytest.fixture
def dialect():
    return BigQueryDialect()


def test_dialect_implements_generated_value_suggestion(dialect):
    assert isinstance(dialect, GeneratedValueSuggestionSupport)
    assert isinstance(dialect, BigQueryGeneratedValueSuggestionMixin)


def test_suggestion_keeps_the_declared_type_and_adds_no_clause(dialect):
    declared = IntegerType()
    suggestion = dialect.suggest_generated_value(declared)
    assert suggestion.state == "embedded-in-type"
    assert suggestion.storage_type is declared
    assert suggestion.clause is None


def test_mixin_does_not_inherit_the_protocol():
    """A Protocol base would swallow constructor arguments under strict validation."""
    assert not any(
        base.__name__ == "Protocol" for base in BigQueryGeneratedValueSuggestionMixin.__mro__
    )


def test_dialect_strict_validation_is_intact(dialect):
    """The plain-class mixin must not break the dialect constructor."""
    assert dialect.strict_validation is True
