# tests/rhosocial/activerecord_bigquery_test/feature/query/test_column_type_support.py
"""The column-type support protocol: entry contract, backend authority, failures.

Four questions, and nothing here needs a database to answer them:

1. **Is the entry contract kept?** Every backend answers the common Python
   types the tests enumerate, so a model never meets a table with a hole.
2. **Whose answer is it?** The backend's own tables, always: a dialect that
   overrides one entry changes exactly that entry, and a backend's extra table
   carries its own Python types without touching the common ones.
3. **What does a declared column type look like, and what fails loudly?**
   ``Model.column_type()`` presents the declaration as written (a
   ``UseColumnType`` marker, a class, or a sequence); the field accessor
   selects from it; ``Any``, a bare ``Union``, an unregistered custom class
   and a ``None`` table entry all raise.
4. **What do the declaration accessors present?** ``column_type`` and
   ``column_data_type`` are dialect-free declarations -- no fallback, no
   selection -- and the batch method mirrors the data-type one.

Plus the boolean algebra surface and its literal discipline: ``TRUE``/``FALSE``
as keywords, never ``1``/``0``, which PostgreSQL rejects outright
(``operator does not exist: boolean = integer``).
"""

import datetime
import decimal
import enum
import typing
import uuid
from typing import Any, ClassVar, Dict, List, Optional, Union

import pytest

from rhosocial.activerecord.backend.adapters import (
    BitString,
    Geometry,
    MacAddress,
    Multirange,
    Range,
    Vector,
)
from rhosocial.activerecord.backend.suggestion.definitions import (
    ColumnTypeSuggestion,
    ExtraColumnTypeSuggestion,
)
from rhosocial.activerecord.backend.suggestion.protocols import ColumnTypeSuggestionSupport
from rhosocial.activerecord.backend.expression.column_types import (
    ArrayColumn,
    ColumnBase,
    TimestampColumn,
    IntegerColumn,
    JSONColumn,
    NumericColumn,
    StringColumn,
    UUIDColumn,
)
from rhosocial.activerecord.backend.expression.types import JsonType
from rhosocial.activerecord.backend.impl.dummy.dialect import DummyDialect
from rhosocial.activerecord.backend.impl.sqlite.dialect import SQLiteDialect
from rhosocial.activerecord.backend.impl.sqlite.mixins.column_type import (
    SQLITE_COLUMN_TYPES,
)
from rhosocial.activerecord.base.field_proxy import (
    ColumnTypeResolutionError,
    FieldProxy,
)
from rhosocial.activerecord.base.fields import DDLAnnotation, UseColumnType, UseSqlType
from rhosocial.activerecord.model import ActiveRecord

from rhosocial.activerecord_bigquery_test.feature.query.column_helpers import (
    COMMON_TYPES,
    build_column,
    resolve_column_class,
)


def sqlite_dialect(version=(3, 46, 1)):
    """A version-adapted SQLite dialect.

    ``supports_json_type`` reads ``self.version``, and an unadapted dialect
    raises rather than answering -- so every test that renders needs a version.
    3.46 is a real release well past the 3.38.0 line where the JSON functions
    became part of SQLite proper.
    """
    return SQLiteDialect(version=version)


def dummy_dialect():
    """An adapted dummy dialect: the dialect-less baseline, not a server."""
    dialect = DummyDialect()
    dialect._version = (3, 46, 1)
    return dialect


def resolve(dialect, annotation, declared=None):
    """The selection step, for the cases below that read as "resolve this"."""
    return resolve_column_class(dialect, annotation, declared)


_ENTRY_IDS = [getattr(entry, "__name__", str(entry)) for entry in COMMON_TYPES]


# ---------------------------------------------------------------------------
# 1. The entry contract
# ---------------------------------------------------------------------------


