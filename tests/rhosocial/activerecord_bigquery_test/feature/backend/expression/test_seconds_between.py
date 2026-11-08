# tests/rhosocial/activerecord_bigquery_test/feature/backend/expression/test_seconds_between.py
"""``seconds_between`` on BigQuery: signed seconds from ``TIMESTAMP_DIFF``.

The core node asks one question -- ``end - start`` in seconds, signed and
fractional -- and leaves the spelling to the dialect. BigQuery answers it with
``TIMESTAMP_DIFF(end, start, MILLISECOND) / 1000.0``: the count is whole
milliseconds, the division turns it into seconds, and the sign rides on the
count because the end instant is counted from the start.

Two things are specific to this backend and are what these cases pin down.
``TIMESTAMP_DIFF`` takes the **end** instant first, so a generic ``start, end``
pair has to be swapped or every result has the wrong sign. And the only
fraction the spelling can carry is the millisecond one: ``TIMESTAMP_DIFF``
counts whole units, so a sub-millisecond remainder is dropped -- a limit
documented on the formatter and in the feature page.
"""

import pytest

from rhosocial.activerecord.backend.expression import (
    Literal,
    SecondsBetweenExpression,
    seconds_between,
)
from rhosocial.activerecord.backend.expression.column_types import TimestampColumn
from rhosocial.activerecord.backend.expression.value_types import NumericValue


@pytest.fixture
def dialect():
    from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect

    return BigQueryDialect()


@pytest.fixture
def started_at(dialect):
    return TimestampColumn(dialect, "started_at")


@pytest.fixture
def ended_at(dialect):
    return TimestampColumn(dialect, "ended_at")


class TestSecondsBetweenRendering:
    def test_exact_sql(self, dialect, started_at, ended_at):
        """The whole spelling, rather than a substring that a wrong form passes."""
        sql, params = seconds_between(dialect, started_at, ended_at).to_sql()
        assert sql == "TIMESTAMP_DIFF(`ended_at`, `started_at`, MILLISECOND) / 1000.0"
        assert params == ()

    def test_end_is_counted_first(self, started_at, ended_at):
        """TIMESTAMP_DIFF(end, start, part) -- reversed from the generic call."""
        sql, _ = seconds_between(started_at.dialect, started_at, ended_at).to_sql()
        assert sql.index("`ended_at`") < sql.index("`started_at`")

    def test_swapping_the_operands_swaps_the_arguments(self, started_at, ended_at):
        """The sign is the argument order, so a reversal must move both names."""
        forward, _ = seconds_between(started_at.dialect, started_at, ended_at).to_sql()
        backward, _ = seconds_between(started_at.dialect, ended_at, started_at).to_sql()
        assert forward == "TIMESTAMP_DIFF(`ended_at`, `started_at`, MILLISECOND) / 1000.0"
        assert backward == "TIMESTAMP_DIFF(`started_at`, `ended_at`, MILLISECOND) / 1000.0"

    def test_milliseconds_are_turned_into_seconds(self, started_at, ended_at):
        """The denominator is what makes the answer fractional, not whole."""
        sql, _ = seconds_between(started_at.dialect, started_at, ended_at).to_sql()
        assert "MILLISECOND" in sql
        assert "/ 1000.0" in sql
        assert ", SECOND)" not in sql

    def test_it_is_a_fractional_number(self, dialect, started_at, ended_at):
        expr = seconds_between(dialect, started_at, ended_at)
        assert isinstance(expr, SecondsBetweenExpression)
        assert isinstance(expr, NumericValue)
        assert expr.format_method == "format_seconds_between_expression"

    def test_factory_coerces_string_to_column(self, dialect):
        expr = seconds_between(dialect, "started_at", "ended_at")
        sql, params = expr.to_sql()
        assert sql == "TIMESTAMP_DIFF(`ended_at`, `started_at`, MILLISECOND) / 1000.0"
        assert params == ()

    def test_column_method(self, started_at, ended_at):
        sql, params = started_at.seconds_between(ended_at).to_sql()
        assert sql == "TIMESTAMP_DIFF(`ended_at`, `started_at`, MILLISECOND) / 1000.0"
        assert params == ()

    def test_bind_parameters_follow_sql_order(self, dialect):
        """``end`` is written first, so its bind parameter is also first."""
        start = Literal(dialect, "2026-01-01T00:00:00+00:00")
        end = Literal(dialect, "2026-01-01T00:00:02.500+00:00")
        sql, params = seconds_between(dialect, start, end).to_sql()
        assert sql == "TIMESTAMP_DIFF(?, ?, MILLISECOND) / 1000.0"
        assert params == (
            "2026-01-01T00:00:02.500+00:00",
            "2026-01-01T00:00:00+00:00",
        )

    def test_alias_lands_outside(self, dialect, started_at, ended_at):
        sql, params = seconds_between(dialect, started_at, ended_at).as_("elapsed").to_sql()
        assert sql == (
            "TIMESTAMP_DIFF(`ended_at`, `started_at`, MILLISECOND) / 1000.0 "
            "AS `elapsed`"
        )
        assert params == ()
