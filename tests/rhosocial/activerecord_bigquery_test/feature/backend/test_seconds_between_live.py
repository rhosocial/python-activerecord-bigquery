# tests/rhosocial/activerecord_bigquery_test/feature/backend/test_seconds_between_live.py
"""``seconds_between`` against a reachable BigQuery endpoint.

The pure-render cases pin the spelling; this file checks that the server agrees
with the meaning behind it -- that ``TIMESTAMP_DIFF(end, start, MILLISECOND)``
divided by ``1000.0`` is the signed span in seconds, not merely a well-formed
expression. Only a server can say that, and the only endpoint reachable from
this repository is the ``goccy/bigquery-emulator`` the CI matrix starts; a real
project needs credentials this test tree does not carry, so the fixture skips
when nothing answers.

Values are written as inline ``TIMESTAMP`` literals rather than bind
parameters. That keeps the case about the formatter's own SQL: no client-side
parameter conversion can change the type the server sees. The millisecond
denominator is the documented resolution of the formatter, so the fractional
cases stop at milliseconds; a sub-millisecond span is expected to lose its
remainder and is asserted only where the truncation direction is unambiguous.
"""

from datetime import datetime, timezone

import pytest

from rhosocial.activerecord.backend.expression import Literal, seconds_between


@pytest.fixture
def bigquery_backend():
    """A connected backend over the emulator, or a skip when none answers."""
    scenarios = pytest.importorskip(
        "providers.scenarios",
        reason="the scenario loader is imported with PYTHONPATH=tests",
    )
    try:
        backend_class, config = scenarios.get_scenario_raw("bigquery_emulator")
    except Exception as exc:  # noqa: BLE001 -- a missing scenario is a skip
        pytest.skip(f"no BigQuery scenario configured: {exc}")
    backend = backend_class(connection_config=config)
    try:
        backend.connect()
        backend.execute("SELECT 1")
    except Exception as exc:  # noqa: BLE001 -- an unreachable endpoint is a skip
        pytest.skip(f"no reachable BigQuery endpoint: {exc}")
    yield backend
    try:
        backend.disconnect()
    except Exception:
        pass


@pytest.fixture
def timestamp_diff_backend(bigquery_backend):
    """The reachable backend, once it has accepted ``TIMESTAMP_DIFF``.

    The emulator implements a subset of GoogleSQL. When the configured endpoint
    cannot evaluate this function there is nothing here to measure, so the case
    skips with the server's own reason instead of failing on a backend
    limitation the formatter cannot correct.
    """
    try:
        bigquery_backend.execute(
            "SELECT TIMESTAMP_DIFF("
            "TIMESTAMP '2026-01-01 00:00:01+00:00', "
            "TIMESTAMP '2026-01-01 00:00:00+00:00', MILLISECOND)"
        )
    except Exception as exc:  # noqa: BLE001 -- an engine limitation is a skip
        pytest.skip(f"the configured endpoint cannot evaluate TIMESTAMP_DIFF: {exc}")
    return bigquery_backend


def _utc(year, month, day, hour=0, minute=0, second=0, microsecond=0):
    return datetime(
        year, month, day, hour, minute, second, microsecond, tzinfo=timezone.utc
    )


def _elapsed(backend, start, end):
    """Render ``seconds_between`` inline and read the scalar it produces."""
    dialect = backend.dialect
    expr = seconds_between(
        dialect,
        Literal(dialect, start, inline=True),
        Literal(dialect, end, inline=True),
    )
    sql, params = expr.to_sql()
    assert params == ()
    result = backend.execute(f"SELECT {sql} AS elapsed")
    row = result.data[0]
    return float(row["elapsed"] if isinstance(row, dict) else row[0])


class TestSecondsBetweenLive:
    def test_positive_fractional_span(self, timestamp_diff_backend):
        value = _elapsed(
            timestamp_diff_backend,
            _utc(2026, 1, 1, 0, 0, 0),
            _utc(2026, 1, 1, 0, 0, 2, 250000),
        )
        assert value == pytest.approx(2.25, abs=0.0005)

    def test_negative_span_keeps_its_sign(self, timestamp_diff_backend):
        value = _elapsed(
            timestamp_diff_backend,
            _utc(2026, 1, 1, 0, 0, 3),
            _utc(2026, 1, 1, 0, 0, 1, 500000),
        )
        assert value == pytest.approx(-1.5, abs=0.0005)

    def test_equal_instants_are_zero(self, timestamp_diff_backend):
        value = _elapsed(
            timestamp_diff_backend,
            _utc(2026, 1, 1, 0, 0, 0),
            _utc(2026, 1, 1, 0, 0, 0),
        )
        assert value == 0.0

    def test_millisecond_resolution_is_carried(self, timestamp_diff_backend):
        value = _elapsed(
            timestamp_diff_backend,
            _utc(2026, 1, 1, 0, 0, 0),
            _utc(2026, 1, 1, 0, 0, 0, 1000),
        )
        assert value == pytest.approx(0.001, abs=0.0000005)

    def test_sub_millisecond_remainder_is_dropped(self, timestamp_diff_backend):
        """The documented limit: half a millisecond cannot reach the result."""
        value = _elapsed(
            timestamp_diff_backend,
            _utc(2026, 1, 1, 0, 0, 0),
            _utc(2026, 1, 1, 0, 0, 0, 500),
        )
        assert value == 0.0

    def test_a_cross_day_span(self, timestamp_diff_backend):
        value = _elapsed(
            timestamp_diff_backend,
            _utc(2025, 12, 31, 23, 59, 59),
            _utc(2026, 1, 1, 0, 0, 1),
        )
        assert value == pytest.approx(2.0, abs=0.0005)