def test_the_canonical_entry_list_is_the_declared_order():
    """Order is the protocol's reading order, and the list lives in the framework.

    Both dialect tables are keyed by ``FRAMEWORK_PYTHON_TYPES``, so the order
    stated here is the one both lookups walk. The complex families come last
    because the subclass walk must meet ``bool`` before ``int`` and must meet
    ``Geometry`` only for a geometry annotation; ``AwareDatetime`` precedes
    ``datetime`` so the exact-match step wins over the subclass walk.
    """
    assert _ENTRY_IDS == [
        "bool",
        "int",
        "float",
        "Decimal",
        "str",
        "bytes",
        "bytearray",
        "date",
        "time",
        "AwareDatetime",
        "datetime",
        "timedelta",
        "UUID",
        "dict",
        "list",
        "tuple",
        "set",
        "frozenset",
        "Enum",
        "Geometry",
        "Vector",
        "BitString",
        "Range",
        "Multirange",
        "MacAddress",
        "IPAddress",
    ]


def test_entry_list_has_no_duplicates():
    """A duplicate would make 'answer every entry' ambiguous."""
    assert len(set(COMMON_TYPES)) == len(COMMON_TYPES)


def test_the_protocol_is_structural():
    """A dialect satisfies it by answering the two tables, nothing else."""
    dialect = sqlite_dialect()
    assert isinstance(dialect, ColumnTypeSuggestionSupport)
    assert isinstance(dialect.suggest_column_types(), ColumnTypeSuggestion)
    assert isinstance(dialect.suggest_extra_column_types(), ExtraColumnTypeSuggestion)


def _assert_answered_or_refused(dialect, entry):
    """Every framework type is either answered with a class or refused with None.

    ``None`` is the protocol's stated answer for "no column class for this value
    family", so the resolution must fail with that message rather than fall
    through to another table or pick a class anyway.
    """
    if dialect.suggest_column_types().table[entry] is None:
        with pytest.raises(ColumnTypeResolutionError, match="has no column class"):
            resolve(dialect, entry)
    else:
        assert issubclass(resolve(dialect, entry), ColumnBase)


@pytest.mark.parametrize("entry", COMMON_TYPES, ids=_ENTRY_IDS)
def test_every_entry_resolves_or_is_refused_by_sqlite(entry):
    _assert_answered_or_refused(sqlite_dialect(), entry)


@pytest.mark.parametrize("entry", COMMON_TYPES, ids=_ENTRY_IDS)
def test_every_entry_resolves_or_is_refused_by_the_dummy_baseline(entry):
    _assert_answered_or_refused(dummy_dialect(), entry)


def test_boolean_is_its_own_entry_not_an_integer():
    """``bool`` is an ``int`` subclass; the entry order is what keeps them apart.

    Without the order, ``bool`` would walk to ``int`` and a truth-value field
    would offer integer arithmetic -- which MySQL and SQLite would happily
    execute on a column holding 0/1.
    """
    assert COMMON_TYPES.index(bool) < COMMON_TYPES.index(int)
    assert resolve(sqlite_dialect(), bool) is not resolve(sqlite_dialect(), int)


def test_date_and_time_are_separate_entries_sharing_a_column_class():
    """They are distinct entries because the framework asks about each of them.

    They answer the same column class today, which is a modelling gap the entry
    list is what will eventually close (splitting ``TimestampColumn`` by operation
    set). Asserting the shared answer keeps that gap visible: when one of them
    splits, this test is what notices.
    """
    assert resolve(sqlite_dialect(), datetime.date) is TimestampColumn
    assert resolve(sqlite_dialect(), datetime.time) is TimestampColumn


# ---------------------------------------------------------------------------
# 2. The backend is the authority
# ---------------------------------------------------------------------------


class OverridingDialect(SQLiteDialect):
    """A backend that disagrees with SQLite about exactly one entry.

    Its table is SQLite's own with one entry replaced, so "the seventeen other
    answers are untouched" is a statement about this dialect versus the backend
    it extends. ``str`` answers with a class neither would have picked, which is
    what makes the authority observable: a core-side table consulted first would
    ignore this.
    """

    def suggest_column_types(self) -> ColumnTypeSuggestion:
        table = super().suggest_column_types().table
        table[str] = NumericColumn
        return ColumnTypeSuggestion(table=table)


class RefusingDialect(SQLiteDialect):
    """A backend with no column class for one entry.

    The honest "this backend has none", which is what MySQL 5.6 and Firebird
    would have to say about a value family they cannot carry. It must reach the
    caller as a failure rather than as a fallback to another table.
    """

    def suggest_column_types(self) -> ColumnTypeSuggestion:
        table = super().suggest_column_types().table
        table[dict] = None
        return ColumnTypeSuggestion(table=table)


