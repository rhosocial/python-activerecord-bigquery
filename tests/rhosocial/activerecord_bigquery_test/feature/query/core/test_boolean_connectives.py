# tests/rhosocial/activerecord_bigquery_test/feature/query/test_boolean_connectives.py
"""A value's connectives keep the value type; a predicate's stay predicates.

``p1 & p2`` combines predicates for a WHERE clause. A truth *value* needs the
same three operators with a different result: ``(flag & other)`` must be
something a SELECT list can carry, so it stays a boolean value
(:class:`LogicalValue`) with the same SQL. One implementation,
dispatched by the receiver, which is what these tests pin.
"""

# tests/rhosocial/activerecord_bigquery_test/feature/query/test_boolean_connectives.py
import pytest

from rhosocial.activerecord.backend.expression import BooleanColumn
from rhosocial.activerecord.backend.expression.bases import SQLPredicate, SQLValue
from rhosocial.activerecord.backend.expression.core import LogicalValue
from rhosocial.activerecord.backend.expression.predicates import LogicalPredicate


@pytest.fixture
def dialect():
    from rhosocial.activerecord.backend.impl.sqlite.dialect import SQLiteDialect

    return SQLiteDialect()


def test_a_boolean_values_connectives_keep_the_value_type(dialect):
    flag = BooleanColumn(dialect, "flag")
    other = BooleanColumn(dialect, "other")

    combined = flag & other
    assert isinstance(combined, LogicalValue)
    assert isinstance(combined, SQLValue)
    assert not isinstance(combined, SQLPredicate)

    sql, params = combined.to_sql()
    assert "AND" in sql and params == ()


def test_a_value_can_be_negated_and_chained(dialect):
    flag = BooleanColumn(dialect, "flag")
    other = BooleanColumn(dialect, "other")

    assert isinstance(~flag, LogicalValue)

    chained = (flag & other) | flag
    assert isinstance(chained, LogicalValue)
    assert "OR" in chained.to_sql()[0]


def test_a_predicate_combination_stays_a_predicate(dialect):
    flag = BooleanColumn(dialect, "flag")
    other = BooleanColumn(dialect, "other")

    combined = flag.is_true() & other.is_true()
    assert isinstance(combined, LogicalPredicate)
    assert isinstance(combined, SQLPredicate)
    assert not isinstance(combined, SQLValue)

    assert isinstance(~flag.is_true(), LogicalPredicate)


def test_a_value_expression_can_be_aliased_into_a_select_list(dialect):
    flag = BooleanColumn(dialect, "flag")
    aliased = (flag & flag).as_("both")
    sql, params = aliased.to_sql()
    assert "AND" in sql and "both" in sql


def test_a_boolean_value_can_be_compared(dialect):
    flag = BooleanColumn(dialect, "flag")
    predicate = (flag & flag) == flag
    assert isinstance(predicate, SQLPredicate)


def test_both_receivers_render_the_same_connective(dialect):
    flag = BooleanColumn(dialect, "flag")
    other = BooleanColumn(dialect, "other")

    value_sql = (flag & other).to_sql()[0]
    predicate_sql = (flag.is_true() & other.is_true()).to_sql()[0]
    assert "AND" in value_sql and "AND" in predicate_sql
