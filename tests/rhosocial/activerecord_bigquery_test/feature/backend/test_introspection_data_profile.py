# tests/rhosocial/activerecord_bigquery_test/feature/backend/test_introspection_data_profile.py
"""The data-profile family, measured against a reachable endpoint.

Rendering these statements proves only that they are well-formed. What needs
checking is whether BigQuery accepts them, and whether the conversions the
parser performs -- the pivot of one wide row back into a record per column, the
``null_count / row_count`` fraction, and the text-typed bounds a single-row
projection hands back -- land on values a hand count agrees with. That is only
answerable against a server, and the only endpoint reachable from this
repository is the ``goccy/bigquery-emulator`` the CI matrix starts; a real
project needs credentials this test tree does not carry, so the fixture skips
when nothing answers.

The table is a hundred rows, built so every figure is arithmetic rather than
guesswork:

    id      INT64                  i, unique             -> 100 distinct, no nulls
    code    STRING                 "a"/"b"/"c" by i % 3  -> 3 distinct, no nulls
    amount  NUMERIC                i, unique             -> 100 distinct, no nulls
    note    STRING                 "x" when i % 5 == 0, "y" when i % 5 == 1,
                                   NULL otherwise          -> 2 distinct, 60% null

The size is modest because BigQuery aggregates the rows rather than reading a
histogram, and every row of a scan is billed: the answer does not depend on a
sample being large, only on being big enough that a dropped duplicate or a
miscounted NULL would move a number off its hand-counted value.

Two shapes are specific to this backend and are pinned here. First, the profile
is answered as one wide row and pivoted by the parser: a ``UNION ALL`` would be
one billed scan per arm and would have to reconcile one type per column
position. Second, the bounds are ``STRING`` in the result -- ``CAST(MIN(col) AS
STRING)`` -- because the label that names a slot is a string and the projection
keeps one type per slot rather than per column. The figures are exact; only the
Python type is the projection's, which is why the decimal endpoints are read
back through ``int``/``Decimal``.
"""

from decimal import Decimal

import pytest

TABLE = "intro_profile_orders"
CUSTOMERS = "intro_profile_customers"
CODES = ("a", "b", "c")

ROWS = 100

#: ``note`` is NULL on 60 of the 100 rows, "x" on 20 and "y" on 20.
NULL_SHARE = 0.6


@pytest.fixture
def bigquery_backend():
    """A connected backend over the emulator, or a skip when none answers.

    The scenario loader is the repository's own (``tests/providers``), so the
    endpoint this fixture talks to is the one CI started rather than a second
    spelling of it. ``connect()`` alone proves nothing -- the client contacts
    nothing until the first statement -- so the probe is a real query.
    """
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


def _qualified(backend, table):
    """The table's name, qualified by the configured dataset when there is one."""
    dataset = getattr(backend.config, "dataset", None)
    return f"`{dataset}`.`{table}`" if dataset else f"`{table}`"


def _rows():
    rows = []
    for i in range(1, ROWS + 1):
        if i % 5 == 0:
            note = "'x'"
        elif i % 5 == 1:
            note = "'y'"
        else:
            note = "NULL"
        rows.append(f"({i}, '{CODES[i % 3]}', {i}, {note})")
    return rows


def _setup(backend):
    orders = _qualified(backend, TABLE)
    customers = _qualified(backend, CUSTOMERS)
    backend.execute(f"DROP TABLE IF EXISTS {orders}")
    backend.execute(f"DROP TABLE IF EXISTS {customers}")
    backend.execute(
        f"CREATE TABLE {orders} ("
        "id INT64 NOT NULL, code STRING NOT NULL, "
        "amount NUMERIC NOT NULL, note STRING)"
    )
    backend.execute(
        f"INSERT INTO {orders} (id, code, amount, note) VALUES "
        + ", ".join(_rows())
    )
    # The right side of every coverage measurement: four codes and one NULL.
    # The NULL is the point -- it must not be counted as a value of the domain,
    # so right coverage is 3/4 and not 3/5.
    backend.execute(f"CREATE TABLE {customers} (code INT64)")
    backend.execute(f"INSERT INTO {customers} (code) VALUES (1), (2), (3), (4), (NULL)")


def _teardown(backend):
    backend.execute(f"DROP TABLE IF EXISTS {_qualified(backend, TABLE)}")
    backend.execute(f"DROP TABLE IF EXISTS {_qualified(backend, CUSTOMERS)}")


