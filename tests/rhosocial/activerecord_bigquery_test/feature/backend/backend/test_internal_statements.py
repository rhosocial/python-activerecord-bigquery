# tests/rhosocial/activerecord_bigquery_test/feature/backend/backend/test_internal_statements.py
"""The two statements the backend runs itself, built as nodes rather than text.

The PK probe and the emulator's row-count probe used to be f-strings assembled
in the backend -- SQL text at a call site, which expression-dialect §16.2 makes
the formatter's business. They are nodes now, and these cases pin what they
render: the statement's shape, the alias the caller reads, and that no caller
data is spelled into the text where the driver could bind it.

The nodes are reached through the mixin that owns them, so nothing here needs a
client: `to_sql()` is the whole subject, which is what keeps this file in the
offline leg.
"""

import pytest

from rhosocial.activerecord.backend.expression.core import Column, Literal
from rhosocial.activerecord.backend.expression.predicates import ComparisonPredicate
from rhosocial.activerecord.backend.expression.query_parts import WhereClause
from rhosocial.activerecord.backend.impl.bigquery.backend.backend import BigQueryBackend
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect


class _Statements:
    """The mixin's statement builders, without a client behind them.

    ``_next_pk_expression`` and ``_count_expression`` read only ``self.dialect``
    and the relation-object helper, so borrowing the three methods is enough to
    ask a backend's own implementation what it renders.
    """

    dialect = BigQueryDialect()
    _relation_object = BigQueryBackend._relation_object
    _next_pk_expression = BigQueryBackend._next_pk_expression
    _count_expression = BigQueryBackend._count_expression


@pytest.fixture
def statements():
    return _Statements()


@pytest.fixture
def dialect():
    return BigQueryDialect()


class TestNextPkExpression:
    def test_a_bare_relation_renders_unqualified(self, statements):
        sql, params = statements._next_pk_expression("t", None, "id").to_sql()
        assert sql == "SELECT COALESCE(MAX(`id`), 0) + 1 AS `next_id` FROM `t`"
        assert params == ()

    def test_the_dataset_reaches_the_relation(self, statements):
        sql, _ = statements._next_pk_expression("t", "app", "id").to_sql()
        assert sql == (
            "SELECT COALESCE(MAX(`id`), 0) + 1 AS `next_id` FROM `app`.`t`"
        )

    def test_the_constants_are_inline_and_nothing_binds(self, statements):
        """The zero and the one belong to the statement, not to the caller."""
        _, params = statements._next_pk_expression("t", None, "id").to_sql()
        assert params == ()

    def test_the_primary_key_name_is_quoted_by_the_dialect(self, statements):
        """A name the dialect must quote is the dialect's to quote, not ours."""
        sql, _ = statements._next_pk_expression("t", None, "order").to_sql()
        assert "MAX(`order`)" in sql


class TestCountExpression:
    def test_a_where_clause_renders_its_own_keyword(self, statements, dialect):
        where = WhereClause(
            dialect,
            ComparisonPredicate(dialect, "=", Column(dialect, "a"), Literal(dialect, 1)),
        )
        sql, params = statements._count_expression("t", "app", where).to_sql()
        assert sql == "SELECT COUNT(*) AS `n` FROM `app`.`t` WHERE `a` = ?"
        assert params == (1,)

    def test_a_bare_predicate_is_wrapped_rather_than_stripped(self, statements, dialect):
        """The condition arrives as the options carry it, in either shape."""
        predicate = ComparisonPredicate(
            dialect, "=", Column(dialect, "a"), Literal(dialect, 1)
        )
        sql, params = statements._count_expression("t", None, predicate).to_sql()
        assert sql == "SELECT COUNT(*) AS `n` FROM `t` WHERE `a` = ?"
        assert params == (1,)

    def test_the_where_keyword_appears_exactly_once(self, statements, dialect):
        """The old path cut \"WHERE \" off the rendered text; the clause owns it."""
        where = WhereClause(
            dialect,
            ComparisonPredicate(dialect, "=", Column(dialect, "a"), Literal(dialect, 1)),
        )
        sql, _ = statements._count_expression("t", None, where).to_sql()
        assert sql.count("WHERE") == 1

    def test_caller_values_are_parameters_not_text(self, statements, dialect):
        where = WhereClause(
            dialect,
            ComparisonPredicate(
                dialect, "=", Column(dialect, "a"), Literal(dialect, "x'y")
            ),
        )
        sql, params = statements._count_expression("t", None, where).to_sql()
        assert "x'y" not in sql
        assert params == ("x'y",)
