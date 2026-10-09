# tests/rhosocial/activerecord_bigquery_test/feature/backend/dialect/test_column_suggestion.py
"""BigQuery's eighteen-entry column-type suggestion table and its narrowing.

Pure dialect tests -- no server, no emulator. What is asserted here is the
**declaration**: that the table answers every entry of the protocol's closed
list, that the cells BigQuery deviates on are the ones its documentation says
they should be, and that the single narrowing is the one the operator reference
supports.

The evidence level of the whole table is 文档（待云验）. No BigQuery instance was
reachable while this was written, so nothing here was measured. These tests
therefore pin *what the backend claims and why*, never the server's agreement
with it; a scenario run is what would settle the latter, and the docstrings
name which claims are waiting for it. The rendering those cells imply is Phase
2b's work and is deliberately not asserted.
"""

import datetime
import decimal
import enum
import inspect
import uuid

import pytest

from rhosocial.activerecord.backend.dialect.mixins import ColumnSuggestionMixin
from rhosocial.activerecord.backend.expression.column_suggestions import (
    COLUMN_TYPE_ENTRIES,
    NEUTRAL_COLUMN_TYPE_SUGGESTIONS,
    UNSUPPORTED,
)
from rhosocial.activerecord.backend.expression import column_types as core_column_types
from rhosocial.activerecord.backend.expression.column_types import (
    ArrayColumn,
    BinaryColumn,
    BooleanColumn,
    ColumnBase,
    DateTimeColumn,
    DecimalColumn,
    FloatColumn,
    IntegerColumn,
    JSONColumn,
    NumericColumn,
    StringColumn,
    UUIDColumn,
)
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect
from rhosocial.activerecord.backend.impl.bigquery.mixins import (
    BigQueryColumnSuggestionMixin,
)

#: The version the dialect is asked about. BigQuery's is a rolling service with
#: no per-release version string in the way PostgreSQL has one, so this is the
#: dialect's own default and nothing in the table branches on it.
DIALECT_VERSION = (3, 0, 0)

#: Every column class core declares, read off the module rather than restated.
#: Used to say "this backend invents no column class of its own", which is a
#: claim about the *whole* module and not about the ten cells that were named
#: by hand elsewhere in this file.
_CORE_COLUMN_CLASSES = frozenset(
    value
    for value in vars(core_column_types).values()
    if isinstance(value, type) and issubclass(value, ColumnBase)
)

#: This backend's suggestion mixin, as a module rather than as a class, so the
#: docstrings and table comments can be read as the evidence they are.
_MIXIN_MODULE = __import__(
    BigQueryColumnSuggestionMixin.__module__, fromlist=["BigQueryColumnSuggestionMixin"]
)
_MIXIN_SOURCE = inspect.getsource(_MIXIN_MODULE)

_ENTRY_IDS = [getattr(entry, "__name__", str(entry)) for entry in COLUMN_TYPE_ENTRIES]


def _entry_ids():
    return list(_ENTRY_IDS)


@pytest.fixture
def dialect():
    return BigQueryDialect(version=DIALECT_VERSION)