class TestColumnDataProfile:
    """What the rows hold, counted by the server rather than read from a catalog."""

    def test_profile_matches_a_hand_count(self, bigquery_backend):
        _setup(bigquery_backend)
        try:
            profiles = {
                profile.column_name: profile
                for profile in bigquery_backend.introspector.list_column_data_profiles(
                    TABLE
                )
            }
            assert set(profiles) == {"id", "code", "amount", "note"}

            assert profiles["id"].null_fraction == 0.0
            assert profiles["id"].distinct_count == ROWS
            # The bound is a STRING in the result, because the projection has
            # one type per slot; the figure is the engine's own minimum.
            assert int(profiles["id"].min_value) == 1
            assert int(profiles["id"].max_value) == ROWS

            assert profiles["code"].null_fraction == 0.0
            assert profiles["code"].distinct_count == 3
            assert profiles["code"].min_value == "a"
            assert profiles["code"].max_value == "c"

            assert profiles["amount"].null_fraction == 0.0
            assert profiles["amount"].distinct_count == ROWS
            assert Decimal(profiles["amount"].min_value) == Decimal(1)
            assert Decimal(profiles["amount"].max_value) == Decimal(ROWS)

            # 60 of 100 rows are NULL, so a profile that dropped or clamped the
            # figure would still look plausible.
            assert profiles["note"].null_fraction == pytest.approx(NULL_SHARE)
            assert profiles["note"].distinct_count == 2
            assert profiles["note"].min_value == "x"
            assert profiles["note"].max_value == "y"
        finally:
            _teardown(bigquery_backend)

    def test_every_profile_says_it_was_aggregated(self, bigquery_backend):
        """The provenance travels in the row, not in a docstring.

        BigQuery keeps no per-column statistics catalogue, so every figure is a
        count from the rows -- exactly, not from a sample. A figure computed with
        ``APPROX_COUNT_DISTINCT`` would have to say ``sample`` here instead, and
        that distinction is why the slot exists.
        """
        _setup(bigquery_backend)
        try:
            profiles = bigquery_backend.introspector.list_column_data_profiles(TABLE)
            assert profiles
            for profile in profiles:
                assert profile.source == "aggregate"
                assert profile.row_count == ROWS
                assert profile.collected_at is None
        finally:
            _teardown(bigquery_backend)

    def test_empty_table_answers_no_fraction(self, bigquery_backend):
        """Zero rows is "not measured" for the fraction, not a fabricated zero.

        ``SUM(CASE ...)`` over no rows is NULL, so the parser has nothing to
        divide; the counts the engine can answer -- ``COUNT(*)`` and
        ``COUNT(DISTINCT ...)`` -- are real zeroes and are reported as such.
        """
        orders = _qualified(bigquery_backend, TABLE)
        bigquery_backend.execute(f"DROP TABLE IF EXISTS {orders}")
        bigquery_backend.execute(f"CREATE TABLE {orders} (id INT64)")
        try:
            profiles = {
                profile.column_name: profile
                for profile in bigquery_backend.introspector.list_column_data_profiles(
                    TABLE
                )
            }
            assert profiles["id"].row_count == 0
            assert profiles["id"].null_fraction is None
            assert profiles["id"].distinct_count == 0
            assert profiles["id"].min_value is None
        finally:
            _teardown(bigquery_backend)


class TestColumnValueSample:
    """The grouped listing, with NULL treated as a member of the domain."""

    def test_listing_is_ordered_by_frequency(self, bigquery_backend):
        _setup(bigquery_backend)
        try:
            samples = bigquery_backend.introspector.sample_column_values(
                TABLE, "code", limit=10
            )
            assert {item.value for item in samples} == set(CODES)
            # 34/33/33 by ``i % 3``, so the counts are arithmetic and the order
            # is by count first.
            assert sum(item.count for item in samples) == ROWS
            assert samples[0].count >= samples[-1].count
        finally:
            _teardown(bigquery_backend)

    def test_limit_bounds_the_listing(self, bigquery_backend):
        _setup(bigquery_backend)
        try:
            assert (
                len(
                    bigquery_backend.introspector.sample_column_values(
                        TABLE, "code", limit=2
                    )
                )
                == 2
            )
        finally:
            _teardown(bigquery_backend)

    def test_null_is_a_listed_value(self, bigquery_backend):
        """BigQuery groups NULLs, so a column holding them lists one NULL entry.

        That is the opposite of PostgreSQL, whose most-common list never holds
        NULL because the null share is a separate figure. Same question, two
        engines, two shapes -- which is exactly why a caller reads
        ``null_fraction`` rather than scanning the listing for a NULL.
        """
        _setup(bigquery_backend)
        try:
            samples = bigquery_backend.introspector.sample_column_values(
                TABLE, "note", limit=10
            )
            values = {item.value: item.count for item in samples}
            assert values[None] == 60
            assert values["x"] == 20
            assert values["y"] == 20
        finally:
            _teardown(bigquery_backend)