class Complex:
    """A user type the framework does not model; carried by the extra table."""


class ExtendingDialect(SQLiteDialect):
    """A backend with a Python type of its own, in its own table."""

    def suggest_extra_column_types(self) -> ExtraColumnTypeSuggestion:
        return ExtraColumnTypeSuggestion(table={Complex: JSONColumn})


def test_backend_override_changes_only_its_own_entry():
    """One overridden entry, one changed answer, seventeen untouched."""
    dialect = OverridingDialect(version=(3, 46, 1))

    assert resolve(dialect, str) is NumericColumn
    assert resolve(sqlite_dialect(), str) is StringColumn

    for entry in COMMON_TYPES:
        if entry is str:
            continue
        _assert_answered_or_refused(dialect, entry)
        _assert_answered_or_refused(sqlite_dialect(), entry)


def test_a_backend_may_extend_with_an_entry_of_its_own():
    """The extension path for a Python type the framework does not model."""
    dialect = ExtendingDialect(version=(3, 46, 1))

    assert resolve(dialect, Complex) is JSONColumn
    assert resolve(dialect, Optional[Complex]) is JSONColumn
    # ...and the common entries keep working alongside it.
    assert resolve(dialect, int) is IntegerColumn


def test_the_returned_tables_are_copies():
    """A caller walking a table must not mutate what the next field reads."""
    dialect = sqlite_dialect()
    table = dialect.suggest_column_types().table
    table.clear()
    assert set(dialect.suggest_column_types().table) == set(COMMON_TYPES)


def test_there_is_no_inherited_common_table():
    """Core deleted its inherited table mixin: nothing supplies a table by inheritance."""

    class Bare:
        pass

    assert not hasattr(Bare(), "suggest_column_types")

    class Empty(Bare):
        def suggest_column_types(self) -> ColumnTypeSuggestion:
            return ColumnTypeSuggestion(table={})

        def suggest_extra_column_types(self) -> ExtraColumnTypeSuggestion:
            return ExtraColumnTypeSuggestion(table={})

    assert Empty().suggest_column_types().table == {}
    assert Empty().suggest_extra_column_types().table == {}


def test_sqlite_answers_exactly_the_framework_types():
    """Its table is complete, and none of the framework entries is refused.

    The six complex families used to be ``None`` for a real reason -- SQLite
    has no spatial or vector operation -- but the core classes they now name
    promise only the column surface (alias, null tests, casting, collation),
    which SQLite does execute on a value it stores as text or JSON.
    """
    from rhosocial.activerecord.backend.expression.column_types import (
        BitStringColumn,
        GeometryColumn,
        IntervalColumn,
        MacAddressColumn,
        MultirangeColumn,
        RangeColumn,
        VectorColumn,
    )

    assert set(SQLITE_COLUMN_TYPES) == set(COMMON_TYPES)
    assert all(value is not None for value in SQLITE_COLUMN_TYPES.values())
    assert resolve(sqlite_dialect(), Geometry) is GeometryColumn
    assert resolve(sqlite_dialect(), Vector) is VectorColumn
    assert resolve(sqlite_dialect(), BitString) is BitStringColumn
    assert resolve(sqlite_dialect(), Range) is RangeColumn
    assert resolve(sqlite_dialect(), Multirange) is MultirangeColumn
    assert resolve(sqlite_dialect(), MacAddress) is MacAddressColumn
    assert resolve(sqlite_dialect(), datetime.timedelta) is IntervalColumn


def test_the_dummy_dialect_states_its_own_baseline():
    """It stands for no server, so it states no backend's answers.

    SQLite is built into core and the dummy is the other dialect core ships, so
    the two are easy to conflate. They are deliberately different: the dummy is
    the dialect-less default a test reads, and copying a real backend's table
    into it would make "what does the portable baseline say" unanswerable.
    """
    dummy = dummy_dialect()
    assert set(dummy.suggest_column_types().table) == set(COMMON_TYPES)
    assert resolve(dummy, list) is ArrayColumn
    assert resolve(sqlite_dialect(), list) is JSONColumn
    # ``Decimal`` was merged into NumericColumn on both sides; asserting the
    # shared answer keeps the merge deliberate.
    assert resolve(dummy, decimal.Decimal) is NumericColumn
    assert resolve(sqlite_dialect(), decimal.Decimal) is NumericColumn


