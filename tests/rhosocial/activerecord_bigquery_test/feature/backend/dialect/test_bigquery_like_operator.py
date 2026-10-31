# tests/rhosocial/activerecord_bigquery_test/feature/backend/dialect/test_bigquery_like_operator.py
"""The LIKE family: two words BigQuery spells, and the one it refuses.

``LikePredicate`` carries the operation as a wire word and the dialect writes the
SQL keyword, so the three members are the dialect's three answers. BigQuery's
grammar has ``LIKE`` and ``NOT LIKE`` and no ``ILIKE``; the portable
case-insensitive form is a ``LOWER()`` comparison. Rendering ``ILIKE`` would hand
the server a keyword it rejects, from a node the caller built, with nothing on
the way saying so -- expression-dialect §6 and §17 make that a refusal.

``ILikePredicate`` is a different promise (the portable ``LOWER(x) LIKE
LOWER(y)`` emulation) and a different kind, so it is refused by its own absent
formatter. These cases keep the two apart: routing one into the other would
silently rewrite SQL callers depend on.
"""

import pytest

from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError
from rhosocial.activerecord.backend.expression.core import Column, Literal
from rhosocial.activerecord.backend.expression.predicates import (
    ILikePredicate,
    LikeOperator,
    LikePredicate,
)
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect


@pytest.fixture
def dialect():
    return BigQueryDialect()


@pytest.fixture
def pattern(dialect):
    return LikePredicate(
        dialect, LikeOperator.LIKE, Column(dialect, "name"), Literal(dialect, "%a%")
    )


class TestTheWordsBigQuerySpells:
    def test_like(self, dialect):
        expr = LikePredicate(
            dialect, LikeOperator.LIKE, Column(dialect, "name"), Literal(dialect, "%a%")
        )
        assert expr.to_sql() == ("`name` LIKE ?", ("%a%",))

    def test_not_like(self, dialect):
        expr = LikePredicate(
            dialect,
            LikeOperator.NOT_LIKE,
            Column(dialect, "name"),
            Literal(dialect, "%a%"),
        )
        assert expr.to_sql() == ("`name` NOT LIKE ?", ("%a%",))

    def test_the_keyword_comes_from_the_operator_not_the_word(self, dialect, pattern):
        """The node carries ``like``; the SQL says ``LIKE``."""
        sql, _ = pattern.to_sql()
        assert "like" not in sql.replace("LIKE", "")
        assert LikeOperator.LIKE.keyword in sql


class TestTheWordBigQueryRefuses:
    def test_ilike_is_refused_by_name(self, dialect):
        expr = LikePredicate(
            dialect, LikeOperator.ILIKE, Column(dialect, "name"), Literal(dialect, "%a%")
        )
        with pytest.raises(UnsupportedFeatureError) as exc_info:
            expr.to_sql()
        assert "ILIKE" in str(exc_info.value)

    def test_the_refusal_points_at_the_portable_answer(self, dialect):
        """A caller told no should be told what to do instead."""
        expr = LikePredicate(
            dialect, LikeOperator.ILIKE, Column(dialect, "name"), Literal(dialect, "%a%")
        )
        with pytest.raises(UnsupportedFeatureError, match="LOWER"):
            expr.to_sql()

    def test_the_case_insensitive_node_has_its_own_refusal(self, dialect):
        """``ILikePredicate`` is a separate kind with a separate answer."""
        with pytest.raises(UnsupportedFeatureError) as exc_info:
            ILikePredicate(dialect, Column(dialect, "name"), "a%").to_sql()
        assert "format_ilike_predicate" in str(exc_info.value)

    def test_the_two_refusals_are_not_the_same_one(self, dialect):
        """Neither is routed into the other; each names its own cause."""
        like_sql = None
        with pytest.raises(UnsupportedFeatureError) as like_exc:
            LikePredicate(
                dialect,
                LikeOperator.ILIKE,
                Column(dialect, "name"),
                Literal(dialect, "%a%"),
            ).to_sql()
        with pytest.raises(UnsupportedFeatureError) as ilike_exc:
            ILikePredicate(dialect, Column(dialect, "name"), "a%").to_sql()
        assert str(like_exc.value) != str(ilike_exc.value)
        assert like_sql is None
