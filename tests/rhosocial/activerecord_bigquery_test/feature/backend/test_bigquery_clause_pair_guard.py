# tests/rhosocial/activerecord_bigquery_test/feature/backend/test_bigquery_clause_pair_guard.py
"""Guard: the four states of every clause pair this dialect consumes.

The expressiveness round split every two-spelling clause into two independent
parameters (``cycle`` / ``no_cycle``, ``cascade`` / ``restrict``,
``with_data`` / ``no_data``, ``all_`` / ``distinct``, ...); "unspecified" is
the state where none of a pair's parameters is set, and setting both raises
``ValueError`` at construction.  For every pair a formatter here reads, this
file asserts what each of the four states produces:

====================  ==================================================
neither parameter     the dialect's documented behavior for "no request"
parameter A           A's spelling, or a refusal naming A
parameter B           B's spelling, or a refusal naming B
both parameters       ``ValueError``
====================  ==================================================

For a dialect that cannot spell a side, the request is refused by name (never
dropped); the refusal is part of the pair's state table, so "cannot express"
is an asserted outcome rather than a silent substitution.  Where a dialect's
grammar makes a spelling mandatory, the "neither" state maps to the grammar's
required default and that mapping is asserted explicitly -- see
:class:`TestSetOperationQualifier`, the one pair in this file whose grammar
has no bare form.

**Not server-verified.**  No BigQuery instance exists in this repository and
CI has none; every assertion here is a render assertion.  The mapping
assertions are documentation comparisons, recorded per test.

Run red first: this file was run against the pre-split code before any
formatter here was changed; the failing ids are recorded in the round's
report.
"""

import pytest

from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError
from rhosocial.activerecord.backend.expression.core import Column
from rhosocial.activerecord.backend.expression.objects import (
    MaterializedView,
    Schema,
    Table,
)
from rhosocial.activerecord.backend.expression.query_sources import (
    SetOperationExpression,
)
from rhosocial.activerecord.backend.expression.statements.ddl_schema import (
    DropSchemaExpression,
)
from rhosocial.activerecord.backend.expression.statements.ddl_table import (
    IdentityClause,
)
from rhosocial.activerecord.backend.expression.statements.ddl_view import (
    CreateMaterializedViewExpression,
    DropMaterializedViewExpression,
)
from rhosocial.activerecord.backend.expression.statements.dql import (
    QueryExpression,
)
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect
from rhosocial.activerecord.backend.impl.bigquery.expression import (
    BigQueryCreateMaterializedViewExpression,
    BigQueryDropMaterializedViewExpression,
)


@pytest.fixture
def dialect():
    return BigQueryDialect()


def _query(d, table="t"):
    return QueryExpression(d, select=[Column(d, "a")], from_=Table(d, table))


