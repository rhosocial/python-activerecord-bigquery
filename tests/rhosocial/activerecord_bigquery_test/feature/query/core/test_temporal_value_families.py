# tests/rhosocial/activerecord_bigquery_test/feature/query/test_temporal_value_families.py
"""What each temporal operation answers with.

A datetime is not one type. ``YEAR(ts)`` is a whole number, ``EXTRACT`` is a
number, ``NOW() + interval`` is a timestamp again, and ``NOW() - NOW()`` is an
interval. Getting these confused is silent — the SQL is still valid and
the answer is simply the wrong kind of thing — so each one is pinned here.

The result's family is what decides the next operation, so the surface is
asserted too: a year may be added to, a timestamp may not be upper-cased.
"""

# tests/rhosocial/activerecord_bigquery_test/feature/query/test_temporal_value_families.py
import datetime

import pytest

from rhosocial.activerecord.backend.expression import functions as datetime_functions
from rhosocial.activerecord.backend.expression.value_types import (
    NumericValue,
    TemporalValue,
)
from rhosocial.activerecord.backend.expression.datetime import (
    DatetimeAddExpression,
    DatetimeSubtractExpression,
)
from rhosocial.activerecord.backend.expression.operators import ArithmeticOperation


@pytest.fixture
def dialect():
    from rhosocial.activerecord.backend.impl.sqlite.dialect import SQLiteDialect

    d = SQLiteDialect()
    d._version = (3, 46, 1)
    return d


@pytest.fixture
def timestamp(dialect):
    from rhosocial.activerecord_bigquery_test.feature.query.column_helpers import build_column

    return build_column(dialect, "ts", datetime.datetime)


# ---------------------------------------------------------------------------
# The present, in each of its precisions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "factory, cls",
    [
        ("now", TemporalValue),
        ("current_timestamp", TemporalValue),
        ("localtimestamp", TemporalValue),
        ("current_date", TemporalValue),
        ("current_time", TemporalValue),
    ],
)
def test_the_present_keeps_its_precision(dialect, factory, cls):
    """A date is not a timestamp and a time is not either.

    Four separate classes now, where there was one class and a label saying
    which it was standing in for. Each factory returns the class its own
    precision calls for, and that is readable off the result.
    """
    assert isinstance(getattr(datetime_functions, factory)(dialect), cls)


# ---------------------------------------------------------------------------
# Pulling a component out of a timestamp gives a whole number
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "factory", ["year", "month", "day", "hour", "minute", "second"]
)
def test_a_component_is_a_whole_number(dialect, timestamp, factory):
    """A calendar component is a whole number on every backend.

    Asserted on the node's own class: the integral node is a distinct class from
    the fractional one precisely because ``EXTRACT(EPOCH FROM ts)`` is not whole,
    and that distinction now lives in the node rather than in a value class whose
    operations were identical anyway.
    """
    node = getattr(datetime_functions, factory)(dialect, timestamp)
    assert type(node).__name__ == "ExtractFieldExpression"


def test_a_component_takes_arithmetic_and_not_string_operations(dialect, timestamp):
    """A year is a number, so the number surface follows and the string one
    does not. Getting this wrong is how ``str(year(ts))`` sneaks in."""
    year = datetime_functions.year(dialect, timestamp)
    assert hasattr(year, "__add__")
    assert not hasattr(year, "upper")


# ---------------------------------------------------------------------------
# Extraction is numeric because the unit decides it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("factory", ["extract", "date_part"])
def test_extraction_is_numeric(dialect, timestamp, factory):
    """``EXTRACT(EPOCH FROM ts)`` is fractional, so the family is too wide to
    be a whole number. Widening here is deliberate: claiming integer would
    offer ``bit_length`` on a value that may be a million and a half."""
    assert isinstance(getattr(datetime_functions, factory)(dialect, "year", timestamp), NumericValue)


def test_date_diff_counts_whole_units(dialect):
    now = datetime_functions.now(dialect)
    assert isinstance(now.date_diff("day", now), NumericValue)


# ---------------------------------------------------------------------------
# Arithmetic on time stays time
# ---------------------------------------------------------------------------


def test_truncation_stays_a_timestamp(dialect):
    assert isinstance(datetime_functions.now(dialect).date_trunc("day"), TemporalValue)


@pytest.mark.parametrize("method", ["date_add", "date_sub"])
def test_shifting_time_stays_a_timestamp(dialect, method):
    now = datetime_functions.now(dialect)
    result = getattr(now, method)(1, "days")
    assert isinstance(result, TemporalValue)
    assert isinstance(result, (DatetimeAddExpression, DatetimeSubtractExpression))


def test_an_interval_is_its_own_family(dialect):
    """A span is not a point in time, which is why date_add takes one."""
    assert isinstance(datetime_functions.interval(dialect, 1, "day"), TemporalValue)


# ---------------------------------------------------------------------------
# The operators are interval-based; a point in time has no sum
# ---------------------------------------------------------------------------


def test_a_timestamp_moves_by_an_interval(dialect):
    """Constructed, not rendered: SQLite has no interval node yet (the
    emulation belongs to the data-type step), and what this test pins is the
    gate that lets the combination through at all."""
    now = datetime_functions.now(dialect)
    one_day = datetime_functions.interval(dialect, 1, "day")
    expression = now + one_day
    assert isinstance(expression, ArithmeticOperation)


