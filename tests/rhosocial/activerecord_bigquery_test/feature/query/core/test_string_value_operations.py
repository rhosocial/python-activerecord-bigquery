# tests/rhosocial/activerecord_bigquery_test/feature/query/test_string_value_operations.py
"""String value operations belong on the string column, and chain.

``StringMixin`` used to hold exactly two methods, ``like`` and ``ilike``, and
both returned a predicate. A class named ``StringColumn`` therefore offered no
string operations at all — only the ability to be LIKE-matched — while the 26
string functions that did exist sat unused in ``functions/string.py``.

The split this file pins:

- :class:`StringValueMixin` derives new strings and chains.
- :class:`StringPatternPredicateMixin` answers questions and ends the chain.
- Numeric results stay off the string surface, because ``LENGTH(x) LIKE '3'``
  is a type error in every backend.
"""

# tests/rhosocial/activerecord_bigquery_test/feature/query/test_string_value_operations.py
import pytest

from rhosocial.activerecord.backend.expression.value_types import TextValue

from rhosocial.activerecord.backend.expression import (
    LikePredicate,
    UpperFunction,
    build_json_path,
)
from rhosocial.activerecord.backend.expression import functions as string_functions

from rhosocial.activerecord_bigquery_test.feature.query.column_helpers import build_column


@pytest.fixture
def dialect():
    # The portable baseline dialect, not SQLite: what this file pins is the
    # *core* layer -- each operation reaches its factory and the result is a
    # typed string. Which spelling a given backend then writes is a per-dialect
    # question and lives in test_operation_boundaries.py, where SQLite's
    # INSTR/SUBSTR/TRUNC and its pad and repeat emulations are checked against
    # a real database.
    from rhosocial.activerecord.backend.impl.dummy.dialect import DummyDialect

    return DummyDialect()


@pytest.fixture
def name(dialect):
    return build_column(dialect, "name", str)


# ---------------------------------------------------------------------------
# The string surface exists and derives
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method, args, expected_function",
    [
        ("upper", (), "UPPER"),
        ("lower", (), "LOWER"),
        ("initcap", (), "INITCAP"),
        ("reverse", (), "REVERSE"),
        ("left", (2,), "LEFT"),
        ("right", (2,), "RIGHT"),
        ("lpad", (5,), "LPAD"),
        ("rpad", (5,), "RPAD"),
        ("repeat", (2,), "REPEAT"),
        ("trim", (), "TRIM"),
        ("substr", (1, 3), "SUBSTRING"),
        ("replace", ("a", "b"), "REPLACE"),
        ("translate", ("ab", "cd"), "TRANSLATE"),
        ("overlay", ("x", 2), "OVERLAY"),
    ],
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_string_operation_renders_its_function(
    name, method, args, expected_function
):
    """Each operation must reach the factory that already existed."""
    result = getattr(name, method)(*args)
    sql, _ = result.to_sql()
    assert expected_function in sql


def test_string_operations_return_a_typed_string_value(name):
    """The result must be a string-valued node, not a bare function call."""
    assert isinstance(name.upper(), UpperFunction)


# ---------------------------------------------------------------------------
# Chaining — the reason the result is typed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "build, expected_functions",
    [
        (lambda c: c.upper(), ["UPPER"]),
        (lambda c: c.upper().substr(1, 3), ["UPPER", "SUBSTRING"]),
        (lambda c: c.upper().left(2).lower(), ["UPPER", "LEFT", "LOWER"]),
        (lambda c: c.trim().replace("a", "b"), ["TRIM", "REPLACE"]),
        (lambda c: c.substr(1, 2).upper().lower(), ["SUBSTRING", "UPPER", "LOWER"]),
    ],
    ids=["one", "two", "three", "trim-replace", "substr-upper-lower"],
)
def test_string_operations_chain(name, build, expected_functions):
    """A derived string is still a string, so the next operation exists."""
    sql, _ = build(name).to_sql()
    for function in expected_functions:
        assert function in sql, f"{function} missing from {sql!r}"


def test_chained_result_keeps_the_whole_string_surface(name):
    """Three levels deep, the value operations are all still available."""
    result = name.upper().left(2).lower()
    for method in ("upper", "lower", "substr", "trim", "concat", "replace"):
        assert hasattr(result, method), f"chain lost {method}"


def test_chained_result_keeps_the_pattern_predicates(name):
    """String-ness is what makes LIKE legal on the result."""
    result = name.upper().left(2)
    sql, _ = result.like("A%").to_sql()
    assert "LIKE" in sql
    assert "UPPER" in sql


# ---------------------------------------------------------------------------
# Crossing into the predicate domain ends the value chain
# ---------------------------------------------------------------------------


def test_pattern_predicate_terminates_the_chain(name):
    """A predicate is a boolean; it never becomes a string again."""
    predicate = name.upper().like("A%")
    assert isinstance(predicate, LikePredicate)
    for method in ("upper", "substr", "trim", "concat"):
        assert not hasattr(predicate, method), (
            f"predicate wrongly offers {method}; the value chain should have ended"
        )


def test_predicate_still_combines(name):
    """Ending the value chain does not end the predicate chain."""
    combined = (name.like("A%") | name.like("B%")) & name.ilike("%x%")
    sql, _ = combined.to_sql()
    assert " OR " in sql and " AND " in sql


# ---------------------------------------------------------------------------
# Numeric results are not on the string surface
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "factory", ["length", "ascii", "octet_length", "bit_length"]
)
def test_numeric_result_is_not_a_string_value(dialect, name, factory):
    """``LENGTH(x) LIKE '3'`` is a type error; the surface must not offer it."""
    result = getattr(string_functions, factory)(dialect, name)
    assert not isinstance(result, TextValue)


@pytest.mark.parametrize(
    "method, args",
    [("length", ()), ("ascii", ()), ("strpos", ("x",)), ("position", ("x",))],
)
def test_string_column_offers_them_but_the_result_is_not_a_string(name, method, args):
    """A legal string operation whose *result* is a number.

    ``LENGTH(s) LIKE '3'`` is still a type error, but it is caught by the
    result's type rather than by hiding the method. Hiding it would be wrong:
    these are well-defined on every backend, and ``strpos`` and ``position``
    differ in availability, so "does a string offer it" is not the same
    question as "is the answer a string".
    """
    assert hasattr(name, method), f"StringColumn lost a legal operation {method}()"
    result = getattr(name, method)(*args)
    assert not isinstance(result, TextValue)


# ---------------------------------------------------------------------------
# Existing behaviour is preserved
# ---------------------------------------------------------------------------


def test_free_functions_still_work_and_are_now_typed(dialect, name):
    """Existing call sites keep working; they gain a string-valued node."""
    result = string_functions.upper(dialect, name)
    assert isinstance(result, UpperFunction)
    assert result.like("A%").to_sql()[0].endswith("LIKE ?")


def test_concat_includes_the_receiver(dialect, name):
    """A variadic factory must receive the column as an operand.

    Passing the operand list as a single argument would bind the whole list to
    one placeholder, which is what an earlier version of the mixin did.
    """
    other = build_column(dialect, "other", str)
    sql, params = name.concat(other, "x").to_sql()
    assert sql.count("?") == 1
    assert params == ("x",)
    assert '"other"' in sql


def test_json_path_builder_is_untouched():
    """The integer-index rule is a separate concern and must not regress."""
    assert build_json_path("tags", 0) == "$.tags[0]"
    assert build_json_path("tags", "0") == "$.tags.0"
