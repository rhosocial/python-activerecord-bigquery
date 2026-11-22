# tests/rhosocial/activerecord_bigquery_test/feature/query/core/test_surface_only_column_types.py
"""The seven surface-only column classes and the tables that answer them.

These families have no operation the framework can promise on every backend --
see ``value_types.SurfaceOnlyValue`` for the evidence -- so their column
classes take ``ColumnBase`` alone. This file checks the three things that
follows from:

1. each class exists, is concrete, and builds a column that renders;
2. it offers the column surface (alias, null tests, casting) and no family
   operation, in particular no comparison;
3. every dialect table that names it -- SQLite and the dummy baseline -- stays
   complete (all twenty-four entries) and answers nothing with ``None``.
"""

import datetime
import inspect

import pytest

from rhosocial.activerecord.backend.adapters import (
    BitString,
    Geometry,
    MacAddress,
    Multirange,
    Range,
    Vector,
)
from rhosocial.activerecord.backend.suggestion.definitions import ExtraColumnTypeSuggestion
from rhosocial.activerecord.backend.expression import (
    BitStringColumn,
    ColumnBase,
    GeometryColumn,
    IntervalColumn,
    MacAddressColumn,
    MultirangeColumn,
    RangeColumn,
    VectorColumn,
)
from rhosocial.activerecord.backend.expression.column_types import annotation_for
from rhosocial.activerecord.backend.expression.declared import SurfaceOnlyAnnotation
from rhosocial.activerecord.backend.expression.mixins import ComparisonMixin
from rhosocial.activerecord.backend.expression.value_types import SurfaceOnlyValue
from rhosocial.activerecord.backend.impl.dummy.column_type import DUMMY_COLUMN_TYPES
from rhosocial.activerecord.backend.impl.dummy.dialect import DummyDialect
from rhosocial.activerecord.backend.impl.sqlite.dialect import SQLiteDialect
from rhosocial.activerecord.backend.impl.sqlite.mixins.column_type import (
    SQLITE_COLUMN_TYPES,
)
from rhosocial.activerecord.base.framework_types import FRAMEWORK_PYTHON_TYPES
from rhosocial.activerecord_bigquery_test.feature.query.column_helpers import (
    resolve_column_class,
)

#: ``{class: the framework type it answers}``, written out rather than derived:
#: a derived table would only restate the code back at itself.
SURFACE_ONLY = [
    (GeometryColumn, Geometry),
    (VectorColumn, Vector),
    (BitStringColumn, BitString),
    (RangeColumn, Range),
    (MultirangeColumn, Multirange),
    (MacAddressColumn, MacAddress),
    (IntervalColumn, datetime.timedelta),
]

_IDS = [klass.__name__ for klass, _ in SURFACE_ONLY]


def sqlite_dialect(version=(3, 46, 1)):
    return SQLiteDialect(version=version)


def dummy_dialect():
    dialect = DummyDialect()
    dialect._version = (3, 46, 1)
    return dialect


def test_the_value_surface_is_abstract():
    """A surface is not a node: it must not be instantiable.

    The annotation derived from it *is* a node -- it renders -- because
    ``_Annotation`` supplies the ``format_method`` the surface declares.
    """
    assert inspect.isabstract(SurfaceOnlyValue)
    assert not inspect.isabstract(SurfaceOnlyAnnotation)


def test_the_value_surface_offers_no_family_operation():
    """Only alias, null tests and casting -- no comparison, no arithmetic."""
    assert ComparisonMixin not in SurfaceOnlyValue.__mro__
    assert not hasattr(SurfaceOnlyValue, "compare")
    assert not hasattr(SurfaceOnlyValue, "add")


@pytest.mark.parametrize("klass, entry", SURFACE_ONLY, ids=_IDS)
def test_each_class_is_concrete_and_renders(klass, entry):
    """The protocol needs a class that builds; a failure here is a table hole."""
    assert inspect.isclass(klass)
    assert not inspect.isabstract(klass)
    assert issubclass(klass, ColumnBase)
    column = klass(sqlite_dialect(), "c")
    assert isinstance(column, ColumnBase)
    assert column.to_sql() == ('"c"', ())


