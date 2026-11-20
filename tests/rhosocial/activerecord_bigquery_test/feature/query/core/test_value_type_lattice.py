# tests/rhosocial/activerecord_bigquery_test/feature/query/test_value_type_lattice.py
"""Every operation declares a result type, and the type gates the next operation.

The rule this file pins: an operation's result determines which operations are
available next. ``upper()`` returns a string, so ``substr()`` follows.
``length()`` is a legal string operation whose result is a *number*, so
``upper()`` does not — and that falls out of the types rather than out of a
check somewhere.

The two halves that are easy to get wrong are both pinned here: a result must
not lose its own surface, and it must not gain a surface belonging to another
family.
"""

# tests/rhosocial/activerecord_bigquery_test/feature/query/test_value_type_lattice.py
import pytest

from rhosocial.activerecord.backend.expression import (
    CharLengthFunction,
)


@pytest.fixture
def dialect():
    # The portable baseline: this file pins result *types* and the core
    # spellings. Which spelling a backend writes is checked in
    # test_operation_boundaries.py, against SQLite and a real database.
    from rhosocial.activerecord.backend.impl.dummy.dialect import DummyDialect

    return DummyDialect()


@pytest.fixture
def name(dialect):
    from rhosocial.activerecord_bigquery_test.feature.query.column_helpers import build_column

    return build_column(dialect, "name", str)


# ---------------------------------------------------------------------------
# A string operation whose result is a number
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method, args, function",
    [
        ("length", (), "LENGTH"),
        ("ascii", (), "ASCII"),
        ("octet_length", (), "OCTET_LENGTH"),
        ("bit_length", (), "BIT_LENGTH"),
        ("strpos", ("a",), "STRPOS"),
        ("position", ("a",), "POSITION"),
    ],
    ids=["length", "ascii", "octet_length", "bit_length", "strpos", "position"],
)
def test_number_returning_operation_yields_an_integer(name, method, args, function):
    """These read a string and produce a count or a code.

    Each is now a node of its own -- ``CharLengthFunction``,
    ``AsciiFunction``, ``OctetLengthFunction``, ``BitLengthFunction``,
    ``PositionExpression`` -- so what the six share is asserted as the
    **surface** rather than as a class: arithmetic is available and the string
    surface is not. Asserting ``isinstance(result, IntegerAnnotation)`` would pin
    the wrapper these operations used to be returned in, which is exactly what
    the per-function classes removed.
    """
    result = getattr(name, method)(*args)
    assert hasattr(result, "__add__")
    assert not hasattr(result, "upper")
    assert function in result.to_sql()[0]


def test_the_whole_string_surface_offers_them(name):
    """They are string operations, so they belong on the string surface.

    Their absence earlier was a gap in the surface, not a rule that only
    string-to-string operations exist.
    """
    for method in ("length", "ascii", "strpos", "position", "octet_length", "bit_length"):
        assert hasattr(name, method), f"StringColumn is missing {method}"


# ---------------------------------------------------------------------------
# The result type gates the next operation
# ---------------------------------------------------------------------------


#: How many arguments each string operation *requires*, so the parametrized
#: test can call them all the same way. `substr` also takes an optional length
#: and `trim` optional characters and a direction; passing the minimum is
#: enough to reach the return, which is what is under test here.
#:
#: The placeholders are typed, not a repeated ``"x"``. Positions and counts are
#: integers and text operands are strings, and a call that got them wrong used
#: to pass silently -- a literal carrier accepted any value -- which is how
#: ``substr("x")`` came to mean "substring starting one character in" nowhere.
#: The typed value nodes now refuse it, which is the point of them.
_REQUIRED_ARGS = {
    "upper": [], "lower": [], "trim": [], "initcap": [],
    "substr": [1], "left": [1], "right": [1],
    "concat": ["x"],
    "replace": ["a", "b"],
}


def _call(name, method):
    return getattr(name, method)(*_REQUIRED_ARGS[method])


@pytest.mark.parametrize(
    "method", ["upper", "lower", "substr", "trim", "concat", "replace", "left", "initcap"]
)
def test_string_result_keeps_the_string_surface(name, method):
    """The result is a string and *says* so by offering the next operation.

    What is asserted is the surface, not one class: most of these return a
    StringValue, but a node with its own dialect hook -- TRIM, whose
    standard spelling is a syntax error on SQLite -- is its own class and
    carries the same mixins, which is what makes ``col.trim().upper()`` legal.
    """
    result = _call(name, method)
    assert hasattr(result, "upper"), f"{method} did not return a string value"
    assert hasattr(result, "substr"), f"{method} did not return a string value"


@pytest.mark.parametrize(
    "chained, expected_functions",
    [
        (lambda c: c.upper().substr(1, 3), ["UPPER", "SUBSTRING"]),
        (lambda c: c.trim().replace("a", "b"), ["TRIM", "REPLACE"]),
        (lambda c: c.upper().lower().initcap(), ["UPPER", "LOWER", "INITCAP"]),
    ],
    ids=["upper-substr", "trim-replace", "case-chain"],
)
def test_string_chain_stays_string(name, chained, expected_functions):
    sql, _ = chained(name).to_sql()
    for function in expected_functions:
        assert function in sql


def test_number_result_loses_the_string_surface(name):
    """A length has no case, so ``upper()`` must not exist on it."""
    result = name.length()
    for method in ("upper", "lower", "substr", "trim", "initcap", "reverse"):
        assert not hasattr(result, method), (
            f"an integer result wrongly offers {method}"
        )


def test_number_result_keeps_integer_operations(name):
    """Arithmetic is legal on an integer, and stays an integer."""
    result = name.length()
    assert hasattr(result, "__add__")
    assert hasattr(result, "__sub__")
    assert hasattr(result, "__mul__")


# ---------------------------------------------------------------------------
# The chain crosses families correctly
# ---------------------------------------------------------------------------


def test_string_then_number(name):
    """upper() is a string, length() of it is a number."""
    result = name.upper().length()
    assert isinstance(result, CharLengthFunction)
    assert "LENGTH" in result.to_sql()[0] and "UPPER" in result.to_sql()[0]


def test_number_comparison_chains(name):
    sql, _ = (name.length() > 5).to_sql()
    assert "LENGTH" in sql and ">" in sql


def test_arithmetic_on_a_number_result(name):
    """``length + 1`` is an arithmetic expression over an integer value."""
    sql, params = (name.length() + 1).to_sql()
    assert "LENGTH" in sql
    assert params == (1,)


def test_a_number_result_can_be_compared_but_not_matched(name):
    """Comparison is universal; ``LIKE`` is not.

    Every value can be compared, so ``length() > 5`` is offered. ``LIKE`` is
    text matching and a whole number is not text, so the operation is not
    offered — it fails here, at the point of the call, rather than at the
    database. This used to be the other way round and the reason the typed
    column classes exist at all.
    """
    result = name.length()
    assert " > " in (result > 0).to_sql()[0]
    with pytest.raises(AttributeError):
        result.like("1%")


# ---------------------------------------------------------------------------
# Crossing into a predicate ends the value chain
# ---------------------------------------------------------------------------


def test_predicate_ends_the_chain(name):
    """A predicate is the end of the value chain whatever produced it."""
    predicate = name.upper().like("A%")
    for method in ("upper", "length", "substr"):
        assert not hasattr(predicate, method), (
            f"predicate wrongly offers {method}; the value chain should have ended"
        )


def test_integer_value_can_be_aliased(name):
    sql, _ = name.length().as_("n").to_sql()
    assert " AS " in sql
