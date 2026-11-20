# tests/rhosocial/activerecord_bigquery_test/feature/query/test_predicate_alias.py
"""Predicates must be able to carry an alias.

A predicate is not confined to a WHERE clause. ``LIKE`` and its relatives also
appear in a SELECT list, inside ``CASE WHEN``, in a ``JOIN ... ON`` condition,
and in DDL as a ``CHECK`` constraint or a partial-index predicate. In the
projection case the boolean is a column like any other and needs a name.

None of the predicate formatters honoured an alias, and ``SQLPredicate`` did
not even offer ``as_()``, so an aliased predicate silently rendered a bare
boolean — or could not be aliased at all. These tests pin the behaviour for
every predicate family, and pin the equally important inverse: no alias means
no ``AS`` in the output.
"""

# tests/rhosocial/activerecord_bigquery_test/feature/query/test_predicate_alias.py
import pytest

from rhosocial.activerecord.backend.impl.sqlite.dialect import SQLiteDialect
from rhosocial.activerecord.backend.expression import Column, Literal, NumericColumn, StringColumn
from rhosocial.activerecord.backend.expression.predicates import (
    IsBooleanPredicate,
    IsNullPredicate,
)


@pytest.fixture
def dialect():
    d = SQLiteDialect()
    d._version = (3, 46, 1)
    return d


@pytest.fixture
def name(dialect):
    # Typed: the families below are exercised through the capability mixins
    # (``LIKE`` / ``ILIKE``), which live on the typed classes only.
    return StringColumn(dialect, "name", table="t")


@pytest.fixture
def qty(dialect):
    return NumericColumn(dialect, "qty", table="t")


def ident(dialect, alias):
    return dialect.format_identifier(alias)


# ---------------------------------------------------------------------------
# Every predicate family honours the alias
# ---------------------------------------------------------------------------


def _families(dialect, name, qty):
    """One aliased predicate per family, keyed by name."""
    return {
        "comparison": (name == Literal(dialect, "x")).as_("a"),
        "like": name.like("a%").as_("a"),
        "ilike": name.ilike("a%").as_("a"),
        "logical_and": ((name == Literal(dialect, "x")) & (qty > Literal(dialect, 0))).as_("a"),
        "logical_or": ((name == Literal(dialect, "x")) | (qty > Literal(dialect, 0))).as_("a"),
        "not": (~(name == Literal(dialect, "x"))).as_("a"),
        "in": name.in_([1, 2]).as_("a"),
        "between": name.between(Literal(dialect, "a"), Literal(dialect, "z")).as_("a"),
        "is_null": IsNullPredicate(dialect, name).as_("a"),
        "is_boolean": IsBooleanPredicate(dialect, name, True).as_("a"),
    }


@pytest.mark.parametrize(
    "family",
    [
        "comparison",
        "like",
        "ilike",
        "logical_and",
        "logical_or",
        "not",
        "in",
        "between",
        "is_null",
        "is_boolean",
    ],
)
def test_predicate_alias_reaches_the_sql(dialect, name, qty, family):
    """The alias must appear in the rendered statement."""
    expr = _families(dialect, name, qty)[family]
    sql, _ = expr.to_sql()
    assert sql.endswith(f"AS {ident(dialect, 'a')}")
    assert sql.count("AS ") == 1, f"alias applied more than once: {sql!r}"


@pytest.mark.parametrize(
    "family",
    [
        "comparison",
        "like",
        "ilike",
        "logical_and",
        "logical_or",
        "not",
        "in",
        "between",
        "is_null",
        "is_boolean",
    ],
)
def test_unaliased_predicate_has_no_as_clause(dialect, name, qty, family):
    """The inverse: no alias must not introduce a stray ``AS``.

    A formatter that appended an empty ``AS`` would be just as broken as one
    that dropped the alias, and the regression is invisible unless it is
    pinned separately.
    """
    expr = _families(dialect, name, qty)[family]
    expr = type(expr).as_(expr, expr.alias)
    expr.alias = None
    sql, _ = expr.to_sql()
    assert " AS " not in sql, f"unexpected AS without an alias: {sql!r}"


# ---------------------------------------------------------------------------
# The reason this matters: a predicate used as a projected column
# ---------------------------------------------------------------------------


def test_projected_predicate_is_named_like_a_column(dialect, name):
    """``SELECT name LIKE 'a%' AS is_apple`` is the motivating case."""
    sql, params = name.like("a%").as_("is_apple").to_sql()
    assert sql == f'"t"."name" LIKE {dialect.get_parameter_placeholder()} AS {ident(dialect, "is_apple")}'
    assert params == ("a%",)


def test_alias_works_for_a_bare_column_too(dialect):
    """The base behaviour must be unchanged by the predicate change.

    Deliberately a bare ``Column``: the ``name`` fixture is typed now, and this
    case is specifically about the untyped reference still aliasing.
    """
    sql, _ = Column(dialect, "name", table="t").as_("n").to_sql()
    assert sql == f'"t"."name" AS {ident(dialect, "n")}'


# ---------------------------------------------------------------------------
# Empty value list: a branch of the IN formatter with its own return
# ---------------------------------------------------------------------------


def test_empty_in_list_keeps_its_alias(dialect, name):
    """``IN ()`` is a separate return path in the IN formatter."""
    sql, params = name.in_([]).as_("none").to_sql()
    assert sql.endswith(f"AS {ident(dialect, 'none')}")
    assert params == ()


# ---------------------------------------------------------------------------
# Parameters are unaffected by aliasing
# ---------------------------------------------------------------------------


def test_aliasing_preserves_parameters(dialect, name, qty):
    """The alias is pure SQL decoration; bind order must not shift."""
    expr = (name.like("a%") & (qty > Literal(dialect, 5))).as_("both")
    _, params = expr.to_sql()
    assert params == ("a%", 5)
