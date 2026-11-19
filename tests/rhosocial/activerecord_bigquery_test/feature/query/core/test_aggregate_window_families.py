# tests/rhosocial/activerecord_bigquery_test/feature/query/test_aggregate_window_families.py
"""What aggregating and windowing a value gives back.

Each aggregate is its own node class now, so the identity of the function
travels on the node instead of inside a generic name string: COUNT is a
CountFunction, SUM a SumFunction, and so on. A count is a whole number however
wide the thing counted is; an average is numeric whatever it averages; MIN and
MAX hand back something of the operand's kind, which the node cannot know, so
they offer only the operations every value has.

A window function is either a count or a value from another row, and confusing
the two is how a name column ends up arithmetic. ROW_NUMBER counts; LAG
borrows.
"""

# tests/rhosocial/activerecord_bigquery_test/feature/query/test_aggregate_window_families.py
import pytest

from rhosocial.activerecord.backend.expression.declared import (
    IntegerAnnotation,
    NumberAnnotation,
    TextAnnotation,
)
from rhosocial.activerecord.backend.expression import (
    AvgFunction,
    CountFunction,
    FunctionCall,
    MaxFunction,
    MinFunction,
    SumFunction,
)
from rhosocial.activerecord.backend.expression.value_types import (
    ArrayValue,
    BooleanValue,
    JSONValue,
    NumericValue,
    OpaqueValue,
    TemporalValue,
    TextValue,
)
from rhosocial.activerecord.backend.expression import functions as F


@pytest.fixture
def dialect():
    from rhosocial.activerecord.backend.impl.sqlite.dialect import SQLiteDialect

    d = SQLiteDialect()
    d._version = (3, 46, 1)
    return d


@pytest.fixture
def columns(dialect):
    from rhosocial.activerecord_bigquery_test.feature.query.column_helpers import build_column

    return {
        "int": build_column(dialect, "i", int),
        "float": build_column(dialect, "f", float),
        "str": build_column(dialect, "s", str),
        "json": build_column(dialect, "j", dict),
    }


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------


def test_count_is_always_a_whole_number(dialect, columns):
    """However wide the thing counted, the answer is a number of rows."""
    for column in columns.values():
        assert isinstance(F.count(dialect, column), CountFunction)


def test_count_takes_arithmetic_and_not_string_operations(dialect, columns):
    count = F.count(dialect, columns["int"])
    assert hasattr(count, "__add__")
    assert not hasattr(count, "upper")


# ---------------------------------------------------------------------------
# Averaging widens
# ---------------------------------------------------------------------------


def test_avg_is_numeric_whatever_it_averages(dialect, columns):
    """Averaging whole numbers gives a fraction, so the family has to allow
    one. SQL Server is the exception that returns an integer here, which is
    exactly why it is not something to build an operation surface on."""
    for column in columns.values():
        assert isinstance(F.avg(dialect, column), AvgFunction)


# ---------------------------------------------------------------------------
# Adding, minimising and maximising are their own node classes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "factory, node_class",
    [("sum_", SumFunction), ("min_", MinFunction), ("max_", MaxFunction)],
)
def test_a_reduction_is_its_own_node_class(dialect, columns, factory, node_class):
    """The reduction's identity is the node class, not a name string.

    SUM / MIN / MAX used to be guessed into a value family from the operand's
    column class; now each is its own node, and the operand kind does not
    change which node comes back.
    """
    reduce_it = getattr(F, factory)
    for column in columns.values():
        assert isinstance(reduce_it(dialect, column), node_class)


@pytest.mark.parametrize(
    "factory, node_class",
    [("sum_", SumFunction), ("min_", MinFunction), ("max_", MaxFunction)],
)
def test_a_literal_input_is_still_the_classed_node(dialect, factory, node_class):
    """A literal operand does not change which node comes back.

    The reduction is classed by the function, not inferred from the operand
    kind, so a literal -- which declares no kind -- yields the same node a
    column would.
    """
    result = getattr(F, factory)(dialect, 1)
    assert isinstance(result, node_class)


