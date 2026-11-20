# tests/rhosocial/activerecord_bigquery_test/feature/query/test_value_family_inference.py
"""Result families, and the lattice they add up to.

A family is what decides an expression's operation surface, and it has to be
accurate in both directions. Over-narrowing removes a legal operation;
over-widening offers an illegal one. Both failures are silent — the SQL is
still produced, it is just wrong — so the families are pinned here.

The distinction that matters most is whole number against fraction. ``int`` and
``float`` share a column class, so the family has to come from the annotation
rather than the class, or "integer in, integer out" cannot be expressed and
``ceil`` of an integer claims to be fractional.
"""

# tests/rhosocial/activerecord_bigquery_test/feature/query/test_value_family_inference.py
import datetime
import uuid

import pytest

from rhosocial.activerecord.backend.expression import Column, FunctionCall
from rhosocial.activerecord.backend.expression import functions as F
from rhosocial.activerecord.backend.expression.column_types import annotation_for
from rhosocial.activerecord.backend.expression.declared import (
    ArrayAnnotation,
    BinaryAnnotation,
    BooleanAnnotation,
    IntegerAnnotation,
    JSONAnnotation,
    NumberAnnotation,
    TemporalAnnotation,
    TextAnnotation,
    UUIDAnnotation,
    XMLAnnotation,
)

#: Every value class the lattice holds, for the "declares nothing" assertions.
TYPED_VALUE_CLASSES = (
    ArrayAnnotation,
    BinaryAnnotation,
    BooleanAnnotation,
    IntegerAnnotation,
    JSONAnnotation,
    NumberAnnotation,
    TemporalAnnotation,
    TextAnnotation,
    UUIDAnnotation,
    XMLAnnotation,
)


@pytest.fixture
def dialect():
    from rhosocial.activerecord.backend.impl.sqlite.dialect import SQLiteDialect

    d = SQLiteDialect()
    d._version = (3, 46, 1)
    return d


@pytest.fixture
def columns(dialect):
    from rhosocial.activerecord_bigquery_test.feature.query.column_helpers import build_column

    return {
        "string": build_column(dialect, "s", str),
        "int": build_column(dialect, "i", int),
        "float": build_column(dialect, "f", float),
        "bool": build_column(dialect, "b", bool),
        "json": build_column(dialect, "j", dict),
        "bytes": build_column(dialect, "y", bytes),
        "uuid": build_column(dialect, "u", uuid.UUID),
        "datetime": build_column(dialect, "d", datetime.datetime),
    }


# ---------------------------------------------------------------------------
# A column's family comes from its annotation
# ---------------------------------------------------------------------------


def test_every_column_class_has_an_annotation(columns):
    """The map is complete, so no column class is silently untyped.

    There is no registry of family *names* to be complete any more -- a type is
    a class. But there is a table from column class to value class (see
    ``column_types.annotation_for``), and a column class missing from it would
    make every operation over that column quietly untyped, which is the failure
    this file exists to catch. So it is checked here instead of assumed.
    """
    import inspect

    from rhosocial.activerecord.backend.expression import column_types as CT

    declared = {
        name
        for name, klass in vars(CT).items()
        if inspect.isclass(klass)
        and issubclass(klass, CT.ColumnBase)
        and klass is not CT.ColumnBase
    }
    assert declared, "the typed column classes moved"
    for name in sorted(declared):
        column = getattr(CT, name).__new__(getattr(CT, name))
        assert annotation_for(column) is not None, f"{name} has no annotation"
    # The base is now an ABC, so there is no "untyped column object" left to
    # map -- not being able to build one is the stronger form of the same
    # invariant.  The untyped column that *can* be built is the bare ``Column``,
    # which lives outside this module, and staying unmapped is still the point.
    assert inspect.isabstract(CT.ColumnBase), "the typed base must not be instantiable"
    from rhosocial.activerecord.backend.expression import Column as BareColumn

    assert annotation_for(BareColumn.__new__(BareColumn)) is None


