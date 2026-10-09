# tests/rhosocial/activerecord_bigquery_test/feature/backend/dialect/test_column_type.py
"""BigQuery's eighteen-entry column-type table.

Pure dialect tests -- no server, no emulator. What is asserted here is the
**declaration**: that the table answers every entry of the protocol's closed
list, that the cells BigQuery deviates on are the ones its documentation says
they should be, and that no entry is refused (``None``) where the server has a
documented type for the value family.

The evidence level of the whole table is 文档（待云验）. No BigQuery instance was
reachable while this was written, so nothing here was measured. These tests
therefore pin *what the backend claims and why*, never the server's agreement
with it; a scenario run is what would settle the latter, and the docstrings
name which claims are waiting for it. The rendering those cells imply is Phase
2b's work and is deliberately not asserted.

The older capability mechanism -- ``supports_column_operation`` -- is gone from
the rebuilt core together with its ``UNSUPPORTED`` sentinel, and has no test
here any more than it has a call site in the source.
"""

import datetime
import decimal
import enum
import inspect
import uuid

import pytest
from rhosocial.activerecord.backend.dialect.mixins import ColumnTypeMixin
from rhosocial.activerecord.backend.expression import column_types as core_column_types
from rhosocial.activerecord.backend.expression.column_types import (
    ArrayColumn,
    BinaryColumn,
    BooleanColumn,
    ColumnBase,
    DateTimeColumn,
    IntegerColumn,
    JSONColumn,
    NumericColumn,
    StringColumn,
    UUIDColumn,
)

from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect
from rhosocial.activerecord.backend.impl.bigquery.mixins import (
    BigQueryColumnTypeMixin,
)

#: The version the dialect is asked about. BigQuery's is a rolling service with
#: no per-release version string in the way PostgreSQL has one, so this is the
#: dialect's own default and nothing in the table branches on it.
DIALECT_VERSION = (3, 0, 0)

#: The common Python types every backend must answer, in the reading order the
#: protocol declares. Spelled out here rather than imported: the required key
#: set is a contract the tests state and hold each backend to, and this
#: repository shares no test package with the core repository that could lend
#: its copy.
COMMON_TYPES = (
    bool,
    int,
    float,
    decimal.Decimal,
    str,
    bytes,
    bytearray,
    datetime.date,
    datetime.time,
    datetime.datetime,
    datetime.timedelta,
    uuid.UUID,
    dict,
    list,
    tuple,
    set,
    frozenset,
    enum.Enum,
)

#: ``{entry: column class}`` as BigQuery states it. Written out in full rather
#: than derived, because a derived table would restate the code's own answer
#: back at itself and could not catch a change to it.
BIGQUERY_ANSWERS = [
    (bool, BooleanColumn),
    (int, IntegerColumn),
    (float, NumericColumn),
    (decimal.Decimal, NumericColumn),
    (str, StringColumn),
    (bytes, BinaryColumn),
    (bytearray, BinaryColumn),
    (datetime.date, DateTimeColumn),
    (datetime.time, DateTimeColumn),
    (datetime.datetime, DateTimeColumn),
    (datetime.timedelta, NumericColumn),
    (uuid.UUID, UUIDColumn),
    (dict, JSONColumn),
    (list, ArrayColumn),
    (tuple, ArrayColumn),
    (set, ArrayColumn),
    (frozenset, ArrayColumn),
    (enum.Enum, StringColumn),
]

_ENTRY_IDS = [getattr(entry, "__name__", str(entry)) for entry in COMMON_TYPES]

#: Every column class core declares, read off the module rather than restated.
#: Used to say "this backend invents no column class of its own", which is a
#: claim about the *whole* module and not about the cells named by hand above.
_CORE_COLUMN_CLASSES = frozenset(
    value
    for value in vars(core_column_types).values()
    if isinstance(value, type) and issubclass(value, ColumnBase)
)

#: This backend's column-type mixin, as a module rather than as a class, so the
#: docstrings and table comments can be read as the evidence they are.
_MIXIN_MODULE = __import__(BigQueryColumnTypeMixin.__module__, fromlist=["BigQueryColumnTypeMixin"])

