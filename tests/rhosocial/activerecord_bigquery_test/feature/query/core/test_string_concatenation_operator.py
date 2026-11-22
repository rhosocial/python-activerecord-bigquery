# tests/rhosocial/activerecord_bigquery_test/feature/query/test_string_concatenation_operator.py
"""``||`` is concatenation in SQL and logical OR in several backends.

PostgreSQL, Oracle, Snowflake, Firebird and ClickHouse read ``||`` as string
concatenation. MySQL and MariaDB read it as logical OR unless the server runs
with ``PIPES_AS_CONCAT``, and SQL Server reads it as logical OR outright.
Emitting the bare token on those backends returns a boolean where a string was
meant — a wrong answer rather than a syntax error, which is why it can survive
a test suite.

So the node records the *intent* and the dialect picks the spelling. These
tests pin the contract: the intent survives the round trip, the default is the
standard operator, and a dialect that declares a function gets one.
"""

# tests/rhosocial/activerecord_bigquery_test/feature/query/test_string_concatenation_operator.py
import pytest

from rhosocial.activerecord.backend.expression import StringColumn
from rhosocial.activerecord.backend.expression import functions as string_functions
from rhosocial.activerecord.backend.expression.operators import (
    BinaryExpression,
    ConcatenationOperation,
)


@pytest.fixture
def dialect():
    from rhosocial.activerecord.backend.impl.sqlite.dialect import SQLiteDialect

    d = SQLiteDialect()
    d._version = (3, 46, 1)
    return d


@pytest.fixture
def operands(dialect):
    """Two string columns.

    StringColumn rather than Column: the point of the round trip is that the
    result is still a string, and a bare Column carries no string surface to
    lose.
    """
    return (
        StringColumn(dialect, "a", table="t"),
        StringColumn(dialect, "b", table="t"),
    )


# ---------------------------------------------------------------------------
# The node carries intent, not an operator
# ---------------------------------------------------------------------------


def test_concat_op_builds_an_intent_node(dialect, operands):
    left, right = operands
    expr = string_functions.concat_op(dialect, left, right)
    assert isinstance(expr, ConcatenationOperation)


def test_the_intent_node_is_not_a_bare_binary_expression(dialect, operands):
    """The node is its own kind, not a BinaryExpression with a token.

    A bare BinaryExpression with op ``||`` says nothing about intent, which is
    exactly why concat_op stopped producing one.
    """
    left, right = operands
    expr = string_functions.concat_op(dialect, left, right)
    assert not isinstance(expr, BinaryExpression)
    assert expr.left is left and expr.right is right


def test_the_operator_is_not_a_parameter(dialect, operands):
    """Concatenation carries no ``op``: the kind is the intent.

    ``left`` and ``right`` are the node's only construction parameters, so
    nothing about the operator token travels in the artifact.
    """
    left, right = operands
    expr = ConcatenationOperation(dialect, left, right)
    assert not hasattr(expr, "op")
    assert set(expr.get_params()) == {"left", "right"}


# ---------------------------------------------------------------------------
# The default spelling
# ---------------------------------------------------------------------------


def test_default_dialect_uses_the_standard_operator(dialect, operands):
    """SQLite and PostgreSQL both read ``||`` as concatenation."""
    left, right = operands
    assert dialect.suggest_concatenation_function().function is None
    assert string_functions.concat_op(dialect, left, right).to_sql()[
        0
    ] == '"t"."a" || "t"."b"'


def test_a_declared_function_replaces_the_operator(dialect, operands):
    """The declaration is consulted, so the same node renders differently."""
    left, right = operands
    dialect.STRING_CONCATENATION = "CONCAT"
    assert dialect.suggest_concatenation_function().function == "CONCAT"
    assert string_functions.concat_op(dialect, left, right).to_sql()[0] == (
        'CONCAT("t"."a", "t"."b")'
    )


def test_declaration_must_be_a_string(dialect):
    """A non-string declaration is ignored rather than interpolated."""
    dialect.STRING_CONCATENATION = None
    assert dialect.suggest_concatenation_function().function is None
    dialect.STRING_CONCATENATION = 42
    assert dialect.suggest_concatenation_function().function is None


# ---------------------------------------------------------------------------
# Chaining: the result is a string
# ---------------------------------------------------------------------------


def test_result_keeps_the_string_value_surface(operands):
    left, _ = operands
    result = left.concat_using_operator("x")
    for method in ("upper", "substr", "like", "trim", "concat_using_operator"):
        assert hasattr(result, method), f"concatenation lost {method}"


def test_chaining_after_concatenation(operands):
    left, right = operands
    sql, _ = left.concat_using_operator(right).upper().to_sql()
    assert "UPPER" in sql
    assert "||" in sql or "CONCAT" in sql


def test_alias_reaches_the_sql(operands):
    left, right = operands
    sql, _ = left.concat_using_operator(right).as_("joined").to_sql()
    assert " AS " in sql


def test_no_alias_means_no_as(operands):
    left, right = operands
    sql, _ = left.concat_using_operator(right).to_sql()
    assert " AS " not in sql


def test_parameters_are_preserved(operands):
    left, right = operands
    _, params = left.concat_using_operator(right).to_sql()
    assert params == ()


# ---------------------------------------------------------------------------
# concat_op is not the path for logical OR
# ---------------------------------------------------------------------------


def test_logical_or_does_not_go_through_concatenation(operands):
    """OR has its own node and formatter, so the two never meet."""
    left, _ = operands
    predicate = left.like("a%") | left.like("b%")
    assert not isinstance(predicate, ConcatenationOperation)
    assert " OR " in predicate.to_sql()[0]