def test_every_core_data_type_has_an_annotation_or_is_explicitly_impossible():
    """The DDL-type -> value-class map is closed, so a cast cannot go silently
    untyped.

    There is a second completeness question beside the column one above, and it
    is asked of the *target* side of a cast: ``cast`` answers from the class of
    the ``DataType`` it was handed (``type_conversion._type_annotations()``),
    so a core type missing from that table would make every cast to it come
    back untyped and the operations its value supports invisible. A type added
    to the core without a map entry must therefore be a test failure here, not
    a quiet degradation.

    The loop walks every concrete core ``DataType`` currently loaded rather
    than a hand-kept list, so a new core type file cannot dodge it by not being
    imported.

    ``CustomType`` is the one deliberate exception and is asserted as such: it
    is the escape hatch for a name this library does not model, so there is no
    family it could honestly promise operations on (see its docstring), and the
    map deliberately leaves it out.
    """
    import inspect

    from rhosocial.activerecord.backend.expression import types as core_types
    from rhosocial.activerecord.backend.expression.functions.type_conversion import (
        _type_annotations,
    )

    core_prefix = "rhosocial.activerecord.backend.expression.types"
    seen = set()
    stack = [core_types.DataType]
    while stack:
        klass = stack.pop()
        if klass in seen:
            continue
        seen.add(klass)
        stack.extend(klass.__subclasses__())
    declared = {
        klass.__name__: klass
        for klass in seen
        if klass is not core_types.DataType
        and not inspect.isabstract(klass)
        and klass.__module__.startswith(core_prefix)
    }
    assert declared, "the core types moved"

    mapping = _type_annotations()
    # The exception, stated rather than merely skipped. ``CustomType`` is the
    # escape hatch for a type nobody here has heard of; mapping it to any value
    # class would offer operations the database may reject. Asserting it stays
    # unmapped is what keeps the exception the only one.
    assert core_types.CustomType in declared.values()
    assert core_types.CustomType not in mapping, (
        "CustomType must not map to a value class: it exists precisely because "
        "nothing here knows what the type is, so no value surface can be "
        "claimed for it"
    )

    for name, klass in sorted(declared.items()):
        if klass is core_types.CustomType:
            continue
        assert any(base in mapping for base in klass.__mro__), (
            f"{name} has no annotation: add it to "
            f"functions/type_conversion._type_annotations(), or add it to "
            f"the deliberate-exception list here with the reason it cannot "
            f"honestly have one"
        )


def test_a_bare_function_call_has_no_family(dialect, columns):
    """It says nothing about what a database would return."""
    call = FunctionCall(dialect, "MY_FUNC", columns["string"])
    assert not isinstance(call, TYPED_VALUE_CLASSES)


def test_a_hand_written_column_has_no_family(dialect):
    """A permissive Column means "unknown type", which is not the same as any."""
    assert not isinstance(Column(dialect, "x", table="t"), TYPED_VALUE_CLASSES)


@pytest.mark.parametrize(
    "key, expected",
    [
        ("string", TextAnnotation),
        ("int", IntegerAnnotation),
        ("float", NumberAnnotation),
        ("bool", BooleanAnnotation),
        ("json", JSONAnnotation),
        ("bytes", BinaryAnnotation),
        ("uuid", UUIDAnnotation),
        ("datetime", TemporalAnnotation),
    ],
)
def test_each_annotation_lands_in_its_type(columns, key, expected):
    """The annotation picks the column class, and the class picks the annotation.

    This used to compare against a family *name* read off an attribute. The
    attribute is gone and the class is the whole of it, so the assertion is the
    annotation an operation over that column now returns.
    """
    assert annotation_for(columns[key]) is expected


def test_a_disagreement_yields_no_type(dialect, columns):
    """GREATEST of an integer and a string is legal SQL and is neither, so the
    call stays generic rather than promising the first or the widest."""
    mixed = F.greatest(dialect, columns["int"], columns["string"])
    assert not isinstance(mixed, TYPED_VALUE_CLASSES)
    assert mixed.to_sql() == FunctionCall(
        dialect, "GREATEST", columns["int"], columns["string"]
    ).to_sql()
