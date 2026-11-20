# tests/rhosocial/activerecord_bigquery_test/feature/query/test_typed_columns.py
"""Type-narrowed column expressions.

The column a model field resolves to depends on the field's Python
annotation, so a numeric field offers arithmetic and no ``.like()``, a JSON
field offers path access, and so on. These tests pin the selection the field
accessor makes, the narrowing it produces, and the guarantees that make it
safe to rely on.

No database is involved — every assertion is on the expression tree or the
SQL a dialect produces from it — so no provider fixture is required.
"""

import datetime
import decimal
import typing
import uuid
from typing import Any, ClassVar, Dict, List, Optional, Union

import pytest

from rhosocial.activerecord.backend.expression import (
    ArrayColumn,
    BinaryColumn,
    BooleanColumn,
    Column,
    ColumnBase,
    TimestampColumn,
    IntegerColumn,
    IntervalColumn,
    JSONColumn,
    NumericColumn,
    StringColumn,
    UUIDColumn,
    build_json_path,
)
from rhosocial.activerecord.backend.impl.sqlite.dialect import SQLiteDialect
from rhosocial.activerecord.base.field_proxy import (
    ColumnTypeResolutionError,
    FieldAccessor,
    FieldProxy,
)
from rhosocial.activerecord.base.fields import UseColumnType
from rhosocial.activerecord.model import ActiveRecord

from rhosocial.activerecord_bigquery_test.feature.query.column_helpers import (
    build_column,
    resolve_column_class,
)


def column_class_for(annotation, dialect=None):
    """The class the field accessor's selection picks for *annotation*.

    A one-line shim so the cases below read as "resolve this annotation" the
    way ``Model.c.<field>`` does it. The selection lives on
    :class:`FieldAccessor`; a free framework-level function would have to
    invent a backend or reach for a core-side table, which is the
    core-authority shape the architecture removed.
    """
    if dialect is None:
        dialect = sqlite_dialect()
    return resolve_column_class(dialect, annotation)


def sqlite_dialect():
    """A version-adapted SQLite dialect.

    ``supports_json_*`` reads ``self.version``, so the dialect must be
    adapted before any rendering; 3.46 satisfies every gate these tests
    exercise (JSON arrows need 3.38).
    """
    dialect = SQLiteDialect()
    dialect._version = (3, 46, 1)
    return dialect


# ---------------------------------------------------------------------------
# Selection: annotation -> column class
# ---------------------------------------------------------------------------

_DISPATCH = [
    (str, StringColumn),
    (int, IntegerColumn),
    (float, NumericColumn),
    (bool, BooleanColumn),
    (bytes, BinaryColumn),
    (dict, JSONColumn),
    # No array type exists in SQLite, so a `list` field is a JSON document here
    # rather than an ArrayColumn. The same model on PostgreSQL gets a real array;
    # that divergence is the protocol working, not a bug (see
    # `test_column_type_support.py`).
    (list, JSONColumn),
    (decimal.Decimal, NumericColumn),
    (datetime.datetime, TimestampColumn),
    (datetime.date, TimestampColumn),
    (datetime.timedelta, IntervalColumn),
    (uuid.UUID, UUIDColumn),
]


@pytest.mark.parametrize("annotation, expected", _DISPATCH, ids=lambda v: getattr(v, "__name__", str(v)))
def test_dispatch_by_annotation(annotation, expected):
    assert column_class_for(annotation) is expected


@pytest.mark.parametrize(
    "annotation",
    [
        Optional[str],
        Optional[dict],
    ],
    ids=lambda v: str(v),
)
def test_optional_annotations_resolve_to_the_inner_entry(annotation):
    assert column_class_for(annotation) in {StringColumn, JSONColumn}


@pytest.mark.parametrize(
    "annotation",
    [
        List[int],  # a parameterised container is not classifiable
        Dict[str, int],
        Union[int, str],  # genuinely ambiguous
        Any,
    ],
    ids=lambda v: str(v),
)
def test_unclassifiable_annotations_fail(annotation):
    """No guessing, and no escape: each of these raises at build time.

    This is the "全量或失败" ruling. These four used to become the permissive
    ``Column``, which offered every operation to a value whose type nothing was
    known about — so ``Model.c.meta.like('%x%')`` rendered happily and failed at
    the database, with the error pointing at the SQL rather than at the
    annotation that caused it. Narrowing exists to catch that at the point the
    field is declared, so a hole in it is a hole in the guarantee.

    ``UseColumnType`` is the way through: it says which operations the value
    carries, which is a statement the framework can honour on any backend.
    """
    with pytest.raises(ColumnTypeResolutionError) as excinfo:
        column_class_for(annotation)
    assert "UseColumnType" in str(excinfo.value)