#: The model layer's own selection step, invoked without a model -- the same
#: call ``Model.c.<field>`` makes, so the table is checked where it is consumed
#: rather than only where it is declared.
_RESOLVE = __import__(
    "rhosocial.activerecord.base.field_proxy", fromlist=["FieldAccessor"]
).FieldAccessor._select_column_class


@pytest.fixture
def dialect():
    return BigQueryDialect(version=DIALECT_VERSION)


def resolve(dialect, annotation):
    return _RESOLVE(dialect, annotation, None)


class TestTableCompleteness:
    """A hole in the table is a silent gap, and the protocol forbids one."""

    def test_the_dialect_carries_the_mixin(self, dialect):
        assert isinstance(dialect, BigQueryColumnTypeMixin)
        assert isinstance(dialect, ColumnTypeMixin)

    def test_the_bigquery_mixin_extends_the_core_mixin(self):
        """The base class is what supplies ``suggested_extra_column_types``.

        ``ColumnTypeMixin`` deliberately declares no common-type table, so the
        eighteen answers can only come from this backend's own override --
        which the next test then holds to.
        """
        assert issubclass(BigQueryColumnTypeMixin, ColumnTypeMixin)

    def test_every_entry_is_answered(self, dialect):
        """All eighteen, by name -- an omission fails here rather than at lookup."""
        missing = [e for e in COMMON_TYPES if e not in dialect.suggested_column_types()]
        assert missing == []

    def test_the_table_has_no_entry_beyond_the_contract(self, dialect):
        """A backend may extend the list with a type of its own; this one has none.

        Asserted so that an extension added later is a deliberate act with its
        own entry in this file, rather than a key that appears in the table and
        is never checked by anything.
        """
        assert set(dialect.suggested_column_types()) == set(COMMON_TYPES)

    def test_no_entry_is_answered_none(self, dialect):
        """``None`` is the last resort, and this backend never needs it.

        Firebird refuses ``dict`` and ``list`` (no JSON functions, no arrays);
        MySQL < 5.7 and MariaDB < 10.2 refuse ``dict``. BigQuery has a native
        ``ARRAY<T>`` in REPEATED mode and a documented non-Preview ``JSON``
        type, so answering ``None`` would state a limit this backend does not
        have -- as wrong as a hole.
        """
        table = dialect.suggested_column_types()
        assert [e for e in COMMON_TYPES if table[e] is None] == []

    @pytest.mark.parametrize("entry", COMMON_TYPES, ids=_ENTRY_IDS)
    def test_every_answer_is_a_column_class(self, dialect, entry):
        answer = dialect.suggested_column_types()[entry]
        assert isinstance(answer, type)
        assert issubclass(answer, ColumnBase)

    @pytest.mark.parametrize("entry", COMMON_TYPES, ids=_ENTRY_IDS)
    def test_every_entry_resolves_to_its_own_answer(self, dialect, entry):
        """Through the selection, not by reading the dict."""
        assert resolve(dialect, entry) is dialect.suggested_column_types()[entry]

    @pytest.mark.parametrize("entry", COMMON_TYPES, ids=_ENTRY_IDS)
    def test_every_answer_builds_a_column_that_renders(self, dialect, entry):
        """A table answer is only real if the column it names can be built."""
        column = resolve(dialect, entry)(dialect, "c")
        assert isinstance(column, ColumnBase)
        assert column.to_sql() == ("`c`", ())

    def test_the_table_is_a_copy(self, dialect):
        """Mutating the answer must not corrupt the module-level constant."""
        first = dialect.suggested_column_types()
        first[str] = JSONColumn
        assert dialect.suggested_column_types()[str] is StringColumn

    def test_the_extra_table_is_empty(self, dialect):
        """This backend models no Python type of its own.

        The core default is the honest one: a type the backend does not offer is
        simply absent, and inventing a vocabulary here would be the extension
        path nobody asked for.
        """
        assert dialect.suggested_extra_column_types() == {}

    @pytest.mark.parametrize("entry", COMMON_TYPES, ids=_ENTRY_IDS)
    def test_no_entry_answers_a_class_this_backend_defines(self, dialect, entry):
        """A backend-only column class would be the extension path, not a default.

        The table may hold a class core does not know -- that is how a backend
        with a Python type of its own registers it -- but this backend declares
        no ``DataType`` subclass and defines no column class of its own, so
        every answer is one core already has. This is also what keeps the
        ``dict`` cell honest: inventing a ``StructColumn`` here would be 议题 A's
        core-level decision made by accident, in a backend.
        """
        answer = dialect.suggested_column_types()[entry]
        assert answer in _CORE_COLUMN_CLASSES

    def test_the_capability_mechanism_is_gone(self, dialect):
        """``supports_column_operation`` was deleted from core, and stays deleted.

        It had drifted from real behaviour and had no production caller, so the
        narrowing it carried (``ilike`` on a string column) is recorded in the
        mixin's evidence comments instead of in a method a caller could consult
        and trust. A method of that name reappearing here would be a
        re-invention, not a restoration.
        """
        assert not hasattr(dialect, "supports_column_operation")
        assert not hasattr(BigQueryColumnTypeMixin, "supports_column_operation")


