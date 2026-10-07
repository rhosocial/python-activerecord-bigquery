# tests/rhosocial/activerecord_bigquery_test/feature/backend/test_bigquery_master_probe_guard.py
"""Guard: the master probes core's gate round consults are declared here.

Core's ``c4d6adc`` ("gate the unreachable clauses and add the wait pair") gave
three previously-decorative probes their first call sites and introduced a
fourth:

=  ===================================  ==========================================
#  probe                                now consulted by
=  ===================================  ==========================================
1  ``supports_materialized_cte()``      ``format_cte_expression``
2  ``supports_truncate()``              ``format_truncate_statement``
3  ``supports_with_data_clause()``      ``WITH [NO] DATA`` on CTAS, CREATE
                                        MATERIALIZED VIEW and REFRESH
                                        MATERIALIZED VIEW
4  ``supports_transaction_wait()``      the ``wait`` / ``no_wait`` pair on
                                        ``BeginTransactionExpression`` and
                                        ``SetTransactionExpression``
=  ===================================  ==========================================

A dialect that does not declare one of the first three now refuses what it
used to render -- possibly with SQL the server rejects.  For BigQuery the
documented answers are:

1. **False.**  ``WITH [RECURSIVE] { non_recursive_cte | recursive_cte }[, ...]``
   has no ``AS MATERIALIZED`` hint; the strings "AS MATERIALIZED" and
   "NOT MATERIALIZED" do not occur on the query-syntax page at all.
   https://cloud.google.com/bigquery/docs/reference/standard-sql/query-syntax#with_clause
2. **True.**  ``TRUNCATE TABLE [[project_name.]dataset_name.]table_name`` is
   the documented statement.
   https://cloud.google.com/bigquery/docs/reference/standard-sql/dml-syntax#truncate_table_statement
3. **False.**  ``CREATE TABLE``'s grammar ends at ``[ AS query_statement ]``
   and ``CREATE MATERIALIZED VIEW``'s at ``AS query_expression``; neither page
   contains the string "WITH DATA" or "WITH NO DATA" (the view is populated at
   creation time).
   https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language#create_table_statement
   https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language#create_materialized_view_statement
4. **False.**  The transactions page documents ``BEGIN TRANSACTION``,
   ``COMMIT TRANSACTION`` and ``ROLLBACK TRANSACTION``; the strings "WAIT" and
   "SET TRANSACTION" do not occur on it.
   https://cloud.google.com/bigquery/docs/reference/standard-sql/transactions

The refusals are asserted as outcomes: a request the dialect cannot spell
raises ``UnsupportedFeatureError`` naming that request (never a silent drop),
and the probe's answer is asserted alongside the refusal so a probe flip and
its formatter branch cannot drift apart.

**Not server-verified.**  No BigQuery instance exists in this repository and
CI has none; every assertion here is a render assertion, and the probe answers
above are documentation comparisons.

Run red first: this file was run against the unmodified tree (before the
probes were declared) and the failing ids are recorded in the round's report.
"""

import pytest

from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError
from rhosocial.activerecord.backend.expression.core import Column
from rhosocial.activerecord.backend.expression.objects import (
    MaterializedView,
    Table,
)
from rhosocial.activerecord.backend.expression.query_sources import (
    CTEExpression,
)
from rhosocial.activerecord.backend.expression.statements.ddl_table import (
    CreateTableAsExpression,
)
from rhosocial.activerecord.backend.expression.statements.ddl_truncate import (
    TruncateExpression,
)
from rhosocial.activerecord.backend.expression.statements.ddl_view import (
    CreateMaterializedViewExpression,
    RefreshMaterializedViewExpression,
)
from rhosocial.activerecord.backend.expression.statements.dql import (
    QueryExpression,
)
from rhosocial.activerecord.backend.expression.transaction import (
    BeginTransactionExpression,
    SetTransactionExpression,
)
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect


@pytest.fixture
def dialect():
    return BigQueryDialect()


def _query(d, table="t"):
    return QueryExpression(d, select=[Column(d, "a")], from_=Table(d, table))


