# tests/rhosocial/activerecord_bigquery_test/feature/query/bigquery/test_bigquery_explain_deep.py
"""Backend-local, deep EXPLAIN tests for BigQuery.

The shared testsuite contracts only assert that EXPLAIN *can run*.  BigQuery is
an honest "no": both ``supports_explain()`` and ``supports_explain_plan()`` are
``False``, and the dialect inherits the generic ``ExplainMixin`` renderer rather
than a GoogleSQL-specific one.  This file pins two things the testsuite cannot:

* **capability gates** -- BigQuery refuses EXPLAIN, so a real-DB plan-reading
  test is gated off and skipped with the reason, never faked with assertions on
  a plan the emulator will not produce;
* **construction-level rendering** -- the inherited generic formatter renders a
  PostgreSQL-shaped ``EXPLAIN ...`` for every option combination, which is the
  exact fallback text emitted if the capability gate were bypassed.  Pinning it
  documents its option handling without needing a live database.

There is no async variant: rendering is a synchronous, dialect-level operation,
identical for the sync and the native-async BigQuery backend.
"""

from typing import Optional, Tuple

import pytest
from rhosocial.activerecord.backend.expression import Literal
from rhosocial.activerecord.backend.expression.objects import Table
from rhosocial.activerecord.backend.expression.sources import NamedRelationRef
from rhosocial.activerecord.backend.expression.statements import (
    ExplainFormat,
    ExplainOptions,
    ExplainStatement,
    ExplainType,
    QueryStatement,
)

from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect

_DATASET = "test_explain"
_BASE_SQL = f"SELECT ? FROM `{_DATASET}`.`users`"


def _dialect() -> BigQueryDialect:
    """A dialect with a default dataset, so rendered relations are qualified."""
    return BigQueryDialect(version=(3, 0, 0), default_dataset=_DATASET)


def _render(
    dialect: BigQueryDialect, options: Optional[ExplainOptions] = None
) -> Tuple[str, tuple]:
    """Render an ``EXPLAIN SELECT ...`` statement with the given options."""
    query = QueryStatement(
        dialect=dialect,
        select=[Literal(dialect, "*")],
        from_=NamedRelationRef(dialect, Table(dialect, "users")),
    )
    expr = ExplainStatement(dialect, statement=query, options=options)
    return dialect.format_explain_statement(expr)


class TestBigQueryExplainCapabilities:
    """BigQuery honestly declines EXPLAIN at the capability level."""

    def test_explain_and_explain_plan_unsupported(self):
        """Both the statement and plan gates are False -- no EXPLAIN at all."""
        dialect = _dialect()
        assert dialect.supports_explain() is False
        assert dialect.supports_explain_plan() is False

    def test_explain_option_probes_unsupported(self):
        """No ANALYZE and no FORMAT variant is advertised as supported."""
        dialect = _dialect()
        assert dialect.supports_explain_analyze() is False
        for fmt in ExplainFormat:
            assert dialect.supports_explain_format(fmt.value) is False, fmt.value


class TestBigQueryExplainRendering:
    """The inherited generic renderer's SQL, option by option.

    These are construction-level: they never touch the emulator.  Because the
    capability gates are False, this text is a documented fallback, not a claim
    that BigQuery executes it.
    """

    def test_basic_explain_without_options(self):
        """With no options the renderer emits a plain ``EXPLAIN SELECT ...``."""
        sql, params = _render(_dialect())
        assert sql == f"EXPLAIN {_BASE_SQL}"
        assert params == ("*",), "wrapped statement's parameters must pass through"

    def test_empty_options_same_as_none(self):
        """An all-default ``ExplainOptions`` renders identically to no options."""
        assert _render(_dialect(), ExplainOptions()) == _render(_dialect())

    def test_analyze_via_flag_or_type(self):
        """``analyze=True`` and ``type=ANALYZE`` both render ``ANALYZE``."""
        dialect = _dialect()
        by_flag, _ = _render(dialect, ExplainOptions(analyze=True))
        by_type, _ = _render(dialect, ExplainOptions(type=ExplainType.ANALYZE))
        assert by_flag == f"EXPLAIN ANALYZE {_BASE_SQL}"
        assert by_type == by_flag

    def test_format_rendering(self):
        """``format=`` renders ``FORMAT <NAME>``; syntax is ungated by probes."""
        dialect = _dialect()
        for fmt in ExplainFormat:
            sql, _ = _render(dialect, ExplainOptions(format=fmt))
            assert f"FORMAT {fmt.value}" in sql, fmt.value

    def test_costs_off_only_when_explicitly_false(self):
        """The default is ``costs=True``; only an explicit False emits COSTS OFF."""
        dialect = _dialect()
        default_sql, _ = _render(dialect, ExplainOptions())
        off_sql, _ = _render(dialect, ExplainOptions(costs=False))
        assert "COSTS OFF" not in default_sql
        assert off_sql == f"EXPLAIN COSTS OFF {_BASE_SQL}"

    def test_verbose_and_buffers(self):
        """``verbose`` and ``buffers`` each append their own keyword."""
        dialect = _dialect()
        assert _render(dialect, ExplainOptions(verbose=True))[0] == f"EXPLAIN VERBOSE {_BASE_SQL}"
        assert _render(dialect, ExplainOptions(buffers=True))[0] == f"EXPLAIN BUFFERS {_BASE_SQL}"

    def test_settings_and_wal(self):
        """The PostgreSQL-only SETTINGS and WAL keywords still render."""
        dialect = _dialect()
        assert "SETTINGS" in _render(dialect, ExplainOptions(settings=True))[0]
        assert "WAL" in _render(dialect, ExplainOptions(wal=True))[0]

    def test_timing_requires_analyze(self):
        """``TIMING ON`` appears only when ``analyze`` is also True."""
        dialect = _dialect()
        without, _ = _render(dialect, ExplainOptions(timing=True))
        with_, _ = _render(dialect, ExplainOptions(timing=True, analyze=True))
        assert "TIMING" not in without
        assert "TIMING ON" in with_

    def test_all_options_combined(self):
        """Every recognised option composes in the renderer's fixed order."""
        sql, _ = _render(
            _dialect(),
            ExplainOptions(
                analyze=True,
                format=ExplainFormat.JSON,
                costs=False,
                buffers=True,
                timing=True,
                verbose=True,
                settings=True,
                wal=True,
            ),
        )
        assert sql == (
            "EXPLAIN ANALYZE FORMAT JSON COSTS OFF BUFFERS TIMING ON "
            f"VERBOSE SETTINGS WAL {_BASE_SQL}"
        )


@pytest.mark.skipif(
    not BigQueryDialect(version=(3, 0, 0)).supports_explain_plan(),
    reason=(
        "BigQuery dialect reports supports_explain_plan()=False; there is no "
        "EXPLAIN result shape to interpret (the emulator returns no plan)"
    ),
)
class TestBigQueryExplainResultInterpretation:
    """Real-DB plan interpretation -- gated off until BigQuery supports EXPLAIN.

    The single test below records *where* a plan-shape interpretation would go.
    It is skipped by construction because the capability gate is False, so no
    plan-reading assertion is fabricated for a backend that cannot produce one.
    """

    def test_explain_returns_interpretable_plan(self, order_fixtures):
        """If support is ever added, assert the plan is a non-empty row list."""
        User, _, _ = order_fixtures
        plan = User.query().where(User.c.id == 1).explain().aggregate()
        assert isinstance(plan, list) and plan, "expected a non-empty plan row list"