class TestBaselineCells:
    """The shared baseline, restated cell by cell."""

    @pytest.mark.parametrize("entry, expected", BIGQUERY_ANSWERS, ids=_ENTRY_IDS)
    def test_baseline_entry(self, dialect, entry, expected):
        assert dialect.suggested_column_types()[entry] is expected

    def test_the_two_numeric_entries_share_the_one_numeric_class(self, dialect):
        """``float`` and ``Decimal`` both answer ``NumericColumn``.

        Core declares one class for every numeric width and precision: the
        operations are the same whatever the value was declared as, and the
        difference between a ``NUMERIC(18,4)`` and a ``DOUBLE PRECISION``
        belongs to the DDL layer's ``DataType``. BigQuery's documented storage
        still splits them -- ``FLOAT64`` an approximate double, ``NUMERIC`` /
        ``BIGNUMERIC`` exact fixed-point declared with a precision and scale --
        and the two do not implicitly mix in arithmetic (待云验: the non-mixing
        is documented, not measured). That is a rendering obligation on the
        numeric formatters, not a different column surface.
        """
        table = dialect.suggested_column_types()
        assert table[float] is NumericColumn
        assert table[decimal.Decimal] is NumericColumn

    def test_int_is_a_whole_number_here_too(self, dialect):
        """No unsigned integer on this backend, so 议题 C does not arise.

        ClickHouse faces the question (whether ``UInt8..UInt256`` earns a
        column class); BigQuery's documented type list has no unsigned integer
        at all, so ``int`` is ``IntegerColumn`` with nothing open behind it.
        """
        assert dialect.suggested_column_types()[int] is IntegerColumn

    def test_uuid_stays_uuid_column_though_bigquery_has_no_uuid_type(self, dialect):
        """The column class is not the storage type, and the two are separate.

        BigQuery's documented type list has no UUID; ``GENERATE_UUID()`` yields
        a ``STRING``. ``UUIDColumn`` still carries no UUID-specific operator --
        portable SQL has none -- so a UUID column supports exactly what any
        other value column does, and the ``STRING`` spelling is the DataType
        layer's answer (this backend suggests ``uuid`` -> ``STRING`` there).
        """
        assert resolve(dialect, uuid.UUID) is UUIDColumn
        assert dialect.suggested_data_types()["uuid"].__name__ == "VarCharType"

    def test_date_and_time_are_provisional(self, dialect):
        """Core has no ``DateColumn`` / ``TimeColumn`` yet, so one class stands.

        Worth pinning because BigQuery has had native ``DATE`` and ``TIME`` for
        years (this repository's investigation appendix D-①) -- the shared
        answer is a core gap, not a statement about this backend.
        """
        table = dialect.suggested_column_types()
        assert table[datetime.date] is DateTimeColumn
        assert table[datetime.time] is DateTimeColumn

    def test_timedelta_is_numeric_because_intervals_are_function_shaped(self, dialect):
        """BigQuery expresses a duration as a function operand, not a column.

        ``DATE_ADD(date, INTERVAL n DAY)`` puts the unit in the function and
        the value in an ``INT64`` count, so no column type holds "a span". The
        standalone ``INTERVAL`` type does exist and is documented, but it is
        marked **Preview** and core has no ``IntervalColumn`` to aim at either
        way -- the ``IntervalColumn`` question rides with core.
        """
        assert dialect.suggested_column_types()[datetime.timedelta] is NumericColumn
        assert dialect.suggested_data_types()["interval"].__name__ == "IntegerType"

    def test_enum_is_a_string_because_bigquery_has_no_enum_type(self, dialect):
        """No ``ENUM`` in the documented type list; the value is stored as text.

        The column class is unaffected: comparison, ``IN`` and ``ORDER BY`` are
        the text surface. What BigQuery cannot give is *rejection* of an
        illegal member -- there is no CHECK constraint -- which
        :class:`TestEnumRejectionIsRecorded` pins.
        """
        assert dialect.suggested_column_types()[enum.Enum] is StringColumn

    def test_bytearray_shares_the_bytes_answer(self, dialect):
        """``BYTES`` is the one byte-string type; there is no second one."""
        table = dialect.suggested_column_types()
        assert table[bytearray] is table[bytes] is BinaryColumn