class TestProbeDeclarations:
    """Each probe is this dialect's own ``bool`` answer, not a default or a stub.

    ``supports_transaction_wait`` previously resolved to the protocol stub's
    bare ``...`` body and answered ``None``; ``None is False`` is not the point
    -- the point is that the answer must be a declared boolean, and the
    renderer that consumes it must agree.
    """

    def test_materialized_cte_probe_is_declared_false(self, dialect):
        assert dialect.supports_materialized_cte() is False

    def test_truncate_probe_is_declared_true(self, dialect):
        assert dialect.supports_truncate() is True

    def test_with_data_probe_is_declared_false(self, dialect):
        assert dialect.supports_with_data_clause() is False

    def test_transaction_wait_probe_is_declared_false(self, dialect):
        assert dialect.supports_transaction_wait() is False


class TestMaterializedCteGate:
    """``CTEExpression.materialized`` / ``not_materialized``: gate 1.

    The documented ``WITH`` grammar has no hint, so both spellings are refused
    by name and the unspecified state renders the plain CTE.
    """

    def _cte(self, dialect, **kwargs):
        return CTEExpression(dialect, "c", _query(dialect), **kwargs)

    def test_neither_renders_the_plain_cte(self, dialect):
        sql, params = self._cte(dialect).to_sql()
        assert sql == "`c` AS (SELECT `a` FROM `t`)", sql
        assert params == ()

    def test_materialized_is_refused_by_name(self, dialect):
        with pytest.raises(UnsupportedFeatureError) as exc:
            self._cte(dialect, materialized=True).to_sql()
        assert exc.value.feature_name == "MATERIALIZED CTE"
        assert exc.value.dialect_name == "BigQuery"

    def test_not_materialized_is_refused_by_name(self, dialect):
        with pytest.raises(UnsupportedFeatureError) as exc:
            self._cte(dialect, not_materialized=True).to_sql()
        assert exc.value.feature_name == "NOT MATERIALIZED CTE"
        assert exc.value.dialect_name == "BigQuery"

    def test_both_parameters_are_api_misuse(self, dialect):
        with pytest.raises(
            ValueError, match="materialized and not_materialized are mutually exclusive"
        ):
            self._cte(dialect, materialized=True, not_materialized=True)


class TestTruncateGate:
    """``TruncateExpression``: gate 2.

    The probe is True because the DML reference documents the statement, so
    the plain render stays reachable; the option pairs stay refused by name.
    """

    def test_truncate_renders(self, dialect):
        sql, params = TruncateExpression(dialect, Table(dialect, "t")).to_sql()
        assert sql == "TRUNCATE TABLE `t`", sql
        assert params == ()

    def test_option_pairs_are_refused_by_name(self, dialect):
        for kwargs, feature in (
            ({"restart_identity": True}, "TRUNCATE RESTART IDENTITY"),
            ({"continue_identity": True}, "TRUNCATE CONTINUE IDENTITY"),
            ({"cascade": True}, "TRUNCATE CASCADE"),
            ({"restrict": True}, "TRUNCATE RESTRICT"),
        ):
            with pytest.raises(UnsupportedFeatureError) as exc:
                TruncateExpression(dialect, Table(dialect, "t"), **kwargs).to_sql()
            assert exc.value.feature_name == feature

    def test_option_pairs_are_api_misuse_together(self, dialect):
        with pytest.raises(ValueError, match="restart_identity and continue_identity"):
            TruncateExpression(
                dialect,
                Table(dialect, "t"),
                restart_identity=True,
                continue_identity=True,
            )
        with pytest.raises(ValueError, match="cascade and restrict"):
            TruncateExpression(
                dialect, Table(dialect, "t"), cascade=True, restrict=True
            )