class TestSetOperationQualifier:
    """``SetOperationExpression.all_`` / ``distinct``.

    BigQuery's grammar has no bare set operator::

        set_operator:
          UNION { ALL | DISTINCT } | INTERSECT DISTINCT | EXCEPT DISTINCT

    (GoogleSQL DDL/query reference; the Redshift-to-BigQuery migration guide
    rewrites a bare ``UNION`` as ``UNION DISTINCT``, and the audit records
    "BigQuery: falsy forces DISTINCT, so 'unspecified' is unreachable there").

    The dialect therefore spells the unspecified state with its grammar's
    required default, ``DISTINCT``; it does not emit the invalid bare form and
    it does not refuse the ORM's default ``union()`` path.  The explicit
    ``distinct=True`` state renders the same SQL: on this dialect the two
    requests cannot be distinguished in SQL, because there is no second
    spelling for "no qualifier".  This is the one pair in this file where the
    four states are not pairwise distinguishable in SQL; the two requests stay
    distinguishable at the API (one sets a parameter), and the audit entry is
    the recorded reason.
    """

    def _expr(self, dialect, operation="UNION", **kwargs):
        return SetOperationExpression(
            dialect,
            left=_query(dialect, "t1"),
            right=_query(dialect, "t2"),
            operation=operation,
            **kwargs,
        )

    def test_neither_spells_the_grammar_required_default(self, dialect):
        sql = self._expr(dialect).to_sql()[0]
        assert sql == (
            "SELECT `a` FROM `t1` UNION DISTINCT SELECT `a` FROM `t2`"
        ), sql

    def test_all_spells_all(self, dialect):
        sql = self._expr(dialect, all_=True).to_sql()[0]
        assert sql == "SELECT `a` FROM `t1` UNION ALL SELECT `a` FROM `t2`", sql

    def test_distinct_spells_distinct(self, dialect):
        sql = self._expr(dialect, distinct=True).to_sql()[0]
        assert sql == (
            "SELECT `a` FROM `t1` UNION DISTINCT SELECT `a` FROM `t2`"
        ), sql

    def test_both_parameters_are_api_misuse(self, dialect):
        with pytest.raises(ValueError, match="all_ and distinct are mutually exclusive"):
            self._expr(dialect, all_=True, distinct=True)

    def test_intersect_all_is_refused_by_name(self, dialect):
        """BigQuery has ``INTERSECT DISTINCT`` only; ALL is not in the grammar."""
        with pytest.raises(UnsupportedFeatureError) as exc:
            self._expr(dialect, operation="INTERSECT", all_=True).to_sql()
        assert exc.value.feature_name == "INTERSECT ALL"

    def test_except_all_is_refused_by_name(self, dialect):
        """BigQuery has ``EXCEPT DISTINCT`` only; ALL is not in the grammar."""
        with pytest.raises(UnsupportedFeatureError) as exc:
            self._expr(dialect, operation="EXCEPT", all_=True).to_sql()
        assert exc.value.feature_name == "EXCEPT ALL"

    def test_distinct_on_intersect_and_except_is_expressible(self, dialect):
        assert self._expr(dialect, operation="INTERSECT", distinct=True).to_sql()[0] == (
            "SELECT `a` FROM `t1` INTERSECT DISTINCT SELECT `a` FROM `t2`"
        )
        assert self._expr(dialect, operation="EXCEPT", distinct=True).to_sql()[0] == (
            "SELECT `a` FROM `t1` EXCEPT DISTINCT SELECT `a` FROM `t2`"
        )