class TestArrayCells:
    """``ARRAY<T>`` in REPEATED mode is native, which is why these are arrays."""

    @pytest.mark.parametrize("entry", [list, tuple, set, frozenset], ids=_ENTRY_IDS[13:17])
    def test_container_entry_is_an_array(self, dialect, entry):
        assert dialect.suggested_column_types()[entry] is ArrayColumn

    def test_tuple_carries_no_answer_for_a_heterogeneous_value(self, dialect):
        """议题 A is open and this cell is its subject, not its answer.

        ``ARRAY<T>`` declares one element type, so a *heterogeneous* tuple has
        no native carrier here other than ``STRUCT`` -- which is the same
        core-level question ClickHouse's ``Tuple`` / ``Map`` raise. The answer
        is the protocol's agreed BigQuery row, and the permissive fallback this
        entry used to reach is gone, so the cell has to answer *something*.
        Pinned so a 议题 A ruling moves it deliberately.
        """
        assert resolve(dialect, tuple) is ArrayColumn

    def test_the_array_surface_is_not_taken_away(self, dialect):
        """The documented array surface is native: no capability is lost.

        ``ARRAY_LENGTH``, the ``UNNEST`` operator (with ``WITH OFFSET`` and
        ``JOIN UNNEST``), ``ARRAY_SLICE`` / ``ARRAY_TO_STRING`` and the
        quantified ``LIKE ... ANY UNNEST(...)`` form are all documented, and
        they are what ``ArrayColumn``'s two operations ask for. The old
        capability mechanism that used to state this is gone; the class the
        cell answers carries the two methods, which is the same statement.
        """
        column_class = dialect.suggested_column_types()[list]
        assert hasattr(column_class, "array_length")
        assert hasattr(column_class, "unnest")

    def test_set_entries_carry_no_server_side_deduplication_claim(self, dialect):
        """Set-ness is a value-layer property; the ``ARRAY`` does not re-dedupe.

        Nothing to refuse -- it is not an operation -- but it is the reason
        ``set`` and ``frozenset`` answer the array cell at all.
        """
        table = dialect.suggested_column_types()
        assert table[set] is table[frozenset] is ArrayColumn