class TestTableCompleteness:
    """A hole in the table is a silent gap, and the protocol forbids one."""

    def test_the_dialect_carries_the_mixin(self, dialect):
        assert isinstance(dialect, ColumnSuggestionMixin)

    def test_the_bigquery_half_comes_first_in_the_mro(self, dialect):
        """The load-bearing part of the dialect's base list.

        ``BigQueryColumnSuggestionMixin`` overrides both members, so C3 has to
        see it before ``ColumnSuggestionMixin`` or the table and the narrowing
        would be core's. Nothing in the query would look wrong either way --
        core's generic answers are all valid column classes, and core's
        ``supports_column_operation`` returns True for ``ilike`` -- which is
        exactly why it takes an assertion to notice.
        """
        mro = type(dialect).__mro__
        assert mro.index(BigQueryColumnSuggestionMixin) < mro.index(ColumnSuggestionMixin)

    def test_every_entry_is_answered(self, dialect):
        """All eighteen, by name -- an omission fails here rather than at lookup."""
        missing = [e for e in COLUMN_TYPE_ENTRIES if e not in dialect.suggested_column_types()]
        assert missing == []

    def test_no_entry_is_answered_none(self, dialect):
        """``None`` would be indistinguishable from "not filled in yet"."""
        table = dialect.suggested_column_types()
        assert [e for e in COLUMN_TYPE_ENTRIES if table[e] is None] == []

    @pytest.mark.parametrize("entry", COLUMN_TYPE_ENTRIES, ids=_entry_ids())
    def test_every_answer_is_a_column_class(self, dialect, entry):
        answer = dialect.suggested_column_types()[entry]
        assert isinstance(answer, type)
        assert issubclass(answer, ColumnBase)

    @pytest.mark.parametrize("entry", COLUMN_TYPE_ENTRIES, ids=_entry_ids())
    def test_every_entry_resolves_to_its_own_answer(self, dialect, entry):
        assert dialect.column_class_for(entry) is dialect.suggested_column_types()[entry]

    def test_no_bigquery_entry_is_unsupported(self, dialect):
        """The refusal is real elsewhere and unnecessary here -- see the mixin.

        Firebird has no JSON functions and no arrays; MySQL < 5.7 and
        MariaDB < 10.2 have no JSON functions. BigQuery has a native
        ``ARRAY<T>`` in REPEATED mode and a documented non-Preview ``JSON``
        type, so a refusal would state a limit this backend does not have --
        as wrong as a hole.
        """
        table = dialect.suggested_column_types()
        assert [e for e in COLUMN_TYPE_ENTRIES if table[e] is UNSUPPORTED] == []

    def test_the_table_is_not_core_baseline_aliasing(self, dialect):
        """A backend that had inherited core's dict would answer core's numbers.

        ``float`` and ``Decimal`` are the two cells BigQuery deviates on, so
        the check that this table is BigQuery's own is that it is not core's.
        """
        assert BigQueryColumnSuggestionMixin.COLUMN_TYPE_SUGGESTIONS is not \
            NEUTRAL_COLUMN_TYPE_SUGGESTIONS

    def test_the_table_is_a_copy(self, dialect):
        """Mutating the answer must not corrupt the class attribute."""
        first = dialect.suggested_column_types()
        first[str] = FloatColumn
        assert dialect.suggested_column_types()[str] is StringColumn

    def test_exactly_two_cells_differ_from_core_baseline(self, dialect):
        """The deviation set is pinned, so adding one is a deliberate act.

        Core keeps ``float`` and ``Decimal`` on one ``NumericColumn``;
        BigQuery's documented storage splits them (``FLOAT64`` an approximate
        double, ``NUMERIC``/``BIGNUMERIC`` exact fixed-point that do not
        implicitly mix with it). Every other cell restates the baseline.
        """
        table = dialect.suggested_column_types()
        differing = {
            entry
            for entry in COLUMN_TYPE_ENTRIES
            if table[entry] is not NEUTRAL_COLUMN_TYPE_SUGGESTIONS[entry]
        }
        assert differing == {float, decimal.Decimal}

    @pytest.mark.parametrize("entry", COLUMN_TYPE_ENTRIES, ids=_entry_ids())
    def test_no_entry_answers_a_class_this_backend_defines(self, dialect, entry):
        """A backend-only column class would be the extension path, not a default.

        ``COLUMN_TYPE_SUGGESTIONS`` may hold a class core does not know -- that
        is how a backend with a Python type of its own registers it -- but this
        backend declares no ``DataType`` subclass and defines no column class
        of its own, so every answer is one core already has. This is also what
        keeps the ``dict`` cell honest: inventing a ``StructColumn`` here would
        be 议题 A's core-level decision made by accident, in a backend.
        """
        answer = dialect.suggested_column_types()[entry]
        assert answer in _CORE_COLUMN_CLASSES