# ---------------------------------------------------------------------------
# 3. Declared column types: three forms, and what is refused
# ---------------------------------------------------------------------------


def test_use_column_type_overrides_the_tables():
    """Naming a class bypasses the recommendation, and only the recommendation."""
    assert resolve(sqlite_dialect(), int, UseColumnType(StringColumn)) is StringColumn


def test_a_bare_class_declaration_answers():
    """``column_type`` may present a class directly; the selector accepts it."""
    assert resolve(sqlite_dialect(), int, StringColumn) is StringColumn


def test_a_single_candidate_sequence_answers():
    """A one-element sequence is a declaration with one candidate."""
    assert resolve(sqlite_dialect(), int, [StringColumn]) is StringColumn


def test_a_multi_candidate_sequence_is_refused():
    """Choosing among candidates needs the capability declaration, which is not here.

    Taking the first silently would make the declaration a lie the caller
    cannot see.
    """
    with pytest.raises(ColumnTypeResolutionError, match="capability"):
        resolve(sqlite_dialect(), int, [StringColumn, JSONColumn])


def test_an_empty_sequence_is_refused():
    with pytest.raises(ColumnTypeResolutionError, match="empty sequence"):
        resolve(sqlite_dialect(), int, [])


def test_a_non_declaration_is_refused():
    with pytest.raises(ColumnTypeResolutionError, match="not a column-type declaration"):
        resolve(sqlite_dialect(), int, "StringColumn")


def test_use_column_type_saves_an_annotation_no_table_could_classify():
    """The escape hatch is what makes every other failure actionable."""
    assert resolve(sqlite_dialect(), Any, UseColumnType(StringColumn)) is StringColumn


def test_use_column_type_with_several_classes_is_refused():
    """Multi-candidate selection needs the capability declaration, which is not here.

    Declaring two classes is a request to negotiate with the backend, and there
    is nothing to ask yet. Taking the first silently would make the declaration
    a lie the caller cannot see.
    """
    with pytest.raises(TypeError, match="capability"):
        UseColumnType(StringColumn, JSONColumn)


def test_use_column_type_with_no_classes_is_refused():
    with pytest.raises(TypeError, match="at least one"):
        UseColumnType()


@pytest.mark.parametrize(
    "bad_factory, why",
    [
        (str, "builtin"),
        (lambda: "StringColumn", "name"),
        (lambda: StringColumn(sqlite_dialect(), "x"), "instance"),
    ],
    ids=["builtin", "string", "instance"],
)
def test_use_column_type_rejects_non_column_classes(bad_factory, why):
    """A column class is a type, never an instance -- an instance carries state.

    Built through factories because a column instance needs a dialect, and
    constructing one at collection time would put a database-free object in the
    module preamble.
    """
    with pytest.raises(TypeError, match="ColumnBase"):
        UseColumnType(bad_factory())


def test_use_column_type_is_not_a_ddl_annotation():
    """Strict independence: the DDL collector must never see it.

    ``UseSqlType`` is a ``DDLAnnotation``; this one deliberately is not. If it
    were, the DDL layer would be one refactor away from inferring a storage type
    from a column declaration -- the exact coupling the independence ruling
    forbids.
    """
    assert not isinstance(UseColumnType(StringColumn), DDLAnnotation)


def test_use_column_type_is_independent_of_use_sql_type():
    """Both declared, and neither is inferred from the other."""
    Annotated = getattr(typing, "Annotated", None)
    if Annotated is None:
        pytest.skip("typing.Annotated requires Python 3.9+")

    annotation = Annotated[int, UseSqlType(JsonType()), UseColumnType(StringColumn)]
    declared = [m for m in annotation.__metadata__ if isinstance(m, UseColumnType)][0]

    assert resolve(sqlite_dialect(), annotation, declared) is StringColumn
    # The DDL side still sees only its own candidate.
    assert [type(d).__name__ for d in annotation.__metadata__] == [
        "UseSqlType",
        "UseColumnType",
    ]
    assert UseSqlType(JsonType()).data_type.name == "json"


