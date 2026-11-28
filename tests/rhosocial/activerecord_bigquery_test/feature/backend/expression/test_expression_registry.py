# tests/rhosocial/activerecord_bigquery_test/feature/backend/expression/test_expression_registry.py
"""The one position-level decision a value makes when it reaches BigQuery SQL.

Table-shape rules (frozen, core-plus-own merge, no siblings, resolution) live in
the shared registry contract. Kept here is the value-position behaviour: bind by
default, render inline text on request, and bind a raw value.

Everything here is construction and rendering; nothing opens a connection.
"""

import pytest

from rhosocial.activerecord.backend.expression.coerce import value_expression
from rhosocial.activerecord.backend.expression.core import Column, FunctionCall, Parameter
from rhosocial.activerecord.backend.expression.predicates import ComparisonPredicate
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect


@pytest.fixture
def dialect():
    return BigQueryDialect()


class TestValuePositions:
    def test_parameter_binds_by_default_with_this_dialects_placeholder(self, dialect):
        sql, params = Parameter(dialect, "abc").to_sql()
        assert sql == dialect.get_parameter_placeholder() == "?"
        assert params == ("abc",)

    def test_inline_renders_backend_sql_text_with_empty_params(self, dialect):
        value = "O'Brien"
        sql, params = Parameter(dialect, value, inline=True).to_sql()
        # BigQuery escapes a quote with a backslash, not by doubling it.
        assert sql == dialect.format_literal(value) == "'O\\'Brien'"
        assert params == ()

    def test_a_raw_value_at_a_value_position_is_bound_not_inlined(self, dialect):
        sql, params = value_expression(dialect, "O'Brien").to_sql()
        assert sql == "?"
        assert params == ("O'Brien",)

        predicate = ComparisonPredicate(dialect, "=", Column(dialect, "id"), "O'Brien")
        assert isinstance(predicate.right, Parameter)
        assert predicate.right.value == "O'Brien"
        assert predicate.to_sql() == ("`id` = ?", ("O'Brien",))
        assert "O'Brien" not in predicate.to_sql()[0]

        call = FunctionCall(dialect, "LOWER", "abc")
        assert call.to_sql() == ("LOWER(?)", ("abc",))