class TestBaselineCells:
    """The shared ten-backend baseline, restated cell by cell."""

    @pytest.mark.parametrize(
        "entry, expected",
        [
            (bool, BooleanColumn),
            (int, IntegerColumn),
            (str, StringColumn),
            (bytes, BinaryColumn),
            (bytearray, BinaryColumn),
            (datetime.date, DateTimeColumn),
            (datetime.time, DateTimeColumn),
            (datetime.datetime, DateTimeColumn),
            (uuid.UUID, UUIDColumn),
            (enum.Enum, StringColumn),
        ],
        ids=["bool", "int", "str", "bytes", "bytearray", "date", "time",
             "datetime", "UUID", "Enum"],
    )
    def test_baseline_entry(self, dialect, entry, expected):
        assert dialect.suggested_column_types()[entry] is expected

    def test_float_is_not_the_generic_numeric_column(self, dialect):
        """``FLOAT64`` is an approximate double, not exact fixed-point."""
        table = dialect.suggested_column_types()
        assert table[float] is FloatColumn
        assert table[float] is not NumericColumn

    def test_decimal_is_not_the_generic_numeric_column(self, dialect):
        """``NUMERIC`` / ``BIGNUMERIC`` carry a declared precision and scale."""
        table = dialect.suggested_column_types()
        assert table[decimal.Decimal] is DecimalColumn
        assert table[decimal.Decimal] is not NumericColumn

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
        assert dialect.column_class_for(uuid.UUID) is UUIDColumn
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
        :class:`TestEnumRejectionIsRecordedNotNarrowed` pins.
        """
        assert dialect.suggested_column_types()[enum.Enum] is StringColumn

    def test_bytearray_shares_the_bytes_answer(self, dialect):
        """``BYTES`` is the one byte-string type; there is no second one."""
        table = dialect.suggested_column_types()
        assert table[bytearray] is table[bytes] is BinaryColumn


class TestArrayCells:
    """``ARRAY<T>`` in REPEATED mode is native, which is why these are arrays."""

    @pytest.mark.parametrize("entry", [list, tuple, set, frozenset], ids=_entry_ids()[13:17])
    def test_container_entry_is_an_array(self, dialect, entry):
        assert dialect.suggested_column_types()[entry] is ArrayColumn

    def test_tuple_carries_no_narrowing(self, dialect):
        """议题 A is open and this cell is its subject, not its answer.

        ``ARRAY<T>`` declares one element type, so a *heterogeneous* tuple has
        no native carrier here other than ``STRUCT`` -- which is the same
        core-level question ClickHouse's ``Tuple`` / ``Map`` raise. The answer
        is the protocol's agreed BigQuery row, and the permissive fallback this
        entry used to reach is gone, so the cell has to answer *something*.
        Pinned so a 议题 A ruling moves it deliberately.
        """
        assert dialect.column_class_for(tuple) is ArrayColumn

    def test_array_operations_are_not_narrowed(self, dialect):
        """The documented array surface is native: no capability is taken away.

        ``ARRAY_LENGTH``, the ``UNNEST`` operator (with ``WITH OFFSET`` and
        ``JOIN UNNEST``), ``ARRAY_SLICE`` / ``ARRAY_TO_STRING`` and the
        quantified ``LIKE ... ANY UNNEST(...)`` form are all documented, and
        they are what ``ArrayColumn``'s two operations ask for.
        """
        assert dialect.supports_column_operation("ArrayColumn", "array_length") is True
        assert dialect.supports_column_operation("ArrayColumn", "unnest") is True

    def test_set_entries_carry_no_server_side_deduplication_claim(self, dialect):
        """Set-ness is a value-layer property; the ``ARRAY`` does not re-dedupe.

        Nothing to narrow -- it is not an operation -- but it is the reason
        ``set`` and ``frozenset`` answer the array cell at all.
        """
        table = dialect.suggested_column_types()
        assert table[set] is table[frozenset] is ArrayColumn


class TestDictCell:
    """``dict`` answers JSONColumn, provisionally, and says so in the docstring."""

    def test_dict_is_json_column(self, dialect):
        assert dialect.suggested_column_types()[dict] is JSONColumn

    def test_dict_is_never_refused_on_any_version(self, dialect):
        """The gated refusal exists for MySQL < 5.7 and MariaDB < 10.2.

        Those have no JSON functions at all. BigQuery has a documented,
        non-Preview ``JSON`` type, so a refusal would state a limit it does not
        have -- and no version gate is declared anywhere in this backend, so a
        ``dict`` field annotated today would have to answer on every server.
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
        assert "议题 A" in _MIXIN_SOURCE
        assert "provisional" in _MIXIN_SOURCE.lower()

    def test_the_alternative_candidate_is_named(self, dialect):
        """Both candidates visible, as the protocol requires for a 🔶 cell.

        The alternative is ``STRUCT``, and the cell says so rather than leaving
        a reader to infer it from the type list -- a 🔶 cell that records only
        the answer it happens to give is indistinguishable from a settled one.
        """
        assert "STRUCT" in _MIXIN_SOURCE
        assert "JSONColumn" in _MIXIN_SOURCE

    def test_no_struct_column_class_was_invented_here(self, dialect):
        """A ``STRUCTColumn`` would be 议题 A decided by accident, in a backend."""
        assert not hasattr(_MIXIN_MODULE, "StructColumn")
        defined_here = [
            name
            for name, value in vars(_MIXIN_MODULE).items()
            if isinstance(value, type)
            and getattr(value, "__module__", None) == _MIXIN_MODULE.__name__
        ]
        assert defined_here == ["BigQueryColumnSuggestionMixin"]

    def test_json_operations_are_not_narrowed(self, dialect):
        """The documented ``JSON`` function family covers what the class offers.

        ``JSON_QUERY`` / ``JSON_VALUE`` for document and scalar access (already
        rendered by ``BigQueryCapabilityMixin.format_json_function_expression``),
        ``JSON_EXTRACT_SCALAR``, ``JSON_QUERY_ARRAY_LENGTH``, ``JSON_KEYS``,
        ``TO_JSON_STRING``, ``PARSE_JSON``. Unlike ClickHouse there is no
        version gate here to apply, because this backend declares none.
        """
        assert dialect.supports_column_operation("JSONColumn", "json_path") is True
        assert dialect.supports_column_operation("JSONColumn", "json_value") is True