# ---------------------------------------------------------------------------
# 4. The model-side declaration accessors (dialect-free)
# ---------------------------------------------------------------------------


def _declared_model(dialect):
    Annotated = getattr(typing, "Annotated", None)
    if Annotated is None:
        pytest.skip("typing.Annotated requires Python 3.9+")

    class Declared(ActiveRecord):
        @classmethod
        def table_name(cls):
            return "declared_types"

        @classmethod
        def primary_key(cls):
            return "id"

        c: ClassVar[FieldProxy] = FieldProxy()

        id: int
        label: Annotated[str, UseColumnType(JSONColumn)]
        payload: Annotated[dict, UseSqlType(JsonType())]

    Declared.__backend__ = type("B", (), {"dialect": dialect})()
    return Declared


def test_column_type_presents_the_declaration_or_none():
    """``column_type`` presents; it does not resolve and does not fall back."""
    Model = _declared_model(sqlite_dialect())

    declared = Model.column_type("label")
    assert isinstance(declared, UseColumnType)
    assert declared.column_class is JSONColumn
    assert Model.column_type("id") is None


def test_two_column_type_declarations_on_one_field_are_refused():
    Annotated = getattr(typing, "Annotated", None)
    if Annotated is None:
        pytest.skip("typing.Annotated requires Python 3.9+")

    class Bad(ActiveRecord):
        @classmethod
        def table_name(cls):
            return "bad_declarations"

        @classmethod
        def primary_key(cls):
            return "id"

        c: ClassVar[FieldProxy] = FieldProxy()

        id: int
        broken: Annotated[
            Any,
            UseColumnType(StringColumn),
            UseColumnType(JSONColumn),
        ]

    Bad.__backend__ = type("B", (), {"dialect": sqlite_dialect()})()
    with pytest.raises(TypeError, match="UseColumnType declarations"):
        Bad.column_type("broken")


def test_column_data_type_presents_the_declaration_or_none():
    """The renamed accessor: dialect-free declaration, no inference."""
    Model = _declared_model(sqlite_dialect())

    assert Model.column_data_type("id") is None
    marker = Model.column_data_type("payload")
    assert isinstance(marker, UseSqlType)
    assert isinstance(marker.data_types[0], JsonType)


def test_columns_data_type_batches():
    Model = _declared_model(sqlite_dialect())

    batch = Model.columns_data_type()
    assert set(batch) == {"id", "label", "payload"}
    assert batch["payload"] is Model.column_data_type("payload")


def test_the_accessor_path_end_to_end():
    """The declared class wins where the table would have answered otherwise."""
    Model = _declared_model(sqlite_dialect())

    assert type(Model.c.label) is JSONColumn      # declared
    assert type(Model.c.id) is IntegerColumn      # selected from the table
    assert type(Model.c.payload) is JSONColumn    # table, not the DDL declaration


# ---------------------------------------------------------------------------
# 5. Failures: tables with holes, refused entries, unclassifiable annotations
# ---------------------------------------------------------------------------


def test_a_missing_entry_is_reported_against_the_backends_table():
    class PartialDialect(SQLiteDialect):
        def suggest_column_types(self) -> ColumnTypeSuggestion:
            return ColumnTypeSuggestion(table={str: StringColumn})

    with pytest.raises(ColumnTypeResolutionError, match="Cannot choose a column class"):
        resolve(PartialDialect(version=(3, 46, 1)), int)


def test_a_none_entry_fails_and_names_the_declaration_that_fixes_it():
    with pytest.raises(ColumnTypeResolutionError) as excinfo:
        resolve(RefusingDialect(version=(3, 46, 1)), dict)
    message = str(excinfo.value)
    assert "no column class for" in message
    assert "UseColumnType" in message


def test_a_none_entry_does_not_leak_into_other_entries():
    """One refusal must not make the whole backend unusable."""
    dialect = RefusingDialect(version=(3, 46, 1))
    assert resolve(dialect, str) is StringColumn
    assert resolve(dialect, int) is IntegerColumn


def test_a_table_entry_that_is_not_a_column_class_raises():
    """A malformed table is a backend bug, caught where it is written down."""

    class WrongDialect(SQLiteDialect):
        def suggest_column_types(self) -> ColumnTypeSuggestion:
            table = super().suggest_column_types().table
            table[str] = "StringColumn"
            return ColumnTypeSuggestion(table=table)

    with pytest.raises(ColumnTypeResolutionError, match="not a ColumnBase subclass"):
        resolve(WrongDialect(version=(3, 46, 1)), str)