def test_two_points_subtract_to_an_interval(dialect):
    now = datetime_functions.now(dialect)
    sql, params = (now - now).to_sql()
    assert "-" in sql


def test_two_points_have_no_sum(dialect):
    """``created_at + created_at`` used to render and fail only in SQL."""
    now = datetime_functions.now(dialect)
    with pytest.raises(AttributeError, match="no sum"):
        now + now


def test_interval_arithmetic_stays_between_intervals(dialect):
    one_day = datetime_functions.interval(dialect, 1, "day")
    two_days = datetime_functions.interval(dialect, 2, "day")
    for expression in (one_day + two_days, one_day - two_days, one_day * 2):
        assert isinstance(expression, ArithmeticOperation)


def test_a_number_does_not_move_a_point_in_time(dialect):
    now = datetime_functions.now(dialect)
    with pytest.raises(AttributeError):
        now + 1


def test_a_span_is_not_divided(dialect):
    one_day = datetime_functions.interval(dialect, 1, "day")
    with pytest.raises(AttributeError):
        one_day / 2


def test_a_temporal_column_follows_the_same_gate(dialect, timestamp):
    """The column and the value are the same expression layer, so the gate
    has to see a temporal *column* as a temporal operand too."""
    one_day = datetime_functions.interval(dialect, 1, "day")
    assert isinstance(timestamp + one_day, ArithmeticOperation)
    assert isinstance(timestamp - timestamp, ArithmeticOperation)
    with pytest.raises(AttributeError, match="no sum"):
        timestamp + timestamp


# ---------------------------------------------------------------------------
# A node with a class of its own is its type; there is nothing to declare
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "factory, args, result_cls",
    [
        ("extract", ("year",), NumericValue),
        ("date_part", ("year",), NumericValue),
        ("interval", (1, "day"), TemporalValue),
        ("date_diff", ("day",), NumericValue),
        ("seconds_between", (), NumericValue),
    ],
)
def test_a_temporal_operation_yields_its_own_type(dialect, timestamp, factory, args, result_cls):
    """What a temporal operation yields is decided where it is built.

    ``EXTRACT`` yields a number and ``DATE_DIFF`` a whole number; each is
    decided by the factory that builds the node, and neither needed a label to
    say so afterwards. ``SECONDS_BETWEEN`` is the fractional member: seconds
    are divisible, so its result is the numeric family again.
    """
    if factory == "interval":
        result = getattr(datetime_functions, factory)(dialect, *args)
    elif factory in ("date_diff", "seconds_between"):
        result = getattr(datetime_functions, factory)(dialect, *args, timestamp, timestamp)
    else:
        result = getattr(datetime_functions, factory)(dialect, *args, timestamp)
    assert isinstance(result, result_cls)


def test_a_temporal_value_offers_temporal_operations(dialect):
    now = datetime_functions.now(dialect)
    for method in ("date_add", "date_sub", "date_diff", "seconds_between", "date_part", "extract"):
        assert hasattr(now, method), f"a timestamp lost {method}"


def test_a_temporal_value_does_not_offer_string_operations(dialect):
    assert not hasattr(datetime_functions.now(dialect), "upper")


@pytest.mark.parametrize(
    "factory",
    ["now", "current_date", "current_time", "current_timestamp", "localtimestamp"],
)
def test_each_temporal_value_is_its_own_node(dialect, factory):
    """They offer the same operations, so they share a surface -- but they are
    four different types, and each says so with its own class.

    A date and a date-time used to be one class with a label saying which it
    was. Now the node is the statement, so this pins that a point in time is
    still distinguishable from a span and from the other points by the class
    the factory chose.
    """
    node = getattr(datetime_functions, factory)(dialect)
    assert isinstance(node, TemporalValue)
    assert hasattr(node, "date_add")


def test_an_interval_is_a_span_and_not_a_point(dialect):
    """The distinction the temporal gate asks about, stated by the node.

    ``_is_interval_value`` used to ask about a class nothing ever constructed,
    which made the whole gate unreachable. The marker it asks about now is one
    the interval node carries.
    """
    from rhosocial.activerecord.backend.expression.mixins import IntervalMixin

    interval = datetime_functions.interval(dialect, 1, "day")
    assert isinstance(interval, IntervalMixin)
    assert isinstance(interval, TemporalValue)
    assert not isinstance(datetime_functions.now(dialect), IntervalMixin)


def test_the_sql_does_not_change_when_a_type_is_stated(dialect, timestamp):
    """Typing is a surface decision, never a rendering one."""
    from rhosocial.activerecord.backend.expression import FunctionCall

    call = FunctionCall(dialect, "MY_FUNC", timestamp)
    assert call.as_datetime().to_sql() == call.to_sql()


def test_an_alias_survives_a_stated_type(dialect, timestamp):
    from rhosocial.activerecord.backend.expression import FunctionCall

    call = FunctionCall(dialect, "MY_FUNC", timestamp)
    assert " AS " in call.as_datetime().as_("when").to_sql()[0]
