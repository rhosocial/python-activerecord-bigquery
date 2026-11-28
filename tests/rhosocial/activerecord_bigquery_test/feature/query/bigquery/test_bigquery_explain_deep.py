# tests/rhosocial/activerecord_bigquery_test/feature/query/bigquery/test_bigquery_explain_deep.py
"""Backend-local, deep EXPLAIN tests for BigQuery.

The shared testsuite contracts only assert that EXPLAIN *can run*.  BigQuery is
an honest "no": every ``supports_explain*`` probe is ``False`` and the dialect
inherits the generic ``ExplainMixin`` renderer rather than a GoogleSQL-specific
one.  This file pins two things the testsuite cannot:

* **capability gates** -- BigQuery refuses EXPLAIN, so a real-DB plan-reading
  test is gated off and skipped with the reason, never faked with assertions on
  a plan the emulator will not produce.  Since a support switch is a
  parameterless bool, the FORMAT probe is one method per ``ExplainFormat``
  member plus one per option the generic formatter emits (verbose, costs,
  buffers, timing, settings, wal).
* **construction-level refusals** -- with no options the inherited formatter
  still prepends ``EXPLAIN`` (the documented fallback text emitted if the
  capability gate were bypassed), and each requested option is refused by name
  through ``UnsupportedFeatureError`` rather than silently dropped.

There is no async variant: rendering is a synchronous, dialect-level operation,
identical for the sync and the native-async BigQuery backend.
"""

from typing import Dict, Optional, Tuple

import pytest
from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError
from rhosocial.activerecord.backend.expression import Parameter
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

#: ``ExplainFormat`` member -> the parameterless probe core now declares for it.
_FORMAT_PROBES = {
    ExplainFormat.TEXT: "supports_explain_format_text",
    ExplainFormat.JSON: "supports_explain_format_json",
    ExplainFormat.XML: "supports_explain_format_xml",
    ExplainFormat.YAML: "supports_explain_format_yaml",
    ExplainFormat.TREE: "supports_explain_format_tree",
    ExplainFormat.TRADITIONAL: "supports_explain_format_traditional",
}

#: The EXPLAIN option spellings the generic formatter can emit.
_OPTION_PROBES = (
    "supports_explain_verbose",
    "supports_explain_costs",
    "supports_explain_buffers",
    "supports_explain_timing",
    "supports_explain_settings",
    "supports_explain_wal",
)


def _dialect() -> BigQueryDialect:
    """A dialect with a default dataset, so rendered relations are qualified."""
    return BigQueryDialect(version=(3, 0, 0), default_dataset=_DATASET)


def _render(
    dialect: BigQueryDialect, options: Optional[ExplainOptions] = None
) -> Tuple[str, tuple]:
    """Render an ``EXPLAIN SELECT ...`` statement with the given options."""
    query = QueryStatement(
        dialect=dialect,
        select=[Parameter(dialect, "*")],
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

    def test_explain_option_probes_are_parameterless_and_false(self):
        """No ANALYZE and no FORMAT/option variant is advertised as supported."""
        dialect = _dialect()
        assert dialect.supports_explain_analyze() is False
        for fmt, probe in _FORMAT_PROBES.items():
            assert getattr(dialect, probe)() is False, fmt.value
        for probe in _OPTION_PROBES:
            assert getattr(dialect, probe)() is False, probe

    def test_the_parameterised_switches_are_gone(self):
        """``supports_explain_format(str)`` is a parameterless switch per format."""
        dialect = _dialect()
        assert not hasattr(dialect, "supports_explain_format")


class TestBigQueryExplainRendering:
    """The inherited generic renderer's behaviour, option by option.

    These are construction-level: they never touch the emulator.  Because the
    capability gates are False, the bare render is a documented fallback, not a
    claim that BigQuery executes it; each option is refused by name.
    """

    def test_basic_explain_without_options(self):
        """With no options the renderer emits a plain ``EXPLAIN SELECT ...``."""
        sql, params = _render(_dialect())
        assert sql == f"EXPLAIN {_BASE_SQL}"
        assert params == ("*",), "wrapped statement's parameters must pass through"

    def test_empty_options_same_as_none(self):
        """An all-default ``ExplainOptions`` renders identically to no options."""
        assert _render(_dialect(), ExplainOptions()) == _render(_dialect())

    @pytest.mark.parametrize(
        ("options", "feature"),
        (
            ({"analyze": True}, "EXPLAIN ANALYZE"),
            ({"type": ExplainType.ANALYZE}, "EXPLAIN ANALYZE"),
            ({"costs": False}, "EXPLAIN COSTS"),
            ({"buffers": True}, "EXPLAIN BUFFERS"),
            ({"verbose": True}, "EXPLAIN VERBOSE"),
            ({"settings": True}, "EXPLAIN SETTINGS"),
            ({"wal": True}, "EXPLAIN WAL"),
        ),
        ids=(
            "analyze-flag",
            "analyze-type",
            "costs-off",
            "buffers",
            "verbose",
            "settings",
            "wal",
        ),
    )
    def test_options_are_refused_by_name(self, options: Dict, feature: str):
        """Each requested option raises, naming the request it cannot spell."""
        with pytest.raises(UnsupportedFeatureError) as exc:
            _render(_dialect(), ExplainOptions(**options))
        assert exc.value.feature_name == feature
        assert exc.value.dialect_name == "BigQuery"

    @pytest.mark.parametrize("fmt", tuple(ExplainFormat), ids=lambda m: m.value)
    def test_formats_are_refused_by_name(self, fmt: ExplainFormat):
        """``format=`` cannot become a GoogleSQL clause; the probe is False."""
        with pytest.raises(UnsupportedFeatureError) as exc:
            _render(_dialect(), ExplainOptions(format=fmt))
        assert exc.value.feature_name == f"EXPLAIN FORMAT {fmt.value}"

    def test_timing_without_analyze_stays_silent(self):
        """Core only emits ``TIMING ON`` alongside ``ANALYZE``.

        Without ``analyze`` the option is inert in the generic formatter, so
        nothing is emitted and nothing is refused -- pinned so a future
        ``timing``-only gate shows up as a behaviour change.  With ``analyze``
        the ANALYZE gate fires first here, so ``EXPLAIN TIMING`` is never the
        refusal this dialect produces; ``supports_explain_timing()`` still
        answers False in the capability test above.
        """
        sql, _ = _render(_dialect(), ExplainOptions(timing=True))
        assert "TIMING" not in sql
        assert sql == f"EXPLAIN {_BASE_SQL}"

    def test_the_first_requested_option_wins_when_all_are_set(self):
        """The renderer checks in a fixed order; ANALYZE is the first gate."""
        with pytest.raises(UnsupportedFeatureError) as exc:
            _render(
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
        assert exc.value.feature_name == "EXPLAIN ANALYZE"


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