class TestDictCell:
    """``dict`` answers JSONColumn, provisionally, and says so in the docstring."""

    def test_dict_is_json_column(self, dialect):
        assert dialect.suggested_column_types()[dict] is JSONColumn

    def test_dict_is_never_refused_on_any_version(self, dialect):
        """The refusal exists for MySQL < 5.7 and MariaDB < 10.2.

        Those have no JSON functions at all. BigQuery has a documented,
        non-Preview ``JSON`` type, so a ``None`` would state a limit it does
        not have -- and no version gate is declared anywhere in this backend,
        so a ``dict`` field annotated today would have to answer on every
        server.
        """
        for version in ((3, 0, 0), (3, 11, 0), (3, 30, 0)):
            table = BigQueryDialect(version=version).suggested_column_types()
            assert table[dict] is JSONColumn, version

    def test_the_provisional_status_is_written_down(self, dialect):
        """The cell must not read as settled: 议题 A is open.

        Whether a structured value belongs to a ``STRUCT`` column class is
        undecided, and BigQuery sharpens rather than settles it -- ``STRUCT<T>``
        and ``JSON`` are two documented non-Preview types whose operation
        surfaces differ (field access by ``expression.fieldname`` versus path
        access by ``JSON_QUERY``). The answer is recorded as provisional so a
        reader is not left to assume the question was closed.
        """
        assert "议题 A" in inspect.getsource(_MIXIN_MODULE)
        assert "provisional" in inspect.getsource(_MIXIN_MODULE).lower()

    def test_the_alternative_candidate_is_named(self, dialect):
        """Both candidates visible, as the protocol requires for a 🔶 cell.

        The alternative is ``STRUCT``, and the cell says so rather than leaving
        a reader to infer it from the type list -- a 🔶 cell that records only
        the answer it happens to give is indistinguishable from a settled one.
        """
        source = inspect.getsource(_MIXIN_MODULE)
        assert "STRUCT" in source
        assert "JSONColumn" in source

    def test_no_struct_column_class_was_invented_here(self, dialect):
        """A ``STRUCTColumn`` would be 议题 A decided by accident, in a backend."""
        assert not hasattr(_MIXIN_MODULE, "StructColumn")
        defined_here = [
            name
            for name, value in vars(_MIXIN_MODULE).items()
            if isinstance(value, type)
            and getattr(value, "__module__", None) == _MIXIN_MODULE.__name__
        ]
        assert defined_here == ["BigQueryColumnTypeMixin"]


class TestEnumRejectionIsRecorded:
    """No CHECK constraint means no illegal-member rejection -- recorded, not narrowed."""

    def test_the_absence_of_check_is_written_down(self, dialect):
        """The ``CREATE TABLE`` grammar admits only primary and foreign keys.

        Both are documented as unenforced ("BigQuery only supports unenforced
        primary keys"), so there is no ``CHECK`` position to put a constraint
        in and an out-of-range enum value is stored rather than refused. That
        contradicts the enum guarantee the protocol's ``§7`` assumes, so it has
        to be visible rather than inferred from a silently absent mechanism.
        """
        source = inspect.getsource(_MIXIN_MODULE)
        assert "CHECK" in source
        assert "unenforced" in source


class TestDocsOnlyMarkers:
    """文档（待云验） is this table's evidence level, and it says so where read."""

    def test_the_module_docstring_states_the_evidence_level(self):
        """A reader must not mistake a documentation answer for a measured one."""
        source = inspect.getsource(_MIXIN_MODULE)
        assert "文档（待云验）" in source
        assert "No BigQuery instance was reachable" in source
        assert "localhost:9050" in source

    def test_the_mixin_docstring_states_the_evidence_level(self):
        assert "文档（待云验）" in BigQueryColumnTypeMixin.__doc__

    def test_the_open_range_gap_is_named_and_not_fixed_here(self):
        """Fix item #8 stays open, and the table does not pretend otherwise.

        ``RANGE<DATE|DATETIME|TIMESTAMP>`` is documented as the declared form,
        but this backend's ``parse_type`` cannot carry the angle brackets and
        raises ``InvalidTypeNameError`` (bare ``RANGE`` survives as a
        word-carrying ``CustomType``). That is a DataType-layer gap; no entry in
        this table is a range, so no column answer is affected.
        """
        source = inspect.getsource(_MIXIN_MODULE)
        assert "RANGE" in source
        assert "#8" in source

    def test_the_range_gap_still_raises_in_parse_type(self):
        """The pending fix is *pending*: the gap is real today, not documented away.

        Asserting the current raise is what keeps this table from being read as
        covering the range family. When fix item #8 lands, this test is what
        should fail and be revisited -- not silently left passing.
        """
        from rhosocial.activerecord.backend.expression.type_name import (
            InvalidTypeNameError,
        )

        with pytest.raises(InvalidTypeNameError):
            dialect = BigQueryDialect(version=DIALECT_VERSION)
            dialect.parse_type("RANGE<DATE>")

    def test_every_cited_page_is_an_official_bigquery_url(self):
        """A citation is only worth carrying if it points at the documentation."""
        source = inspect.getsource(_MIXIN_MODULE).replace("\n", " ")
        urls = [token.strip("`*,;") for token in source.split() if token.startswith("http")]
        assert urls, "the module docstring cites no page"
        for url in urls:
            assert url.startswith("https://cloud.google.com/bigquery/docs/"), url