class TestWithDataGate:
    """``WITH [NO] DATA``: gate 3, on all three consumers.

    The clause is not in BigQuery's grammar for any of the three statements.
    CTAS and the generic materialized-view expression are refused by the core
    renderers through this dialect's probe; ``CREATE MATERIALIZED VIEW`` has a
    BigQuery formatter of its own that refuses the same request with its own
    statement-prefixed feature name.  ``REFRESH MATERIALIZED VIEW`` is refused
    one gate earlier, at the statement: BigQuery has no such statement, so its
    clause gate is subsumed and the statement refusal is asserted instead.
    """

    def test_ctas_neither_renders(self, dialect):
        sql, params = CreateTableAsExpression(
            dialect, Table(dialect, "t"), _query(dialect)
        ).to_sql()
        assert sql == "CREATE TABLE `t` AS SELECT `a` FROM `t`", sql
        assert params == ()

    def test_ctas_with_data_is_refused_by_name(self, dialect):
        with pytest.raises(UnsupportedFeatureError) as exc:
            CreateTableAsExpression(
                dialect, Table(dialect, "t"), _query(dialect), with_data=True
            ).to_sql()
        assert exc.value.feature_name == "WITH DATA"
        assert exc.value.dialect_name == "BigQuery"

    def test_ctas_no_data_is_refused_by_name(self, dialect):
        with pytest.raises(UnsupportedFeatureError) as exc:
            CreateTableAsExpression(
                dialect, Table(dialect, "t"), _query(dialect), no_data=True
            ).to_sql()
        assert exc.value.feature_name == "WITH NO DATA"
        assert exc.value.dialect_name == "BigQuery"

    def test_ctas_both_parameters_are_api_misuse(self, dialect):
        with pytest.raises(
            ValueError, match="with_data and no_data are mutually exclusive"
        ):
            CreateTableAsExpression(
                dialect,
                Table(dialect, "t"),
                _query(dialect),
                with_data=True,
                no_data=True,
            )

    def test_ctas_neither_is_gated_by_this_dialect_probe(self, dialect):
        """The positive control: the same formatter renders when nothing is asked.

        Without it, ``supports_with_data_clause`` could answer False and every
        CTAS could raise for an unrelated reason while these tests still passed.
        """
        assert dialect.supports_with_data_clause() is False
        sql = CreateTableAsExpression(
            dialect, Table(dialect, "t"), _query(dialect)
        ).to_sql()[0]
        assert "WITH" not in sql.upper().replace("WITHOUT", "")

    def test_mv_create_with_data_is_refused_by_name(self, dialect):
        with pytest.raises(UnsupportedFeatureError) as exc:
            CreateMaterializedViewExpression(
                dialect,
                view=MaterializedView(dialect, "mv"),
                query=_query(dialect),
                with_data=True,
            ).to_sql()
        assert exc.value.feature_name == "CREATE MATERIALIZED VIEW WITH DATA"
        assert exc.value.dialect_name == "BigQuery"

    def test_mv_create_no_data_is_refused_by_name(self, dialect):
        with pytest.raises(UnsupportedFeatureError) as exc:
            CreateMaterializedViewExpression(
                dialect,
                view=MaterializedView(dialect, "mv"),
                query=_query(dialect),
                no_data=True,
            ).to_sql()
        assert exc.value.feature_name == "CREATE MATERIALIZED VIEW WITH NO DATA"
        assert exc.value.dialect_name == "BigQuery"

    def test_mv_create_neither_renders(self, dialect):
        sql = CreateMaterializedViewExpression(
            dialect, view=MaterializedView(dialect, "mv"), query=_query(dialect)
        ).to_sql()[0]
        assert sql == "CREATE MATERIALIZED VIEW `mv` AS SELECT `a` FROM `t`", sql

    def test_mv_refresh_is_refused_at_the_statement(self, dialect):
        """No REFRESH MATERIALIZED VIEW in the grammar; the statement wins.

        Asserted for the requested-clause states too, so the ordering (statement
        gate before clause gate) is pinned rather than incidental.
        """
        assert dialect.supports_refresh_materialized_view() is False
        for kwargs in ({}, {"with_data": True}, {"no_data": True}):
            with pytest.raises(UnsupportedFeatureError) as exc:
                RefreshMaterializedViewExpression(
                    dialect, view=MaterializedView(dialect, "mv"), **kwargs
                ).to_sql()
            assert exc.value.feature_name == "REFRESH MATERIALIZED VIEW"