def test_optional_and_annotated_are_stripped():
    # typing.Annotated arrived in 3.9 and this project supports 3.8, so the
    # alias is built the way the runtime marks one on every version.
    Annotated = getattr(typing, "Annotated", None)
    if Annotated is None:
        pytest.skip("typing.Annotated requires Python 3.9+")

    strip = FieldAccessor._strip_annotation
    assert strip(Optional[dict]) is dict
    assert strip(Annotated[str, "some-marker"]) is str
    assert strip(Optional[Annotated[str, "m"]]) is str


# ---------------------------------------------------------------------------
# Narrowing: each family offers only what its value type supports
# ---------------------------------------------------------------------------


def test_string_column_has_like_but_no_arithmetic():
    col = build_column(sqlite_dialect(), "name", str)
    assert isinstance(col, StringColumn)
    assert hasattr(col, "like") and hasattr(col, "ilike")

    # Arithmetic is refused explicitly rather than left absent: the operator is
    # looked up on the type by the interpreter, so a missing one produces
    # CPython's own TypeError instead of the package's message. hasattr is true
    # because the method exists to raise, which is why the check calls it.
    with pytest.raises(AttributeError):
        col + 1
    with pytest.raises(AttributeError):
        col * 2


def test_integer_column_has_arithmetic_but_no_like():
    col = build_column(sqlite_dialect(), "age", int)
    assert isinstance(col, IntegerColumn)
    assert hasattr(col, "__add__") and hasattr(col, "__mul__")
    assert not hasattr(col, "like")


def test_json_column_has_path_access_only():
    col = build_column(sqlite_dialect(), "settings", dict)
    assert isinstance(col, JSONColumn)
    assert hasattr(col, "json_path") and hasattr(col, "json_value")
    assert not hasattr(col, "like")
    assert not hasattr(col, "__add__")


def test_uuid_column_offers_no_uuid_specific_operator():
    """Portable SQL has none, so a UUID column is just a value column."""
    col = build_column(sqlite_dialect(), "uid", uuid.UUID)
    assert isinstance(col, UUIDColumn)
    assert not hasattr(col, "like")
    assert not hasattr(col, "json_path")
    with pytest.raises(AttributeError):
        col + 1


def test_bare_column_offers_no_operation():
    """The hand-built ``Column`` is a reference, and references do not guess.

    Nothing established what the column holds, so offering an operation
    would be a promise the database never made — and the previous shape had
    the failure the typed classes exist to prevent: comparing two of them
    answered Python's identity question silently. The class renders (its one
    job), the shared surface answers questions about the *reference* itself,
    and predicates are built explicitly where the column's type is unknown.
    """
    col = Column(sqlite_dialect(), "anything")
    assert col.to_sql() == ('"anything"', ())
    for operation in ("like", "__add__", "json_path", "in_", "upper"):
        assert not hasattr(col, operation), f"a bare column wrongly offers {operation}"


# ---------------------------------------------------------------------------
# Rendering: unchanged SQL, and a common format_column
# ---------------------------------------------------------------------------

_RENDER_CLASSES = [
    Column, StringColumn, NumericColumn, TimestampColumn, BooleanColumn,
    BinaryColumn, UUIDColumn, JSONColumn, ArrayColumn,
]


@pytest.mark.parametrize("column_class", _RENDER_CLASSES, ids=lambda c: c.__name__)
def test_every_column_class_renders_identically(column_class):
    """Narrowing changed the API, not the SQL."""
    dialect = sqlite_dialect()
    col = column_class(dialect, "settings", table="t", schema_name="s")
    assert col.to_sql() == ('"s"."t"."settings"', ())


@pytest.mark.parametrize("column_class", _RENDER_CLASSES, ids=lambda c: c.__name__)
def test_every_column_class_is_a_column_base(column_class):
    """The 8 isinstance() consumers test for ColumnBase, so all must match."""
    assert isinstance(column_class(sqlite_dialect(), "x"), ColumnBase)


@pytest.mark.parametrize("column_class", _RENDER_CLASSES, ids=lambda c: c.__name__)
def test_qualified_and_aliased_rendering(column_class):
    dialect = sqlite_dialect()
    assert column_class(dialect, "c").to_sql() == ('"c"', ())
    assert column_class(dialect, "c", table="t").to_sql() == ('"t"."c"', ())
    assert column_class(dialect, "c", alias="a").to_sql() == ('"c" AS "a"', ())


# ---------------------------------------------------------------------------
# JSON path building
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "keys, expected",
    [
        ((), "$"),
        (("a",), "$.a"),
        (("a", "b"), "$.a.b"),
        (("tags", 0), "$.tags[0]"),
        (("a", 0, "b"), "$.a[0].b"),
        (("tags", "[0]"), "$.tags[0]"),
    ],
    ids=lambda v: str(v),
)
def test_build_json_path(keys, expected):
    assert build_json_path(*keys) == expected