class TestOperationNarrowing:
    """One narrowing -- ``ilike`` -- and what is deliberately left alone."""

    def test_ilike_is_narrowed(self, dialect):
        """BigQuery has no ``ILIKE`` operator.

        The operator reference enumerates pattern matching as ``LIKE`` and the
        quantified ``LIKE`` (``search_value [NOT] LIKE { ANY | SOME | ALL }
        patterns``); the string ``ILIKE`` occurs on no GoogleSQL reference page
        this table cites. 文档（待云验）.
        """
        assert dialect.supports_column_operation("StringColumn", "ilike") is False

    @pytest.mark.parametrize(
        "version", [(3, 0, 0), (3, 11, 0), (3, 30, 0)], ids=lambda v: ".".join(map(str, v))
    )
    def test_ilike_is_narrowed_on_every_version(self, version):
        """There is no documented version that adds it, so the refusal is flat.

        BigQuery has no per-release version string to gate on; a narrowing that
        branched would be inventing a boundary the documentation does not have.
        """
        dialect = BigQueryDialect(version=version)
        assert dialect.supports_column_operation("StringColumn", "ilike") is False

    def test_like_is_not_narrowed(self, dialect):
        """Narrowing one pair must not refuse the others on the same class.

        BigQuery's ``LIKE`` is documented as **case-sensitive** ("Each
        comparison is case-sensitive"), which is precisely why losing ``ilike``
        costs something here and why ``like`` has to stay: it is the operator
        that exists, and no collation is assumed on its behalf.
        """
        assert dialect.supports_column_operation("StringColumn", "like") is True

    def test_the_narrowing_is_scoped_to_the_column_class(self, dialect):
        """``ilike`` is a string operation; other columns keep their own surface."""
        assert dialect.supports_column_operation("IntegerColumn", "ilike") is True
        assert dialect.supports_column_operation("JSONColumn", "ilike") is True

    def test_the_rest_of_the_string_surface_is_not_narrowed(self, dialect):
        """Every other documented string operation stays available.

        ``CONCAT`` (this backend's declared concatenation spelling), ``UPPER``
        / ``LOWER`` / ``TRIM``, ``SUBSTR``, ``LENGTH`` / ``CHAR_LENGTH`` /
        ``BYTE_LENGTH``, ``STARTS_WITH``, ``REPLACE``, ``SPLIT`` and the rest of
        the string-functions reference are all documented. 文档（待云验）.
        """
        for op in ("like", "concat", "upper", "lower", "trim", "substr", "length"):
            assert dialect.supports_column_operation("StringColumn", op) is True, op

    @pytest.mark.parametrize(
        "column_name, op",
        [
            ("BooleanColumn", "is_true"),
            ("BooleanColumn", "is_false"),
            ("IntegerColumn", "in_"),
            ("IntegerColumn", "abs"),
            ("FloatColumn", "mod"),
            ("DecimalColumn", "round"),
            ("DateTimeColumn", "date_diff"),
            ("DateTimeColumn", "extract"),
            ("BinaryColumn", "cast"),
            ("UUIDColumn", "in_"),
            ("ArrayColumn", "array_length"),
            ("ArrayColumn", "unnest"),
            ("JSONColumn", "json_path"),
        ],
    )
    def test_nothing_else_is_narrowed(self, dialect, column_name, op):
        """The operator reference is a complete enumeration of what GoogleSQL has.

        Everything core's column classes offer maps onto it one for one apart
        from ``ilike``, so a second narrowing here would need a page behind it
        and there is none.
        """
        assert dialect.supports_column_operation(column_name, op) is True

    def test_an_unknown_operation_is_not_narrowed_by_accident(self, dialect):
        """The default is True, so an operation nobody declared stays available.

        The narrowing is a statement about BigQuery, not a whitelist: refusing
        everything this table does not name would refuse the documented array
        and JSON families wider than core's operation set.
        """
        assert dialect.supports_column_operation("ArrayColumn", "arrayJoin") is True

    def test_every_narrowed_operation_exists_on_the_column_class(self, dialect):
        """The operation name is the method's own name, so the two must agree.

        The protocol makes ``op`` the attribute that provides the operation, so
        a narrowing can be cross-checked against the class with ``hasattr``.
        Narrowing a name no column class carries would be a claim about
        nothing.
        """
        column_classes = {
            "StringColumn": StringColumn,
            "IntegerColumn": IntegerColumn,
            "JSONColumn": JSONColumn,
            "ArrayColumn": ArrayColumn,
        }
        assert hasattr(column_classes["StringColumn"], "ilike")
        for op in ("json_path", "json_value"):
            assert hasattr(column_classes["JSONColumn"], op)
        for op in ("array_length", "unnest"):
            assert hasattr(column_classes["ArrayColumn"], op)