class TestIdentityClausePairs:
    """``IdentityClause`` cycle / order / cache pairs.

    BigQuery's ``identity_column`` grammar carries only ``START WITH`` and
    ``INCREMENT BY`` (identity-columns page and DDL reference, fetched
    2026-10-07); every other option is absent, so each requested spelling is
    refused by name.  The refusals name the exact spelling, which is what
    keeps ``cycle`` and ``no_cycle`` (and their siblings) distinguishable as
    outcomes.
    """

    def _bare(self, dialect):
        return IdentityClause(dialect).to_sql()[0]

    def test_neither_renders_the_bare_clause(self, dialect):
        assert self._bare(dialect) == " GENERATED BY DEFAULT AS IDENTITY ()"

    def test_cycle_and_no_cycle_are_refused_by_name(self, dialect):
        with pytest.raises(UnsupportedFeatureError) as exc:
            IdentityClause(dialect, cycle=True).to_sql()
        assert exc.value.feature_name == "IDENTITY CYCLE"
        with pytest.raises(UnsupportedFeatureError) as exc:
            IdentityClause(dialect, no_cycle=True).to_sql()
        assert exc.value.feature_name == "IDENTITY NO CYCLE"

    def test_cycle_and_no_cycle_are_api_misuse_together(self, dialect):
        with pytest.raises(ValueError, match="cycle and no_cycle are mutually exclusive"):
            IdentityClause(dialect, cycle=True, no_cycle=True)

    def test_order_and_no_order_are_refused_by_name(self, dialect):
        with pytest.raises(UnsupportedFeatureError) as exc:
            IdentityClause(dialect, order=True).to_sql()
        assert exc.value.feature_name == "IDENTITY ORDER"
        with pytest.raises(UnsupportedFeatureError) as exc:
            IdentityClause(dialect, no_order=True).to_sql()
        assert exc.value.feature_name == "IDENTITY NO ORDER"

    def test_order_and_no_order_are_api_misuse_together(self, dialect):
        with pytest.raises(ValueError, match="order and no_order are mutually exclusive"):
            IdentityClause(dialect, order=True, no_order=True)

    def test_cache_and_no_cache_are_refused_by_name(self, dialect):
        with pytest.raises(UnsupportedFeatureError) as exc:
            IdentityClause(dialect, cache=10).to_sql()
        assert exc.value.feature_name == "IDENTITY CACHE"
        with pytest.raises(UnsupportedFeatureError) as exc:
            IdentityClause(dialect, no_cache=True).to_sql()
        assert exc.value.feature_name == "IDENTITY NO CACHE"

    def test_cache_and_no_cache_are_api_misuse_together(self, dialect):
        with pytest.raises(ValueError, match="cache and no_cache are mutually exclusive"):
            IdentityClause(dialect, cache=10, no_cache=True)

    def test_cache_zero_is_no_longer_a_sentinel(self, dialect):
        """``cache=0`` was the old spelling of NO CACHE; it is refused now."""
        with pytest.raises(ValueError, match="cache must be a positive integer"):
            IdentityClause(dialect, cache=0)

    def test_start_and_increment_still_render(self, dialect):
        """The two documented options stay reachable in every state table."""
        sql = IdentityClause(dialect, start=5, increment=2).to_sql()[0]
        assert sql == (
            " GENERATED BY DEFAULT AS IDENTITY (START WITH 5 INCREMENT BY 2)"
        )


class TestMaterializedViewCreateClauses:
    """``CreateMaterializedViewExpression.with_data`` / ``no_data``.

    BigQuery's ``CREATE MATERIALIZED VIEW`` grammar has no ``WITH [NO] DATA``
    clause -- the view is populated at creation time -- so both explicit
    spellings are refused by name; the unspecified state renders the clause
    without either.
    """

    def _generic(self, dialect, **kwargs):
        return CreateMaterializedViewExpression(
            dialect, view=MaterializedView(dialect, "mv"), query=_query(dialect), **kwargs
        )

    def test_neither_renders_without_the_clause(self, dialect):
        sql = self._generic(dialect).to_sql()[0]
        assert sql == (
            "CREATE MATERIALIZED VIEW `mv` AS SELECT `a` FROM `t`"
        ), sql

    def test_with_data_is_refused_by_name(self, dialect):
        with pytest.raises(UnsupportedFeatureError) as exc:
            self._generic(dialect, with_data=True).to_sql()
        assert "WITH DATA" in exc.value.feature_name

    def test_no_data_is_refused_by_name(self, dialect):
        with pytest.raises(UnsupportedFeatureError) as exc:
            self._generic(dialect, no_data=True).to_sql()
        assert "WITH NO DATA" in exc.value.feature_name

    def test_both_parameters_are_api_misuse(self, dialect):
        with pytest.raises(ValueError, match="with_data and no_data are mutually exclusive"):
            self._generic(dialect, with_data=True, no_data=True)

    def test_bigquery_subclass_renders_the_plain_form(self, dialect):
        expr = BigQueryCreateMaterializedViewExpression(
            dialect, MaterializedView(dialect, "mv"), _query(dialect)
        )
        assert expr.to_sql()[0] == (
            "CREATE MATERIALIZED VIEW `mv` AS SELECT `a` FROM `t`"
        )