def test_string_zero_is_a_key_not_an_index():
    """``"0"`` names a key; only an int is an index.

    ``$.tags.0`` is a key literally named ``0`` and matches nothing, so the
    distinction is carried by the type rather than the spelling.
    """
    assert build_json_path("tags", "0") == "$.tags.0"
    assert build_json_path("tags", 0) == "$.tags[0]"


def test_bool_is_rejected_as_a_path_segment():
    """bool is an int subclass; silently treating True as index 1 is a trap."""
    with pytest.raises(TypeError, match="bool"):
        build_json_path("a", True)


def test_json_path_renders_bracket_for_integer_index():
    dialect = sqlite_dialect()
    col = build_column(dialect, "settings", dict)
    assert col.json_path("tags", 0).to_sql() == ('"settings"->>\'$.tags[0]\'', ())


def test_json_path_chains_without_renesting_the_path():
    """Chaining accumulates; it must not re-anchor the second path at ``$``."""
    dialect = sqlite_dialect()
    col = build_column(dialect, "settings", dict)
    assert col.json_value("a").json_value("b").to_sql() == (
        '"settings"->\'$.a\'->\'$.b\'',
        (),
    )


def test_json_path_alias_lands_on_the_outermost_form():
    dialect = sqlite_dialect()
    col = build_column(dialect, "settings", dict)
    assert col.as_("j").json_path("a").to_sql() == ('"settings"->>\'$.a\' AS "j"', ())


# ---------------------------------------------------------------------------
# End to end through FieldProxy
# ---------------------------------------------------------------------------


def _annotated():
    """``typing.Annotated``, or a skip — the alias is 3.9+ and this file is 3.8-safe."""
    alias = getattr(typing, "Annotated", None)
    if alias is None:
        pytest.skip("typing.Annotated requires Python 3.9+")
    return alias


def _model(dialect):
    Annotated = _annotated()

    class Widget(ActiveRecord):
        @classmethod
        def table_name(cls):
            return "typed_widget"

        @classmethod
        def primary_key(cls):
            return "id"

        c: ClassVar[FieldProxy] = FieldProxy()

        id: int
        name: str
        qty: int
        price: decimal.Decimal
        created: datetime.datetime
        settings: dict
        tags: list
        uid: uuid.UUID
        flag: bool
        # `Any` is not classifiable, so this field has to say what its value can
        # do. The declaration is the whole point: without it the field does not
        # resolve at all, which is the "全量或失败" ruling applied to a model.
        meta: Annotated[Any, UseColumnType(JSONColumn)]

    Widget.__backend__ = type("B", (), {"dialect": dialect})()
    return Widget


@pytest.mark.parametrize(
    "field, expected",
    [
        ("id", IntegerColumn),
        ("name", StringColumn),
        ("qty", IntegerColumn),
        ("price", NumericColumn),
        ("created", TimestampColumn),
        ("settings", JSONColumn),
        ("tags", JSONColumn),
        ("uid", UUIDColumn),
        ("flag", BooleanColumn),
        ("meta", JSONColumn),        # Any, resolved through UseColumnType
    ],
)
def test_field_proxy_returns_the_matching_class(field, expected):
    Widget = _model(sqlite_dialect())
    assert type(getattr(Widget.c, field)) is expected


def test_field_proxy_refuses_an_undeclared_any():
    """A model field typed ``Any`` with no declaration fails where it is read.

    The proxy is where a column is built, so this is the earliest point at which
    the model can be told — and telling it here beats a driver error naming a
    column at query time.
    """

    class Loose(ActiveRecord):
        @classmethod
        def table_name(cls):
            return "typed_loose"

        @classmethod
        def primary_key(cls):
            return "id"

        c: ClassVar[FieldProxy] = FieldProxy()

        id: int
        meta: Any

    Loose.__backend__ = type("B", (), {"dialect": sqlite_dialect()})()
    with pytest.raises(ColumnTypeResolutionError, match="UseColumnType"):
        # The proxy builds the column on attribute access, so the bare
        # expression is the call under test -- the same shape as the
        # AttributeError case below it.
        Loose.c.meta  # noqa: B018


def test_field_proxy_query_uses_narrowed_operations():
    dialect = sqlite_dialect()
    Widget = _model(dialect)
    sql, params = Widget.query().where(Widget.c.settings.json_path("lang") == "en").to_sql()
    assert sql == """SELECT * FROM "typed_widget" WHERE "typed_widget"."settings"->>'$.lang' = ?"""
    assert params == ("en",)


def test_field_proxy_unknown_field_still_raises_attribute_error():
    Widget = _model(sqlite_dialect())
    with pytest.raises(AttributeError, match="does not exist on model"):
        Widget.c.no_such_field
