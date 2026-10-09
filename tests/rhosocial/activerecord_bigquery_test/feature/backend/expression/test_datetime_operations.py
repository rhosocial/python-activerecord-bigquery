# tests/rhosocial/activerecord_bigquery_test/feature/backend/expression/test_datetime_operations.py

"""BigQuery's date difference, which takes its arguments the other way round.

The core layer refuses to render a date difference on its own and tells the
dialect to implement it; BigQuery never did, so every ``date_diff`` on this
backend raised UnsupportedFeatureError for a function BigQuery has had since
2016.

Two BigQuery-specific things are easy to get wrong and are what these pin
down. ``DATE_DIFF`` takes the **end** date first, so a generic
``date_diff(unit, start, end)`` has to swap them or it measures the wrong span.
And BigQuery has no WEEK part, so a week is seven DAYs rather than a part of
its own.
"""

import pytest

from rhosocial.activerecord.backend.expression import DateTimeColumn


@pytest.fixture
def dialect():
    from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect

    return BigQueryDialect()


@pytest.fixture
def started_at(dialect):
    return DateTimeColumn(dialect, "started_at", table="t")


@pytest.fixture
def ended_at(dialect):
    return DateTimeColumn(dialect, "ended_at", table="t")


class TestDateDiffRenders:
    def test_it_renders_at_all(self, started_at, ended_at):
        """The bug: the core layer refused, so this raised for every call."""
        sql, _ = started_at.date_diff("day", ended_at).to_sql()
        assert "DATE_DIFF(" in sql

    @pytest.mark.parametrize(
        "unit,part",
        [
            ("day", "DAY"),
            ("hour", "HOUR"),
            ("minute", "MINUTE"),
            ("second", "SECOND"),
            ("month", "MONTH"),
            ("year", "YEAR"),
        ],
    )
    def test_each_part(self, started_at, ended_at, unit, part):
        sql, _ = started_at.date_diff(unit, ended_at).to_sql()
        assert part in sql

    def test_end_comes_first(self, started_at, ended_at):
        """DATE_DIFF(end, start, part) -- reversed from the generic signature."""
        sql, _ = started_at.date_diff("day", ended_at).to_sql()
        body = sql[sql.index("(") + 1:]
        assert body.index("ended_at") < body.index("started_at")

    def test_week_is_seven_days(self, started_at, ended_at):
        """BigQuery has no WEEK part, so it is spelled as DAY / 7."""
        sql, _ = started_at.date_diff("week", ended_at).to_sql()
        assert "DAY" in sql
        assert "/ 7" in sql

    def test_an_unknown_unit_is_refused_before_rendering(self, started_at):
        """The framework rejects an unknown unit at construction.

        Worth pinning because it means the formatter's own error is a
        backstop rather than the usual path: a unit the framework does not
        know never reaches BigQuery at all.
        """
        with pytest.raises(ValueError, match="unsupported interval unit"):
            started_at.date_diff("fortnight", ended_at)

    def test_every_framework_unit_has_a_bigquery_spelling(self, started_at, ended_at):
        """No unit the framework allows may be left unrendable here."""
        from rhosocial.activerecord.backend.expression.datetime import IntervalUnit

        for member in IntervalUnit:
            sql, _ = started_at.date_diff(member.value, ended_at).to_sql()
            assert "DATE_DIFF(" in sql, f"{member.value} did not render"

    def test_alias_lands_outside(self, started_at, ended_at):
        sql, _ = started_at.date_diff("day", ended_at).as_("span").to_sql()
        assert "AS" in sql.upper()