class TestMaterializedViewDropClauses:
    """``DropMaterializedViewExpression.cascade`` / ``restrict``.

    BigQuery's ``DROP MATERIALIZED VIEW [IF EXISTS] mv_name`` grammar has no
    CASCADE and no RESTRICT, so both explicit spellings are refused: the
    generic expression through the formatter (dialect-layer refusal), and the
    BigQuery expression at construction (the same refusal, one layer earlier).
    """

    def _generic(self, dialect, **kwargs):
        return DropMaterializedViewExpression(
            dialect, view=MaterializedView(dialect, "mv"), **kwargs
        )

    def test_neither_renders(self, dialect):
        assert self._generic(dialect).to_sql()[0] == "DROP MATERIALIZED VIEW `mv`"

    def test_cascade_is_refused_by_name(self, dialect):
        with pytest.raises(UnsupportedFeatureError) as exc:
            self._generic(dialect, cascade=True).to_sql()
        assert "CASCADE" in exc.value.feature_name

    def test_restrict_is_refused_by_name(self, dialect):
        with pytest.raises(UnsupportedFeatureError) as exc:
            self._generic(dialect, restrict=True).to_sql()
        assert "RESTRICT" in exc.value.feature_name

    def test_both_parameters_are_api_misuse(self, dialect):
        with pytest.raises(ValueError, match="cascade and restrict are mutually exclusive"):
            self._generic(dialect, cascade=True, restrict=True)

    def test_bigquery_subclass_refuses_both_at_construction(self, dialect):
        with pytest.raises(ValueError, match="CASCADE"):
            BigQueryDropMaterializedViewExpression(
                dialect, MaterializedView(dialect, "mv"), cascade=True
            )
        with pytest.raises(ValueError, match="RESTRICT"):
            BigQueryDropMaterializedViewExpression(
                dialect, MaterializedView(dialect, "mv"), restrict=True
            )

    def test_bigquery_subclass_renders_the_plain_form(self, dialect):
        expr = BigQueryDropMaterializedViewExpression(
            dialect, MaterializedView(dialect, "mv")
        )
        assert expr.to_sql()[0] == "DROP MATERIALIZED VIEW `mv`"


class TestDropSchemaClauses:
    """``DropSchemaExpression.cascade`` / ``restrict``.

    BigQuery's grammar is ``DROP SCHEMA [IF EXISTS] name [CASCADE | RESTRICT]``
    with RESTRICT as the default; both spellings are therefore expressible
    (managing-datasets page: "To delete a dataset and all of its contents, use
    the CASCADE keyword").  The dialect renders each requested spelling.
    """

    def _expr(self, dialect, **kwargs):
        return DropSchemaExpression(dialect, Schema(dialect, "s"), **kwargs)

    def test_neither_renders(self, dialect):
        assert self._expr(dialect).to_sql()[0] == "DROP SCHEMA `s`"

    def test_cascade_renders(self, dialect):
        assert self._expr(dialect, cascade=True).to_sql()[0] == (
            "DROP SCHEMA `s` CASCADE"
        )

    def test_restrict_renders(self, dialect):
        assert self._expr(dialect, restrict=True).to_sql()[0] == (
            "DROP SCHEMA `s` RESTRICT"
        )

    def test_both_parameters_are_api_misuse(self, dialect):
        with pytest.raises(ValueError, match="cascade and restrict are mutually exclusive"):
            self._expr(dialect, cascade=True, restrict=True)


class TestConsumedPairsStayGateable:
    """The probes behind the refusals are declared, not defaulted by accident.

    ``supports_schema_restrict`` is new in core and defaults to ``False``; the
    engine supports it, so this dialect declares it ``True`` and the formatter
    renders the spelling.  ``supports_identity_cache`` / ``_order`` are
    declared ``False`` explicitly so the refusal is this dialect's statement,
    not a default nobody revisited.
    """

    def test_schema_probes_are_declared_from_the_documented_grammar(self, dialect):
        assert dialect.supports_schema_cascade() is True
        assert dialect.supports_schema_restrict() is True

    def test_identity_cache_and_order_probes_are_declared_false(self, dialect):
        assert dialect.supports_identity_cycle() is False
        assert dialect.supports_identity_order() is False
        assert dialect.supports_identity_cache() is False