def test_min_does_not_guess_the_operand_family(dialect, columns):
    """MIN hands back something of the operand's kind, which the node cannot
    know, so it offers only the operations every value has rather than
    guessing a family from the operand."""
    result = F.min_(dialect, columns["str"])
    assert isinstance(result, MinFunction)
    assert not isinstance(result, (NumberAnnotation, TextAnnotation))
    assert hasattr(result, "is_null")


# ---------------------------------------------------------------------------
# Building a document or a sequence
# ---------------------------------------------------------------------------


def test_building_a_json_aggregate_gives_json(dialect, columns):
    assert isinstance(F.json_objectagg(dialect, columns["int"], columns["str"]), JSONValue)
    assert isinstance(F.json_arrayagg(dialect, columns["json"]), JSONValue)


def test_collecting_into_an_array_gives_an_array(dialect, columns):
    assert isinstance(F.array_agg(dialect, columns["int"]), ArrayValue)


# ---------------------------------------------------------------------------
# Windowing: a count, or a value from another row
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("factory", ["row_number", "rank", "dense_rank"])
def test_a_rank_is_a_whole_number(dialect, factory):
    for windowed in (getattr(F, factory)(dialect),):
        assert isinstance(windowed, NumericValue)
        assert hasattr(windowed, "__add__")
        assert not hasattr(windowed, "upper")


@pytest.mark.parametrize(
    "factory, extra",
    [("lag", ()), ("lead", ()), ("first_value", ()), ("last_value", ()), ("nth_value", (2,))],
)
def test_a_value_from_another_row_keeps_its_family(dialect, columns, factory, extra):
    """LAG over a name column is a name, not a count.

    Which is asserted by the arithmetic that is *absent*: a name is not a
    number, so no ``sqrt``. The string operations are present, because the
    result genuinely is a string -- it was ``not hasattr(windowed, "upper")``
    before the class replaced the tag, and that assertion is what the tag was
    costing: the node carried ``family="string"`` while offering none of the
    string surface, so a caller could not tell from the object which operations
    it had. Now the class says it, and the operations come with it.
    """
    windowed = getattr(F, factory)(dialect, columns["str"], *extra)
    assert isinstance(windowed, TextAnnotation)
    assert hasattr(windowed, "like")
    assert not hasattr(windowed, "sqrt")


def test_lag_over_a_float_column_is_fractional(dialect, columns):
    assert isinstance(F.lag(dialect, columns["float"]), NumberAnnotation)


# ---------------------------------------------------------------------------
# The node states its family, and the round trip survives it
# ---------------------------------------------------------------------------


def test_a_typed_aggregate_reports_its_family_for_introspection(dialect, columns):
    """Introspection has to see what a result is, or nothing downstream can
    read it.

    It used to read ``get_params()["family"]``. That keyword is gone: it
    duplicated the class, and a tag that can disagree with the class it sits on
    is worse than no tag at all. The class is the introspection surface now, so
    this asserts the class -- which is what a caller would have branched on
    anyway.
    """
    result = F.count(dialect, columns["int"])
    assert isinstance(result, CountFunction)


def test_a_typed_window_reports_its_family_for_introspection(dialect, columns):
    """Same for a window function: the class, not the removed ``family`` tag."""
    result = F.lag(dialect, columns["int"])
    assert isinstance(result, IntegerAnnotation)


def test_an_untyped_aggregate_reports_no_family(dialect, columns):
    """A node constructed directly is the untyped one, and says so by being it.

    ``get_params()["family"] is None`` was how this used to be checked. There is
    no ``family`` parameter to be ``None`` now, so the assertion is the class:
    a bare ``FunctionCall`` is not a typed value, which is the same
    statement without the tag that could contradict it.
    """
    result = FunctionCall(dialect, "COUNT", columns["int"], is_aggregate=True)
    assert not isinstance(
        result,
        (
            ArrayValue,
            BooleanValue,
            JSONValue,
            NumericValue,
            OpaqueValue,
            TemporalValue,
            TextValue,
        ),
    )
def test_declaring_a_family_does_not_change_the_sql(dialect, columns):
    """Typing is a surface decision, never a rendering one."""
    assert F.count(dialect, columns["int"]).to_sql()[0] == "COUNT(\"i\")"
    assert F.lag(dialect, columns["int"]).to_sql()[0] == "LAG(\"i\", ?)"