class TestEnumRejectionIsRecordedNotNarrowed:
    """No CHECK constraint means no illegal-member rejection -- recorded, not narrowed."""

    def test_the_absence_of_check_is_written_down(self, dialect):
        """The ``CREATE TABLE`` grammar admits only primary and foreign keys.

        Both are documented as unenforced ("BigQuery only supports unenforced
        primary keys"), so there is no ``CHECK`` position to put a constraint
        in and an out-of-range enum value is stored rather than refused. That
        contradicts the enum guarantee the protocol's ``§7`` assumes, so it has
        to be visible rather than inferred from a silently absent mechanism.
        """
        source = inspect.getsource(BigQueryColumnSuggestionMixin)
        assert "CHECK" in source
        assert "unenforced" in source

    def test_no_string_operation_is_narrowed_for_it(self, dialect):
        """A schema guarantee is not an operation, so nothing may be refused for it.

        The protocol says a narrowing is a statement that an *operation* is
        unavailable. Nothing about ``StringColumn``'s surface changes because
        the schema cannot enforce membership -- and narrowing ``eq`` would
        refuse a comparison that works, far wider than the evidence supports.
        """
        for op in ("eq", "in_", "like", "between"):
            assert dialect.supports_column_operation("StringColumn", op) is True, op

    def test_the_mixin_says_why_it_narrows_nothing_here(self, dialect):
        """The reasoning is in the docstring, so a later reader does not re-open it."""
        doc = BigQueryColumnSuggestionMixin.supports_column_operation.__doc__
        assert "CHECK" in doc
        assert "narrow" in doc.lower()


class TestDocsOnlyMarkers:
    """文档（待云验） is this table's evidence level, and it says so where read."""

    def test_the_module_docstring_states_the_evidence_level(self):
        """A reader must not mistake a documentation answer for a measured one."""
        assert "文档（待云验）" in _MIXIN_SOURCE
        assert "No BigQuery instance was reachable" in _MIXIN_SOURCE
        assert "localhost:9050" in _MIXIN_SOURCE

    def test_the_mixin_docstring_states_the_evidence_level(self):
        assert "文档（待云验）" in BigQueryColumnSuggestionMixin.__doc__

    def test_the_open_range_gap_is_named_and_not_fixed_here(self):
        """Fix item #8 stays open, and the table does not pretend otherwise.

        ``RANGE<DATE|DATETIME|TIMESTAMP>`` is documented as the declared form,
        but this backend's ``parse_type`` cannot carry the angle brackets and
        raises ``InvalidTypeNameError`` (bare ``RANGE`` survives as a
        word-carrying ``CustomType``). That is a DataType-layer gap; no entry in
        this table is a range, so no column operation is affected.
        """
        assert "RANGE" in _MIXIN_SOURCE
        assert "#8" in _MIXIN_SOURCE

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
        urls = [
            token.strip("`*,;")
            for token in _MIXIN_SOURCE.replace("\n", " ").split()
            if token.startswith("http")
        ]
        assert urls, "the module docstring cites no page"
        for url in urls:
            assert url.startswith("https://cloud.google.com/bigquery/docs/"), url