LEFT_TABLE = "intro_coverage_left"
RIGHT_TABLE = "intro_coverage_right"


def _coverage_setup(backend, left_values, right_values):
    """Two one-column tables, filled with the values the case was written for."""
    for table in (LEFT_TABLE, RIGHT_TABLE):
        backend.execute(f"DROP TABLE IF EXISTS {_qualified(backend, table)}")
    for table, values in ((LEFT_TABLE, left_values), (RIGHT_TABLE, right_values)):
        qualified = _qualified(backend, table)
        backend.execute(f"CREATE TABLE {qualified} (code INT64)")
        if values:
            rendered = ", ".join(
                "(NULL)" if value is None else f"({value})" for value in values
            )
            backend.execute(f"INSERT INTO {qualified} (code) VALUES {rendered}")


def _coverage_teardown(backend):
    for table in (LEFT_TABLE, RIGHT_TABLE):
        backend.execute(f"DROP TABLE IF EXISTS {_qualified(backend, table)}")


def _coverage(backend):
    return backend.introspector.estimate_join_coverage(
        LEFT_TABLE, "code", RIGHT_TABLE, "code"
    )


class TestJoinCoverage:
    """How far two columns' distinct value domains overlap.

    Every expectation is arithmetic rather than a recorded run: ``left`` has
    ``{1,2,3,4}`` and ``right`` has ``{2,3,4,5,6}``, so three of the four left
    values are matched and three of the five right ones are. The two figures are
    different on purpose -- an implementation that answered the same number
    twice, or averaged them, would still look plausible.
    """

    def test_both_fractions_match_a_hand_count(self, bigquery_backend):
        _coverage_setup(bigquery_backend, range(1, 5), range(2, 7))
        try:
            coverage = _coverage(bigquery_backend)
            assert coverage is not None
            assert coverage.left_coverage == pytest.approx(3 / 4)
            assert coverage.right_coverage == pytest.approx(3 / 5)
        finally:
            _coverage_teardown(bigquery_backend)

    def test_values_are_counted_not_rows(self, bigquery_backend):
        """A repeated key that matches once is one covered value, not three.

        The left table holds four rows but only two distinct values, and the
        repeated value is the matched one: counting rows would answer 3/4 where
        the share of values is 1/2.
        """
        _coverage_setup(bigquery_backend, (2, 2, 2, 1), (2, 3))
        try:
            coverage = _coverage(bigquery_backend)
            assert coverage is not None
            assert coverage.left_coverage == pytest.approx(1 / 2)
            assert coverage.right_coverage == pytest.approx(1 / 2)
        finally:
            _coverage_teardown(bigquery_backend)

    def test_no_overlap_is_zero_not_none(self, bigquery_backend):
        """Disjoint domains are a measurement: both sides really are uncovered.

        ``None`` means "the engine could not measure", which is a different
        answer from "nothing matched", and a caller deciding whether a join is
        worth writing has to be able to tell them apart.
        """
        _coverage_setup(bigquery_backend, (1, 2, 3), (10, 11))
        try:
            coverage = _coverage(bigquery_backend)
            assert coverage is not None
            assert coverage.left_coverage == 0.0
            assert coverage.right_coverage == 0.0
        finally:
            _coverage_teardown(bigquery_backend)

    def test_a_side_with_no_value_answers_no_fraction(self, bigquery_backend):
        """A column of nothing but NULLs has no share to report.

        NULLs are excluded from the divisors as well as the numerators, and
        ``NULLIF`` turns the empty denominator into NULL. So the left side --
        which has no value at all -- answers ``None``, while the right side,
        which has values that simply did not match, answers a real zero.
        """
        _coverage_setup(bigquery_backend, (None, None), (1, 2))
        try:
            coverage = _coverage(bigquery_backend)
            assert coverage is not None
            assert coverage.left_coverage is None
            assert coverage.right_coverage == 0.0
        finally:
            _coverage_teardown(bigquery_backend)

    def test_neither_side_having_a_value_is_no_measurement(self, bigquery_backend):
        """When both fractions are NULL the parser reports nothing measured."""
        _coverage_setup(bigquery_backend, (None,), (None,))
        try:
            assert _coverage(bigquery_backend) is None
        finally:
            _coverage_teardown(bigquery_backend)