@pytest.mark.parametrize("klass, entry", SURFACE_ONLY, ids=_IDS)
def test_each_class_carries_only_the_column_surface(klass, entry):
    """No comparison, no arithmetic, no string or JSON handling."""
    assert ComparisonMixin not in klass.__mro__
    column = klass(sqlite_dialect(), "c")
    assert not hasattr(column, "compare")
    assert not hasattr(column, "like")
    assert not hasattr(column, "add")
    # What it *does* carry is the shared column surface.
    assert hasattr(column, "is_null")
    assert hasattr(column, "is_not_null")
    assert hasattr(column, "as_")
    assert hasattr(column, "cast")


@pytest.mark.parametrize("klass, entry", SURFACE_ONLY, ids=_IDS)
def test_each_class_is_annotated_with_the_surface_only_answer(klass, entry):
    """The invariant test also asks this; asserting the exact answer pins it."""
    assert annotation_for(klass(sqlite_dialect(), "c")) is SurfaceOnlyAnnotation


def test_the_annotation_names_the_value_type_it_carries():
    """CASE and CAST read the value type off the annotation, so it must resolve."""
    assert SurfaceOnlyAnnotation.value_type_of() is SurfaceOnlyValue


def test_the_annotation_renders_its_source():
    """An annotation is a node: it wraps what it types and renders it."""
    from rhosocial.activerecord.backend.expression import Column

    dialect = sqlite_dialect()
    annotated = SurfaceOnlyAnnotation(dialect, Column(dialect, "c", table="t"))
    assert annotated.to_sql() == ('"t"."c"', ())


def test_the_annotation_renders_an_aliasless_source():
    """The wrapped node need not expose an ``alias`` slot at all.

    A Literal renders a value and has no column-like surface, so reading
    ``source.alias`` unconditionally raised AttributeError here.
    """
    from rhosocial.activerecord.backend.expression import Literal

    dialect = sqlite_dialect()
    annotated = SurfaceOnlyAnnotation(dialect, Literal(dialect, 1))
    assert annotated.to_sql() == ("?", (1,))


@pytest.mark.parametrize(
    "table, dialect_factory, expected",
    [
        (SQLITE_COLUMN_TYPES, sqlite_dialect, "sqlite"),
        (DUMMY_COLUMN_TYPES, dummy_dialect, "dummy"),
    ],
    ids=["sqlite", "dummy"],
)
def test_the_table_is_complete_and_refuses_nothing(table, dialect_factory, expected):
    """Twenty-four entries, none answered with ``None``."""
    assert set(table) == set(FRAMEWORK_PYTHON_TYPES)
    assert [key for key, value in table.items() if value is None] == []


@pytest.mark.parametrize("klass, entry", SURFACE_ONLY, ids=_IDS)
@pytest.mark.parametrize(
    "dialect_factory, expected",
    [(sqlite_dialect, "sqlite"), (dummy_dialect, "dummy")],
    ids=["sqlite", "dummy"],
)
def test_the_tables_resolve_to_the_new_class(klass, entry, dialect_factory, expected):
    assert resolve_column_class(dialect_factory(), entry) is klass


@pytest.mark.parametrize(
    "dialect_factory, table",
    [(sqlite_dialect, SQLITE_COLUMN_TYPES), (dummy_dialect, DUMMY_COLUMN_TYPES)],
    ids=["sqlite", "dummy"],
)
def test_every_answer_selects_to_a_buildable_column(dialect_factory, table):
    """Table completeness is only real if every answer builds and renders."""
    dialect = dialect_factory()
    for entry in FRAMEWORK_PYTHON_TYPES:
        column = resolve_column_class(dialect, entry)(dialect, "c")
        assert isinstance(column, ColumnBase)
        assert column.to_sql() == ('"c"', ())


def test_there_is_no_inherited_extra_table():
    """Core deleted its inherited table mixin: neither dialect learnt a fallback."""

    class Bare:
        def suggest_extra_column_types(self) -> ExtraColumnTypeSuggestion:
            return ExtraColumnTypeSuggestion(table={})

    assert Bare().suggest_extra_column_types().table == {}