class TestTransactionWaitPair:
    """The ``wait`` / ``no_wait`` pair on both transaction expressions.

    GoogleSQL's transaction statements are ``BEGIN TRANSACTION`` /
    ``COMMIT TRANSACTION`` / ``ROLLBACK TRANSACTION``; the strings ``WAIT`` and
    ``SET TRANSACTION`` do not occur on the transactions page.  BigQuery
    therefore answers ``supports_transaction_wait()`` False and each requested
    spelling is refused by name: previously the ``BEGIN`` formatter dropped the
    pair and rendered a plain ``BEGIN``, which is the silent-ignore defect this
    round removes.  ``SET TRANSACTION`` has no BigQuery statement at all; the
    clause refusal is asserted ahead of the statement-level refusal so the
    requested spelling is still named.
    """

    def test_begin_neither_renders(self, dialect):
        sql, params = BeginTransactionExpression(dialect).to_sql()
        assert sql == "BEGIN", sql
        assert params == ()

    def test_begin_wait_is_refused_by_name(self, dialect):
        with pytest.raises(UnsupportedFeatureError) as exc:
            BeginTransactionExpression(dialect, wait=True).to_sql()
        assert exc.value.feature_name == "transaction WAIT"
        assert exc.value.dialect_name == "BigQuery"

    def test_begin_no_wait_is_refused_by_name(self, dialect):
        with pytest.raises(UnsupportedFeatureError) as exc:
            BeginTransactionExpression(dialect, no_wait=True).to_sql()
        assert exc.value.feature_name == "transaction NO WAIT"
        assert exc.value.dialect_name == "BigQuery"

    def test_begin_both_parameters_are_api_misuse(self, dialect):
        with pytest.raises(ValueError, match="wait and no_wait are mutually exclusive"):
            BeginTransactionExpression(dialect, wait=True, no_wait=True)

    def test_set_transaction_neither_keeps_the_statement_refusal(self, dialect):
        """The pinned round-trip classification: no SET TRANSACTION at all."""
        with pytest.raises(NotImplementedError, match="does not support SET TRANSACTION"):
            SetTransactionExpression(dialect).to_sql()

    def test_set_transaction_wait_is_refused_by_name(self, dialect):
        with pytest.raises(UnsupportedFeatureError) as exc:
            SetTransactionExpression(dialect, wait=True).to_sql()
        assert exc.value.feature_name == "transaction WAIT"
        assert exc.value.dialect_name == "BigQuery"

    def test_set_transaction_no_wait_is_refused_by_name(self, dialect):
        with pytest.raises(UnsupportedFeatureError) as exc:
            SetTransactionExpression(dialect, no_wait=True).to_sql()
        assert exc.value.feature_name == "transaction NO WAIT"
        assert exc.value.dialect_name == "BigQuery"

    def test_set_transaction_both_parameters_are_api_misuse(self, dialect):
        with pytest.raises(ValueError, match="wait and no_wait are mutually exclusive"):
            SetTransactionExpression(dialect, wait=True, no_wait=True)

    def test_probe_and_refusals_agree(self, dialect):
        """The declared probe and the formatter branches cannot drift apart.

        With the probe False, both spellings must refuse; a formatter that
        rendered one would be caught by the four assertions above, and a probe
        that flipped True without a real renderer would be caught by the same
        assertions still expecting refusals.  This test states the coupling in
        one place.
        """
        assert dialect.supports_transaction_wait() is False
        for expr in (
            BeginTransactionExpression(dialect, wait=True),
            BeginTransactionExpression(dialect, no_wait=True),
            SetTransactionExpression(dialect, wait=True),
            SetTransactionExpression(dialect, no_wait=True),
        ):
            with pytest.raises(UnsupportedFeatureError):
                expr.to_sql()

    def test_a_subclass_that_declares_the_clause_gets_a_render(self, dialect):
        """The probe is load-bearing in both directions.

        ``BigQueryDialect`` answers False, so the refusals above are reached
        through ``supports_transaction_wait()``, not through a hardcoded
        refusal.  A subclass that declares the clause exercises the render
        branch -- if the gate were swapped for an unconditional refusal this
        test would fail while the False-path tests kept passing, and the probe
        would have become decorative again.
        """

        class _Waits(BigQueryDialect):
            def supports_transaction_wait(self) -> bool:
                return True

        waits = _Waits()
        assert waits.supports_transaction_wait() is True
        assert BeginTransactionExpression(waits, wait=True).to_sql() == (
            "BEGIN WAIT",
            (),
        )
        assert BeginTransactionExpression(waits, no_wait=True).to_sql() == (
            "BEGIN NO WAIT",
            (),
        )
        # The statement still does not exist, so SET TRANSACTION keeps its
        # refusal even under a subclass that declares the clause.
        with pytest.raises(UnsupportedFeatureError):
            SetTransactionExpression(waits, wait=True).to_sql()