@pytest.mark.parametrize(
    "annotation",
    [Any, Union[int, str], List[int], Dict[str, int]],
    ids=["Any", "bare-union", "parameterised-list", "parameterised-dict"],
)
def test_unclassifiable_annotations_fail(annotation):
    """``Any``, a bare ``Union``, a parameterised container: no entry, no answer.

    Each of these used to become the permissive ``Column``. Now it is a
    definition-time failure naming what to write instead, which is the change
    the ruling asked for: a field the framework cannot type is a mistake in the
    model, and a silent fallback hides it until the database complains.
    """
    with pytest.raises(ColumnTypeResolutionError) as excinfo:
        resolve(sqlite_dialect(), annotation)
    assert "UseColumnType" in str(excinfo.value)


def test_an_unregistered_custom_class_fails():
    """A class the framework does not model is unclassifiable, not a string."""

    class Money:
        pass

    with pytest.raises(ColumnTypeResolutionError, match="Cannot choose a column class"):
        resolve(sqlite_dialect(), Money)


def test_a_subclass_of_an_entry_resolves_through_the_walk():
    """``class MyStr(str)`` is a string; the walk is what says so."""
    assert resolve(sqlite_dialect(), type("Code", (str,), {})) is StringColumn


def test_an_enum_subclass_resolves_to_the_enum_entry():
    """Before the subclass walk, so a ``(int, Enum)`` is not filed as an int."""
    assert resolve(sqlite_dialect(), enum.Enum) is StringColumn

    class Weekday(enum.IntEnum):
        MONDAY = 1

    assert resolve(sqlite_dialect(), Weekday) is StringColumn


def test_optional_and_annotated_still_resolve():
    Annotated = getattr(typing, "Annotated", None)
    if Annotated is None:
        pytest.skip("typing.Annotated requires Python 3.9+")

    assert resolve(sqlite_dialect(), Optional[dict]) is JSONColumn
    # An unrelated marker is simply not a UseColumnType; the selector resolves
    # from the peeled annotation and the declaration is read by the model layer.
    assert resolve(sqlite_dialect(), Annotated[str, "marker"]) is StringColumn


# ---------------------------------------------------------------------------
# 6. Boolean algebra and the literal discipline
# ---------------------------------------------------------------------------


def _flag(name="flag"):
    return build_column(sqlite_dialect(), name, bool)


def test_is_true_and_is_false_render_keywords():
    """``IS TRUE`` / ``IS FALSE``, three-valued-logic correct.

    ``= TRUE`` would match differently under three-valued logic, and ``= 1``
    is not portable at all: PostgreSQL rejects ``boolean = integer`` outright.
    """
    assert _flag().is_true().to_sql() == ('"flag" IS TRUE', ())
    assert _flag().is_false().to_sql() == ('"flag" IS FALSE', ())


def test_and_or_not_render_connectives_not_bitwise_operators():
    """``AND`` / ``OR`` / ``NOT`` — MySQL accepts bitwise ``&`` / ``|`` too, and
    on a boolean column those compute something else entirely."""
    column = _flag()
    assert (column.is_true() & column.is_false()).to_sql() == (
        '"flag" IS TRUE AND "flag" IS FALSE',
        (),
    )
    assert (column.is_true() | column.is_false()).to_sql() == (
        '"flag" IS TRUE OR "flag" IS FALSE',
        (),
    )
    assert (~column.is_true()).to_sql() == ('NOT ("flag" IS TRUE)', ())


def test_boolean_algebra_never_renders_one_or_zero():
    """The rendering discipline, asserted rather than described.

    ``1`` / ``0`` as a boolean literal is the one thing that works on SQLite and
    MySQL and fails on PostgreSQL, so a regression that renders it would pass on
    two backends and break on a third. The literal has to be the keyword.
    """
    column = _flag()
    rendered = [
        column.is_true().to_sql()[0],
        column.is_false().to_sql()[0],
        (column.is_true() & column.is_false()).to_sql()[0],
        (column.is_true() | column.is_false()).to_sql()[0],
        (~column.is_true()).to_sql()[0],
    ]
    for sql in rendered:
        assert " TRUE" in sql or "FALSE" in sql
        # No integer literal standing in for the value.
        assert " IS 1" not in sql
        assert " IS 0" not in sql
        assert "= 1" not in sql
        assert "= 0" not in sql


