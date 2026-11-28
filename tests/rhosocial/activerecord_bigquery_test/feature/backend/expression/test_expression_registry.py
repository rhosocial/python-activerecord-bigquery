# tests/rhosocial/activerecord_bigquery_test/feature/backend/expression/test_expression_registry.py
"""BigQuery's expression table is core's kinds plus its own, published as a value.

A backend's table is a merge of two mappings -- core's and this backend's own --
frozen once at assembly. It names classes; it does not import them until a kind
is resolved, and no dialect or sibling backend takes part in the table. These
cases assert that boundary, then the one position-level decision a value makes
when it reaches BigQuery SQL: bind by default, or render inline text.

Everything here is construction and rendering; nothing opens a connection.
"""

import importlib

import pytest

from rhosocial.activerecord.backend.expression.coerce import value_expression
from rhosocial.activerecord.backend.expression.core import Column, FunctionCall, Parameter
from rhosocial.activerecord.backend.expression.predicates import ComparisonPredicate
from rhosocial.activerecord.backend.expression_registry import CORE_EXPRESSIONS
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect
from rhosocial.activerecord.backend.impl.bigquery.expression.partition import (
    BigQueryTablePartitionByClause,
)
from rhosocial.activerecord.backend.impl.bigquery.expression_registry import (
    BIGQUERY_EXPRESSIONS,
    BIGQUERY_EXPRESSION_REGISTRY,
)

# Sibling backends that the framework may have installed: (module, own mapping).
# Their kinds are not BigQuery's; the ones core also owns are shared, not theirs.
_SIBLINGS = (
    ("rhosocial.activerecord.backend.impl.sqlite.expression_registry", "SQLITE_EXPRESSIONS"),
    ("rhosocial.activerecord.backend.impl.dummy.expression_registry", "DUMMY_EXPRESSIONS"),
)


@pytest.fixture
def dialect():
    return BigQueryDialect()


class TestThePublishedTable:
    def test_it_is_frozen_and_holds_core_plus_bigquery_kinds(self):
        registry = BIGQUERY_EXPRESSION_REGISTRY
        assert registry.is_frozen
        assert set(registry.node_kinds()) == set(CORE_EXPRESSIONS) | set(BIGQUERY_EXPRESSIONS)

        with pytest.raises(Exception) as caught:
            registry.unregister_node("parameter")
        assert "frozen" in str(caught.value)

    def test_it_carries_no_sibling_backend_only_kind(self):
        kinds = set(BIGQUERY_EXPRESSION_REGISTRY.node_kinds())
        for module_name, mapping_name in _SIBLINGS:
            try:
                module = importlib.import_module(module_name)
            except ImportError:
                continue  # a backend that is not installed contributes nothing
            only_its_own = set(getattr(module, mapping_name)) - set(CORE_EXPRESSIONS)
            assert not (only_its_own & kinds), f"{module_name} kinds in BigQuery's table"

        # Named guards: the two canonical sibling-only kinds stay out even if a
        # sibling is not installed in this checkout.
        assert "sqlite_vacuum_statement" not in kinds
        assert "_dummy_type_definition" not in kinds


class TestResolution:
    def test_parameter_resolves_to_cores_node(self):
        assert BIGQUERY_EXPRESSION_REGISTRY.resolve_node("parameter") is Parameter

    def test_a_bigquery_owned_kind_resolves_to_its_class(self):
        kind = "bigquery_table_partition_by_clause"
        assert kind in BIGQUERY_EXPRESSIONS
        assert BIGQUERY_EXPRESSION_REGISTRY.resolve_node(kind) is BigQueryTablePartitionByClause


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
