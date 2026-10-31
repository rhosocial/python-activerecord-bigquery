# tests/rhosocial/activerecord_bigquery_test/feature/backend/test_bigquery_clause_pair_guard.py
"""Guard: the four states of every clause pair this dialect consumes.

The expressiveness round split every two-spelling clause into two independent
parameters (``cycle`` / ``no_cycle``, ``cascade`` / ``restrict``,
``with_data`` / ``no_data``, ...); "unspecified" is
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
required default and that mapping is asserted explicitly.

One pair is **out of scope** because it is no longer a pair: the set
operation's ``all_`` / ``distinct`` flags.  The node now names its operation
with a word drawn from a closed set the node validates at construction, so
there is no "unspecified" state to spell and nothing to refuse.
:class:`TestSetOperationSpelling` guards that word-to-spelling mapping
instead.

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
    SetOperation,
)
from rhosocial.activerecord.backend.expression.statements.ddl_schema import (
    DropSchemaStatement,
)
from rhosocial.activerecord.backend.expression.statements.ddl_table import (
    IdentityClause,
)
from rhosocial.activerecord.backend.expression.statements.ddl_view import (
    CreateMaterializedViewStatement,
    DropMaterializedViewStatement,
)
from rhosocial.activerecord.backend.expression.statements.dql import (
    QueryStatement,
)
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect
from rhosocial.activerecord.backend.impl.bigquery.expression import (
    BigQueryCreateMaterializedViewStatement,
    BigQueryDropMaterializedViewStatement,
)


@pytest.fixture
def dialect():
    return BigQueryDialect()


def _query(d, table="t"):
    return QueryStatement(d, select=[Column(d, "a")], from_=Table(d, table))


class TestSetOperationSpelling:
    """The four operation words and the spelling each one gets here.

    BigQuery's grammar has no bare set operator::

        set_operator:
          UNION { ALL | DISTINCT } | INTERSECT DISTINCT | EXCEPT DISTINCT

    (GoogleSQL DDL/query reference; the Redshift-to-BigQuery migration guide
    rewrites a bare ``UNION`` as ``UNION DISTINCT``.)

    The node names the operation with a word and the dialect maps it. Because
    the grammar has no bare form, every spelling carries an explicit ``ALL`` or
    ``DISTINCT``, and ``union`` / ``union_all`` are told apart by the modifier.

    The former ``all_`` / ``distinct`` flag pair is gone, and with it the one
    intentional SQL collision this file recorded ("falsy forces DISTINCT, so
    'unspecified' is unreachable there"). That collision cannot occur now: the
    word set has no duplicate member, and an unknown word is refused at
    construction. The ``INTERSECT ALL`` / ``EXCEPT ALL`` refusals are likewise
    structural -- there is no word for them -- so there is nothing left to
    assert as a named refusal.
    """

    def _expr(self, dialect, op="union"):
        return SetOperation(
            dialect,
            op=op,
            left=_query(dialect, "t1"),
            right=_query(dialect, "t2"),
        )

    def test_union_spells_distinct(self, dialect):
        sql = self._expr(dialect).to_sql()[0]
        assert sql == (
            "SELECT `a` FROM `t1` UNION DISTINCT SELECT `a` FROM `t2`"
        ), sql

    def test_union_all_spells_all(self, dialect):
        sql = self._expr(dialect, "union_all").to_sql()[0]
        assert sql == "SELECT `a` FROM `t1` UNION ALL SELECT `a` FROM `t2`", sql

    def test_the_two_union_words_are_distinguishable(self, dialect):
        assert self._expr(dialect).to_sql()[0] != self._expr(dialect, "union_all").to_sql()[0]

    def test_intersect_and_except_spell_distinct(self, dialect):
        assert self._expr(dialect, "intersect").to_sql()[0] == (
            "SELECT `a` FROM `t1` INTERSECT DISTINCT SELECT `a` FROM `t2`"
        )
        assert self._expr(dialect, "except").to_sql()[0] == (
            "SELECT `a` FROM `t1` EXCEPT DISTINCT SELECT `a` FROM `t2`"
        )

    def test_intersect_all_and_except_all_cannot_be_spelled(self, dialect):
        """The grammar has no ``INTERSECT ALL`` / ``EXCEPT ALL``, and now
        neither has the node: there is no word to ask for them."""
        for word in ("intersect_all", "except_all", "minus", "UNION ALL"):
            with pytest.raises(ValueError, match="op must be one of"):
                self._expr(dialect, word)

    def test_the_word_is_case_insensitive_and_normalized(self, dialect):
        expr = self._expr(dialect, "UNION_ALL")
        assert expr.op == "union_all"
        assert "UNION ALL" in expr.to_sql()[0]

    def test_every_operation_word_is_covered_and_distinct(self, dialect):
        """Each word renders its own SQL, and no bare operator is ever emitted."""
        rendered = {}
        for op in ("union", "union_all", "intersect", "except"):
            sql = self._expr(dialect, op).to_sql()[0]
            rendered[op] = sql
            operator = sql.split(" FROM `t1` ")[1].split(" SELECT")[0]
            assert "ALL" in operator or "DISTINCT" in operator, (op, sql)
        assert len(set(rendered.values())) == 4, rendered

    def test_nested_set_operations_stay_parenthesized(self, dialect):
        inner = self._expr(dialect, "union_all")
        nested = SetOperation(
            dialect,
            op="union",
            left=inner,
            right=_query(dialect, "t3"),
        )
        sql = nested.to_sql()[0]
        assert sql.startswith("("), sql
        assert ") UNION DISTINCT " in sql, sql


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
    """``CreateMaterializedViewStatement.with_data`` / ``no_data``.

    BigQuery's ``CREATE MATERIALIZED VIEW`` grammar has no ``WITH [NO] DATA``
    clause -- the view is populated at creation time -- so both explicit
    spellings are refused by name; the unspecified state renders the clause
    without either.
    """

    def _generic(self, dialect, **kwargs):
        return CreateMaterializedViewStatement(
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
        expr = BigQueryCreateMaterializedViewStatement(
            dialect, MaterializedView(dialect, "mv"), _query(dialect)
        )
        assert expr.to_sql()[0] == (
            "CREATE MATERIALIZED VIEW `mv` AS SELECT `a` FROM `t`"
        )


class TestMaterializedViewDropClauses:
    """``DropMaterializedViewStatement.cascade`` / ``restrict``.

    BigQuery's ``DROP MATERIALIZED VIEW [IF EXISTS] mv_name`` grammar has no
    CASCADE and no RESTRICT, so both explicit spellings are refused: the
    generic expression through the formatter (dialect-layer refusal), and the
    BigQuery expression at construction (the same refusal, one layer earlier).
    """

    def _generic(self, dialect, **kwargs):
        return DropMaterializedViewStatement(
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
            BigQueryDropMaterializedViewStatement(
                dialect, MaterializedView(dialect, "mv"), cascade=True
            )
        with pytest.raises(ValueError, match="RESTRICT"):
            BigQueryDropMaterializedViewStatement(
                dialect, MaterializedView(dialect, "mv"), restrict=True
            )

    def test_bigquery_subclass_renders_the_plain_form(self, dialect):
        expr = BigQueryDropMaterializedViewStatement(
            dialect, MaterializedView(dialect, "mv")
        )
        assert expr.to_sql()[0] == "DROP MATERIALIZED VIEW `mv`"


class TestDropSchemaClauses:
    """``DropSchemaStatement.cascade`` / ``restrict``.

    BigQuery's grammar is ``DROP SCHEMA [IF EXISTS] name [CASCADE | RESTRICT]``
    with RESTRICT as the default; both spellings are therefore expressible
    (managing-datasets page: "To delete a dataset and all of its contents, use
    the CASCADE keyword").  The dialect renders each requested spelling.
    """

    def _expr(self, dialect, **kwargs):
        return DropSchemaStatement(dialect, Schema(dialect, "s"), **kwargs)

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