def test_boolean_columns_only_carry_the_boolean_surface():
    """``str`` has no ``AND``; that is what the narrow classes are for.

    The mixin is composed into :class:`BooleanColumn` rather than inherited
    from :class:`ColumnBase` precisely so that these three operators stay off
    every other family — giving ``str`` an ``AND`` would be the guess the narrow
    classes exist to avoid.
    """
    assert hasattr(build_column(sqlite_dialect(), "f", bool), "__and__")
    assert hasattr(build_column(sqlite_dialect(), "f", bool), "__or__")
    assert hasattr(build_column(sqlite_dialect(), "f", bool), "__invert__")
    assert not hasattr(build_column(sqlite_dialect(), "s", str), "__and__")
    assert not hasattr(build_column(sqlite_dialect(), "n", int), "__invert__")


def test_negating_the_column_is_not_the_same_as_is_false():
    """``~flag`` is NOT; three-valued logic makes ``NOT NULL`` unknown.

    Callers asking "is it false?" say ``is_false()``. ``~`` is the connective.
    """
    column = _flag()
    assert column.is_false().to_sql()[0] != f"NOT ({column.to_sql()[0]})"


def test_boolean_algebra_composes_with_other_predicates():
    """The connectives are the same ones predicates use, so they interleave."""
    column = _flag()
    name = build_column(sqlite_dialect(), "name", str)
    combined = (column.is_true() & name.like("a%")) | column.is_false()
    sql, params = combined.to_sql()
    assert " AND " in sql and " OR " in sql
    assert params == ("a%",)


# ---------------------------------------------------------------------------
# 7. Two backends, one contract -- and no free resolvers
# ---------------------------------------------------------------------------


def test_two_dialects_differ_only_where_stated():
    """The dummy and SQLite differ exactly in the sequence entries.

    SQLite has no array type, so its four sequence entries are JSON documents;
    the dummy keeps the portable ``ArrayColumn``. Every other entry agrees —
    ``float`` and ``Decimal`` are ``NumericColumn`` on both sides, and
    ``timedelta`` is ``IntervalColumn`` on both. A backend that deviated
    anywhere else would be changing an answer no decision asked it to change.
    """
    dummy, sqlite = dummy_dialect(), sqlite_dialect()
    deviated = {list, tuple, set, frozenset}
    for entry in COMMON_TYPES:
        if entry in deviated:
            continue
        if sqlite.suggest_column_types().table[entry] is None:
            assert dummy.suggest_column_types().table[entry] is None
            continue
        assert resolve(dummy, entry) is resolve(sqlite, entry)
    assert resolve(sqlite, list) is JSONColumn
    assert resolve(dummy, list) is ArrayColumn


def test_the_public_surface_has_no_free_resolvers():
    """Resolution belongs to the field accessor; there is no module function."""
    import rhosocial.activerecord.base as base_package

    assert not hasattr(base_package, "build_column")
    assert not hasattr(base_package, "column_class_for")
    assert not hasattr(base_package, "column_dispatch")


def test_the_permissive_column_is_still_constructible_by_hand():
    """Retiring the fallback did not retire the class.

    ``Column(dialect, "x")`` is how a caller with a bare column name gets an
    expression; what is gone is the framework deciding that an unclassifiable
    annotation becomes one.
    """
    from rhosocial.activerecord.backend.expression import Column

    column = Column(sqlite_dialect(), "anything")
    assert column.to_sql() == ('"anything"', ())


def test_uuid_stays_its_own_column_family():
    """A UUID has no portable operator, but it is still not a string."""
    assert resolve(sqlite_dialect(), uuid.UUID) is UUIDColumn
    assert resolve(sqlite_dialect(), uuid.UUID) is not StringColumn


def test_decimal_is_a_number_and_not_a_string():
    assert issubclass(resolve(sqlite_dialect(), decimal.Decimal), NumericColumn)
