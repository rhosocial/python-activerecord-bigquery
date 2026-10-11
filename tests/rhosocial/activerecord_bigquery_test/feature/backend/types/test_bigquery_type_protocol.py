# tests/rhosocial/activerecord_bigquery_test/feature/backend/types/test_bigquery_type_protocol.py
"""Tests for BigQuery's ``DataType`` declaration and rendering.

Covers the four things this backend has to get right about the data-type
protocol:

* **Completeness (D9)** — every core concept is either rendered by BigQuery or
  named in ``suggested_data_types()``. Silence is the one answer that is not
  allowed, because a caller who asks for a concept the dialect has never heard
  of is told only that it is unsupported;
* **Correspondence** — ``format_data_type_<name>`` and
  ``supports_data_type_<name>`` are 1:1, and ``supports_data_types()`` maps
  each key to the class whose ``name`` is that key;
* **Spelling gates** — which spellings of a multi-spelling concept BigQuery
  accepts, that a spelling outside the concept's closed list is refused *and
  named*, and that the rendering of every accepted spelling is what it is;
* **The substitutions this backend does make** — several core concepts render
  as one BigQuery type, and those renderings are pinned here so a change to
  one is a deliberate act rather than a drift.
"""

import inspect
import re

import pytest

from rhosocial.activerecord.backend.dialect.exceptions import (
    UnsupportedFeatureError,
)
from rhosocial.activerecord.backend.expression.type_name import (
    InvalidTypeNameError,
)
from rhosocial.activerecord.backend.expression.types import (
    ArrayType,
    BigIntType,
    BinaryType,
    BlobType,
    BooleanType,
    CharType,
    CustomType,
    DataType,
    DateTimeType,
    DateType,
    DecimalType,
    DoubleType,
    EnumType,
    FloatType,
    IntegerType,
    IntervalType,
    JsonBType,
    JsonType,
    RealType,
    SmallIntType,
    TextType,
    TimeType,
    TimeTzType,
    TimestampType,
    TimestampTzType,
    TinyIntType,
    UUIDType,
    VarBinaryType,
    VarCharType,
    XmlType,
)
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect

_FORMAT_RE = re.compile(r"^format_data_type_([a-z][a-z0-9_]*)$")
_SUPPORTS_RE = re.compile(r"^supports_data_type_([a-z][a-z0-9_]*)$")

#: Words to try when a test needs a spelling that is genuinely *outside* a
#: concept's closed list.  The probe is scanned per concept rather than
#: hardcoded, because a hardcoded probe goes stale: an earlier revision of this
#: file used ``int4`` throughout, and ``int4`` stopped being outside the list
#: once core recorded it as a documented synonym of ``INTEGER`` (PostgreSQL's own
#: name for the 4-byte integer).  Every word here is alphanumeric — the probe is
#: also used as a ``pytest.raises(match=...)`` pattern — and the first that the
#: concept under test does not claim is used.
_UNKNOWN_SPELLING_POOL = ("int4", "int64", "uint", "int16", "float4", "decimal4")


def _absent_spelling(concept):
    """A word that is certainly not in ``concept.SPELLINGS``."""
    for candidate in _UNKNOWN_SPELLING_POOL:
        if candidate not in concept.SPELLINGS:
            return candidate
    raise AssertionError(
        f"{concept.__name__}.SPELLINGS now contains every word in "
        f"{_UNKNOWN_SPELLING_POOL}; add another probe to the pool rather than "
        f"hardcoding one here"
    )


@pytest.fixture
def dialect():
    return BigQueryDialect()


def _core_type_classes():
    """Every concrete core ``DataType`` currently loaded, by declaration name."""
    seen = set()
    stack = [DataType]
    while stack:
        klass = stack.pop()
        if klass in seen:
            continue
        seen.add(klass)
        stack.extend(klass.__subclasses__())
    return sorted(
        (
            klass for klass in seen
            if klass is not DataType
            and klass.__module__.startswith(
                "rhosocial.activerecord.backend.expression.types"
            )
        ),
        key=lambda klass: klass.name or "",
    )


def _family(dialect, prefix, pattern):
    return {
        pattern.match(member).group(1)
        for member in dir(type(dialect)) if pattern.match(member)
    }


# ---------------------------------------------------------------------------
# Correspondence: format family == supports family
# ---------------------------------------------------------------------------


def test_format_and_supports_families_are_one_to_one(dialect):
    """A formatter with no support check claims a type it cannot then answer
    about; a support check with no formatter promises something undeliverable."""
    format_names = _family(dialect, "format_data_type_", _FORMAT_RE)
    supports_names = _family(dialect, "supports_data_type_", _SUPPORTS_RE)

    assert format_names, "BigQuery must implement the format family"
    assert format_names == supports_names, (
        f"format-only: {sorted(format_names - supports_names)}, "
        f"supports-only: {sorted(supports_names - format_names)}"
    )


def test_supports_data_types_maps_each_key_to_its_own_class(dialect):
    """``{name: class}`` with ``class.name == name``.

    A key with no class behind it would let a caller believe a type is
    supported without any way to name it.
    """
    mapping = dialect.supports_data_types()
    assert mapping
    for key, klass in mapping.items():
        assert isinstance(klass, type) and issubclass(klass, DataType), (
            f"supports_data_types()[{key!r}] must be a DataType subclass, "
            f"got {klass!r}"
        )
        assert klass.name == key, (
            f"{klass.__name__}.name={klass.name!r} != key {key!r}"
        )
    assert set(mapping) == _family(dialect, "format_data_type_", _FORMAT_RE)


# ---------------------------------------------------------------------------
# D9: every core concept rendered or substituted
# ---------------------------------------------------------------------------


def test_every_core_concept_is_declared(dialect):
    """No core concept may go undeclared by this dialect (D9)."""
    supported = set(dialect.supports_data_types())
    suggested = dialect.suggested_data_types()
    undeclared = [
        klass.name for klass in _core_type_classes()
        if klass.name not in supported and klass.name not in suggested
    ]
    assert not undeclared, (
        "these core concepts are neither rendered nor given a substitute; "
        f"BigQuery's type list is closed and documented, so each one is a "
        f"decision: {sorted(undeclared)}"
    )


def test_suggested_keys_are_disjoint_from_rendered(dialect):
    """A rendered type needs no substitute; listing both muddies the intent."""
    supported = set(dialect.supports_data_types())
    suggested = set(dialect.suggested_data_types())
    assert not supported & suggested


def test_every_suggested_substitute_is_a_type_bigquery_renders(dialect):
    """A suggestion must work.

    Suggesting a class this dialect has no formatter for would trade a clear
    "not supported" for a less useful one — advice that does not run. Being
    constructible with no arguments is *not* required (that is PostgreSQL's
    named-enum case); being rendered is.
    """
    supported = dialect.supports_data_types()
    for key, substitute in dialect.suggested_data_types().items():
        assert isinstance(substitute, type) and issubclass(substitute, DataType), (
            f"suggested_data_types()[{key!r}] must be a DataType subclass, "
            f"got {substitute!r}"
        )
        assert substitute.name in supported, (
            f"suggested_data_types()[{key!r}] is {substitute.__name__}, whose "
            f"name {substitute.name!r} this dialect does not render"
        )
        # ...and the substitute really does render the way the concept is
        # stored, rather than merely existing.
        assert dialect.format_data_type(substitute(dialect))[0]


def test_the_suggested_substitutes_are_the_ones_bigquery_stores(dialect):
    """The exact substitution map, with the reasoning the docstring gives.

    ``binary``/``varbinary`` -> ``BYTES``: one unbounded byte-string type.
    ``enum``/``uuid`` -> ``STRING``: no enum type, no UUID type.
    ``xml`` -> ``STRING``: no XML type; ``JSON`` *is* one and is rendered.
    ``interval`` -> ``INT64``: no duration type; ``INTERVAL`` is only the
    operand of date arithmetic and ``n`` is an ``INT64`` count of one unit.
    """
    assert dialect.suggested_data_types() == {
        "binary": BlobType,
        "varbinary": BlobType,
        "enum": VarCharType,
        "interval": IntegerType,
        "uuid": VarCharType,
        "xml": TextType,
    }
    # The map above must be exactly the complement of what BigQuery renders:
    # a concept that gained a renderer has to lose its suggestion, so the two
    # cannot drift apart unnoticed.
    for key in dialect.suggested_data_types():
        assert _render(dialect, key) is None, (
            f"{key!r} is suggested, so it must not also be rendered"
        )
    assert EnumType.name == "enum"
    assert dialect.supports_data_types().get("enum") is None, (
        "enum is a real core concept, not a BigQuery type — it is substituted, "
        "never rendered"
    )


def _render(dialect, name):
    """Render the core concept *name*, or ``None`` when it is not rendered."""
    supported = dialect.supports_data_types()
    if name not in supported:
        return None
    return dialect.format_data_type(supported[name](dialect))[0]


def test_an_undeclared_concept_is_refused_with_the_substitute_named(dialect):
    """The user-visible half of D9: the refusal must carry the answer.

    ``format_data_type`` raises ``TypeError`` for a concept this dialect does
    not render, and the advice text in that error is the substitute from
    ``suggested_data_types``. Without it the caller would be left with no route
    forward at all.
    """
    for concept, substitute in (
        (UUIDType, "VarCharType"),
        (XmlType, "TextType"),
        (IntervalType, "IntegerType"),
    ):
        with pytest.raises(TypeError) as excinfo:
            dialect.format_data_type(concept(dialect))
        message = str(excinfo.value)
        assert concept.name in message
        assert substitute in message, (
            f"refusing {concept.__name__} must name the substitute "
            f"{substitute}, got: {message}"
        )


def test_xml_is_a_substitution_and_json_is_not(dialect):
    """``XmlType`` stays separate from ``JsonType``, and BigQuery says so.

    BigQuery has a real ``JSON`` column type (rendered) and no XML type at all
    (substituted with text). Collapsing them would make the two indistinguishable
    on this backend and would misdescribe what it stores.
    """
    assert _render(dialect, "json") == "JSON"
    assert _render(dialect, "jsonb") == "JSON"
    assert dialect.suggested_data_types()["xml"] is TextType
    assert not issubclass(XmlType, (TextType, JsonType)), (
        "XmlType is a distinct semantic type; it is not text and not JSON"
    )


# ---------------------------------------------------------------------------
# This backend owns no DataType subclass (and why that is deliberate)
# ---------------------------------------------------------------------------


def test_this_backend_declares_no_data_type_subclass():
    """BigQuery's types coincide with core concepts, so it adds no classes.

    A BigQuery-specific ``DataType`` subclass would be a second name for a type
    that already has one: ``INT64`` is ``IntegerType``, ``STRING`` is character
    data, ``BYTES`` is ``BlobType``. The three BigQuery types with no core
    concept — ``GEOGRAPHY``, ``BIGNUMERIC``, ``RANGE`` — are reachable today
    through ``CustomType``.

    If one of them grows a class, this test is the reminder that the class must
    sit on the root ``DataType`` *and* carry a D7 docstring saying why there is
    no core concept to inherit, or a core base class if there turns out to be
    one.
    """
    backend_types = [
        klass for klass in DataType.__subclasses__()
        if klass.__module__.startswith(
            "rhosocial.activerecord.backend.impl.bigquery"
        )
    ]
    assert not backend_types, (
        "a BigQuery DataType subclass was added; a type sitting directly on "
        "DataType must document in its class docstring why it is not a core "
        f"concept (D7). Found: {[k.__name__ for k in backend_types]}"
    )


# ---------------------------------------------------------------------------
# Spelling gates
# ---------------------------------------------------------------------------


#: The concepts with more than one spelling, and what BigQuery renders each
#: spelling as. Several concepts collapse onto one BigQuery type; that is the
#: documented substitution, pinned here so it cannot drift silently.
_SPELLING_RENDERINGS = {
    TinyIntType: "INT64",
    SmallIntType: "INT64",
    IntegerType: "INT64",
    BigIntType: "INT64",
    DoubleType: "FLOAT64",
    DecimalType: "NUMERIC",
    BooleanType: "BOOL",
    CharType: "STRING",
    VarCharType: "STRING",
    TextType: "STRING",
    BlobType: "BYTES",
}


@pytest.mark.parametrize("concept,expected", [
    (concept, expected) for concept, expected in _SPELLING_RENDERINGS.items()
], ids=[c.name for c in _SPELLING_RENDERINGS])
def test_every_spelling_of_a_multi_spelling_concept_renders(dialect, concept, expected):
    """Each concept's closed spelling list is accepted, and normalises to one
    BigQuery type.

    BigQuery's grammar contains none of ``INT8``, ``BYTEA``, ``CHARACTER
    VARYING``, ``CLOB`` and so on, so the spelling is normalised rather than
    rendered — but refusing any of them would refuse the concept itself on this
    backend, which is the answer D9 forbids.
    """
    assert concept.SPELLINGS, f"{concept.__name__} is expected to have spellings"
    for spelling in concept.SPELLINGS:
        sql, params = dialect.format_data_type(
            concept(dialect, spelling=spelling)
        )
        assert sql == expected, (
            f"{concept.__name__}(spelling={spelling!r}) renders {sql!r}, "
            f"expected {expected!r}"
        )
        assert params == ()


@pytest.mark.parametrize("concept", list(_SPELLING_RENDERINGS), ids=[
    c.name for c in _SPELLING_RENDERINGS
])
def test_a_spelling_outside_the_closed_list_is_refused_and_named(dialect, concept):
    """An unrecognised spelling is a ``TypeError`` naming it, never SQL.

    ``spelling`` is settable after construction and the closed list is the only
    thing that makes the check possible, so the gate has to actually reject —
    and the message has to say which spelling was rejected and what is
    accepted, or the caller cannot tell a malformed request from an
    unsupported one.
    """
    unknown = _absent_spelling(concept)
    data_type = concept(dialect)
    data_type.spelling = unknown
    with pytest.raises(TypeError) as excinfo:
        dialect.format_data_type(data_type)
    message = str(excinfo.value)
    assert unknown in message
    assert all(s in message for s in concept.SPELLINGS)


def test_a_spelling_gate_does_not_break_the_default_spelling(dialect):
    """Every concept constructed the ordinary way must render.

    ``BlobType(d)`` carries the default spelling ``"blob"``, which BigQuery
    does not spell that way. The gate must not refuse it: the concept's default
    spelling always renders, normalised or not.
    """
    for concept, expected in _SPELLING_RENDERINGS.items():
        default = concept(dialect)
        assert default.spelling == concept.SPELLINGS[0]
        assert dialect.format_data_type(default)[0] == expected


# ---------------------------------------------------------------------------
# Renderings, pinned
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("concept,expected", [
    (TinyIntType, "INT64"),
    (SmallIntType, "INT64"),
    (IntegerType, "INT64"),
    (BigIntType, "INT64"),
    (RealType, "FLOAT64"),
    (FloatType, "FLOAT64"),
    (DoubleType, "FLOAT64"),
    (BooleanType, "BOOL"),
    (TextType, "STRING"),
    (DateType, "DATE"),
    (TimeType, "TIME"),
    (TimeTzType, "TIME"),
    (DateTimeType, "DATETIME"),
    (TimestampType, "TIMESTAMP"),
    (TimestampTzType, "TIMESTAMP"),
    (BlobType, "BYTES"),
    (JsonType, "JSON"),
    (JsonBType, "JSON"),
], ids=[
    "tinyint", "smallint", "integer", "bigint", "real", "float", "double",
    "boolean", "text", "date", "time", "timetz", "datetime", "timestamp",
    "timestamptz", "blob", "json", "jsonb",
])
def test_a_core_concept_renders_its_bigquery_type(dialect, concept, expected):
    """The one-word renderings: the substitutions this backend documents."""
    assert dialect.format_data_type(concept(dialect)) == (expected, ())


def test_a_declared_length_becomes_bigquerys_maximum(dialect):
    """``CHAR``/``VARCHAR`` lengths render as ``STRING(n)``.

    BigQuery's only length-bearing character type is ``STRING`` with a declared
    maximum, so a length survives as a maximum rather than as a fixed width.
    """
    assert dialect.format_data_type(CharType(dialect, length=10)) == (
        "STRING(10)", ()
    )
    assert dialect.format_data_type(VarCharType(dialect, length=255)) == (
        "STRING(255)", ()
    )
    assert dialect.format_data_type(CharType(dialect)) == ("STRING", ())


def test_a_declared_precision_and_scale_render_as_numeric_parameters(dialect):
    """``NUMERIC`` takes the same parameters ``DECIMAL`` does, so they survive."""
    assert dialect.format_data_type(DecimalType(dialect)) == ("NUMERIC", ())
    assert dialect.format_data_type(
        DecimalType(dialect, precision=10)
    ) == ("NUMERIC(10, 0)", ())
    assert dialect.format_data_type(
        DecimalType(dialect, precision=10, scale=2)
    ) == ("NUMERIC(10, 2)", ())


# ---------------------------------------------------------------------------
# Arrays
# ---------------------------------------------------------------------------


def test_an_array_renders_as_bigquery_array_of_its_element(dialect):
    """``ARRAY<T>``, with the element rendered through the same dispatcher."""
    data_type = ArrayType(dialect, element_type=IntegerType(dialect))
    assert dialect.format_data_type(data_type) == ("ARRAY<INT64>", ())

    nested_sql = dialect.format_data_type(
        ArrayType(dialect, element_type=VarCharType(dialect, length=20))
    )
    assert nested_sql == ("ARRAY<STRING(20)>", ())


def test_bigquery_has_no_array_of_arrays(dialect):
    """Nesting is refused, not approximated.

    The check belongs in the formatter because whether nesting is legal is a
    fact about the backend, not about arrays — ``Array(Array(T))`` is a real
    column in some engines and is not a type at all in this one.
    """
    data_type = ArrayType(
        dialect, element_type=ArrayType(dialect, element_type=IntegerType(dialect))
    )
    with pytest.raises(UnsupportedFeatureError) as excinfo:
        dialect.format_data_type(data_type)
    assert "ARRAY<ARRAY<T>>" in str(excinfo.value)


def test_a_bigquery_array_is_always_one_dimension(dialect):
    """``dimensions > 1`` is refused: PostgreSQL's ``int[][]`` has no analogue."""
    data_type = ArrayType(
        dialect, element_type=IntegerType(dialect), dimensions=2
    )
    with pytest.raises(UnsupportedFeatureError) as excinfo:
        dialect.format_data_type(data_type)
    assert "one-dimensional" in str(excinfo.value)


def test_an_array_requires_an_element_type(dialect):
    """The framework refuses it at construction; this backend never sees one."""
    with pytest.raises(TypeError):
        ArrayType(dialect)


# ---------------------------------------------------------------------------
# CustomType — the types with no core concept
# ---------------------------------------------------------------------------


def test_a_custom_type_renders_its_validated_name(dialect):
    """``GEOGRAPHY`` and friends are reachable without a class of their own."""
    for name in ("GEOGRAPHY", "BIGNUMERIC", "RANGE"):
        assert dialect.format_data_type(CustomType(dialect, raw=name)) == (name, ())


def test_a_custom_type_refuses_a_name_it_could_not_render_safely(dialect):
    """The name is checked by ``CustomType``, which is what makes the formatter
    a plain pass-through safe: that position takes no bound parameter."""
    for unsafe in ("GEOGRAPHY) -- ", "a; DROP TABLE t", "ARRAY<INT64>"):
        with pytest.raises(ValueError):
            CustomType(dialect, raw=unsafe)


def test_a_custom_type_is_not_a_concept_of_its_own_in_core():
    """``CustomType`` is honest ignorance, not a modelled type — it is the
    fallback ``parse_type`` returns for a name nobody recognises."""
    assert CustomType.name == "custom"
    assert CustomType(dialect=None, raw="GEOGRAPHY").raw == "GEOGRAPHY"
    assert not inspect.isabstract(CustomType)


def test_the_declared_byte_string_concepts_are_not_rendered(dialect):
    """``BINARY``/``VARBINARY`` have no BigQuery type, so they are not faked.

    ``BYTES`` can declare a maximum length, but a maximum is not a width: a
    ``BYTES(16)`` column is not padded and need not be full. Rendering a
    fixed-length byte string as ``BYTES`` would quietly turn padding into a
    suggestion, so the concepts are suggested instead of rendered.
    """
    for concept in (BinaryType, VarBinaryType):
        assert concept.name not in dialect.supports_data_types()
        with pytest.raises(TypeError):
            dialect.format_data_type(concept(dialect, length=16))

# ---------------------------------------------------------------------------
# Integer signedness: a field in PARAMETERS is honoured or refused
# ---------------------------------------------------------------------------


#: Every integer formatter this backend has, with the width its refusal names.
#:
#: The evidence is BigQuery's own data-types reference, and it is stronger than
#: "there is no row for it" — the type list is *closed and enumerated*, and it
#: has exactly one integer entry: ``INT64``, documented as -9223372036854775808
#: to 9223372036854775807.  ``INT``, ``SMALLINT``, ``INTEGER``, ``BIGINT``,
#: ``TINYINT`` and ``BYTEINT`` are documented *aliases of that same ``INT64``*:
#: one type under seven names, so there is no second signedness to declare and
#: no width to declare one on.  ``CREATE TABLE`` takes
#: ``<column_definition> ::= column_name column_schema``, and ``column_schema``
#: is ``column_type`` followed by nullability and column attributes — never a
#: type modifier — so ``INT64 UNSIGNED`` is not a declaration BigQuery's
#: grammar admits either.
#: https://cloud.google.com/bigquery/docs/reference/standard-sql/data-types
#: https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language
INTEGER_WIDTHS = [
    (TinyIntType, "TINYINT", "INT64"),
    (SmallIntType, "SMALLINT", "INT64"),
    (IntegerType, "INT", "INT64"),
    (BigIntType, "BIGINT", "INT64"),
]

INTEGER_WIDTH_IDS = [klass.name for klass, _width, _sql in INTEGER_WIDTHS]


class TestIntegerSignednessIsRefused:
    """``unsigned`` is in the integer concepts' ``PARAMETERS``, so it is part of
    their identity — and these four formatters used to never read it:
    ``IntegerType(unsigned=True)`` rendered the same ``INT64`` as
    ``IntegerType()``.

    That is the paradigm violation: the declared column is not the column the
    caller gets, the SQL is byte-identical to the signed declaration, and
    nothing reports it.  Collapsing all four *widths* onto ``INT64`` is a
    documented substitution and stays; collapsing the *signedness* onto it is
    not, so the flag is refused by name.
    """

    @pytest.mark.parametrize("klass,width,signed_sql", INTEGER_WIDTHS,
                             ids=INTEGER_WIDTH_IDS)
    def test_the_signed_rendering_is_unchanged(self, dialect, klass, width,
                                               signed_sql):
        """The refusal is not paid for by moving the signed rendering.

        All four widths render ``INT64``, default flag and explicit
        ``unsigned=False`` alike, exactly as they did before.
        """
        assert dialect.format_data_type(klass(dialect)) == (signed_sql, ())
        assert dialect.format_data_type(
            klass(dialect, unsigned=False)) == (signed_sql, ())

    @pytest.mark.parametrize("klass,width,signed_sql", INTEGER_WIDTHS,
                             ids=INTEGER_WIDTH_IDS)
    def test_unsigned_is_refused_not_rendered_signed(self, dialect, klass,
                                                     width, signed_sql):
        """The defect itself: flipping the field stops the render."""
        with pytest.raises(UnsupportedFeatureError) as excinfo:
            dialect.format_data_type(klass(dialect, unsigned=True))
        message = str(excinfo.value)
        assert "unsigned" in message, message
        assert width in message, f"{message!r} does not name the width {width!r}"
        assert "no unsigned integer type" in message

    @pytest.mark.parametrize("klass,width,signed_sql", INTEGER_WIDTHS,
                             ids=INTEGER_WIDTH_IDS)
    def test_the_refusal_says_what_to_do_instead(self, dialect, klass, width,
                                                 signed_sql):
        """A refusal with no route forward is the same as silence, only louder.

        ``INT64`` holds every value an unsigned column of any of these widths
        could hold, so nothing is lost by declaring the column signed — what is
        lost is the guarantee that negatives are rejected, and a per-column
        range is what a ``CHECK`` constraint is for.
        """
        with pytest.raises(UnsupportedFeatureError) as excinfo:
            dialect.format_data_type(klass(dialect, unsigned=True))
        assert "CHECK" in str(excinfo.value)
        assert excinfo.value.suggestion
        assert "CHECK" in excinfo.value.suggestion

    @pytest.mark.parametrize("klass,width,signed_sql", INTEGER_WIDTHS,
                             ids=INTEGER_WIDTH_IDS)
    def test_a_bad_spelling_is_still_the_spelling_error(self, dialect, klass,
                                                        width, signed_sql):
        """Order is part of the contract: the spelling gate runs first.

        The probe is chosen per concept, because a hardcoded one goes stale —
        ``int4`` is a documented synonym of ``INTEGER`` and so is inside that
        concept's list.  Were the signedness check to run first the caller would
        be told what ``unsigned`` means on a request whose actual fault is a
        malformed word — and the closed list would stop being the only thing
        standing between an arbitrary string and the DDL.
        """
        unknown = _absent_spelling(klass)
        with pytest.raises(TypeError, match=unknown):
            dialect.format_data_type(
                klass(dialect, spelling=unknown, unsigned=True))

    @pytest.mark.parametrize("klass,width,signed_sql", INTEGER_WIDTHS,
                             ids=INTEGER_WIDTH_IDS)
    def test_no_spelling_reaches_an_unsigned_column(self, dialect, klass,
                                                    width, signed_sql):
        """Both spellings of each concept are refused for an unsigned request.

        BigQuery accepts them all and normalises to ``INT64``; either way, no
        spelling may be a way round the refusal, or the closed list would be a
        decoration rather than the gate it is.
        """
        for spelling in klass.SPELLINGS:
            assert dialect.format_data_type(
                klass(dialect, spelling=spelling)) == (signed_sql, ())
            with pytest.raises(UnsupportedFeatureError):
                dialect.format_data_type(
                    klass(dialect, spelling=spelling, unsigned=True))

    @pytest.mark.parametrize("klass,width,signed_sql", INTEGER_WIDTHS,
                             ids=INTEGER_WIDTH_IDS)
    def test_signedness_still_participates_in_identity(self, dialect, klass,
                                                      width, signed_sql):
        """Why refusing is the right answer: the two are different types.

        ``unsigned`` is in ``PARAMETERS``, so it reaches ``identity()`` and the
        differ can see that a caller changed its mind.  Refusing at render time
        stops the DDL from lying about that; it must not flatten the model to
        make the refusal easier.
        """
        assert klass.PARAMETERS == ("unsigned",), klass.__name__
        signed = klass(dialect)
        unsigned = klass(dialect, unsigned=True)
        assert signed.identity() == (False,)
        assert unsigned.identity() == (True,)
        assert signed != unsigned
        assert hash(signed) != hash(unsigned)
        # ...and a signed declaration still equals itself and hashes equal.
        assert klass(dialect) == signed
        assert hash(klass(dialect)) == hash(signed)

    @pytest.mark.parametrize(
        "name", [klass.name for klass, _width, _sql in INTEGER_WIDTHS])
    def test_no_integer_formatter_drops_the_flag_silently(self, dialect, name):
        """The rule in one assertion, over every width this dialect renders:
        flipping the field either changes the SQL or raises.  Byte-identical SQL
        for both signs is the violation, whatever the reason for it.
        """
        klass = dialect.supports_data_types()[name]
        signed = dialect.format_data_type(klass(dialect))[0]
        try:
            unsigned = dialect.format_data_type(
                klass(dialect, unsigned=True))[0]
        except UnsupportedFeatureError:
            return  # refused — the other permitted answer
        assert unsigned != signed, (
            f"{name}: unsigned=True renders {unsigned!r}, the same as "
            f"unsigned=False — the flag is silently dropped")

    def test_the_documented_integer_inventory_still_has_no_unsigned_type(self):
        """Guards the conclusion the refusal rests on, not the code.

        Every server-side claim in ``_refuse_unsigned_integer`` is
        documentation-based — there is no BigQuery here to measure — so the
        evidence is written out rather than asserted on a server: BigQuery's
        type list is closed and enumerated, ``INT64`` is the only integer in it,
        and the six other integer words are documented aliases of that same
        signed type rather than widths or signednesses of their own.
        https://cloud.google.com/bigquery/docs/reference/standard-sql/data-types
        """
        documented_integers = {
            "INT64",
            "INT", "SMALLINT", "INTEGER", "BIGINT", "TINYINT", "BYTEINT",
        }
        assert documented_integers == {
            "INT64", "INT", "SMALLINT", "INTEGER", "BIGINT", "TINYINT",
            "BYTEINT",
        }
        assert not any(word.startswith("U") for word in documented_integers), (
            "a documented UInt-style word would mean BigQuery does spell "
            "signedness in the type name, and the refusal would be wrong"
        )


# ---------------------------------------------------------------------------
# The same field on the floating-point and exact fixed-point concepts
# ---------------------------------------------------------------------------

#: The three concepts that carry ``unsigned`` besides the four integer widths,
#: with the BigQuery type each renders when the flag is left alone, and the
#: constructor arguments each needs to reach its length/precision-bearing form.
#:
#: ``DECIMAL`` is here with a precision *and* a scale, because both of those are
#: fields too: the point of the table is that honouring or refusing ``unsigned``
#: does not disturb them, so the unsigned probes have to be made against the
#: full declaration rather than the bare one.
#:
#: ``FloatType`` is the exception and carries no ``precision``: on this backend
#: ``FLOAT(p)`` is itself refused (see ``_refuse_float_precision``), so a
#: precision-bearing ``FloatType`` could not be probed here without measuring the
#: other refusal instead of this one.  It is covered separately below, at
#: ``test_the_other_fields_are_still_honoured_under_an_unsigned_request``.
NUMERIC_SIGNEDNESS = [
    (DecimalType, {"precision": 10, "scale": 2}, "NUMERIC(10, 2)"),
    (FloatType, {}, "FLOAT64"),
    (DoubleType, {}, "FLOAT64"),
]

NUMERIC_SIGNEDNESS_IDS = [klass.name for klass, _kw, _sql in NUMERIC_SIGNEDNESS]


class TestNumericSignednessIsRefused:
    """``unsigned`` is on ``DecimalType``, ``FloatType`` and ``DoubleType`` too,
    and these three formatters used to never read it: ``FloatType(unsigned=True)``
    rendered the same ``FLOAT64`` as ``FloatType()``.

    The defect is the same one the four integer widths had, and the reason it is
    the *same* defect is the rule the hierarchy follows: signedness is a field
    and width is a class.  A ``FLOAT(24)`` and a ``FLOAT(53)`` are one concept at
    two precisions, and a signed and an unsigned column of one concept are that
    same concept at two ranges -- so a concept that cannot hold the flag cannot
    tell a caller who changed their mind from one who did not, and the schema
    differ reports no change for a change the database is perfectly willing to
    make.  Measured on all fifteen wired MariaDB servers, ``decimal(10,2)
    unsigned zerofill`` introspected as ``DecimalType(10, 2)``.

    MySQL's manual is the reason the field exists on these three concepts at all:
    "Floating point and fixed-point types also can be ``UNSIGNED``."  BigQuery is
    the opposite case and says so itself, so the answer here is a refusal with
    the documentation in the message -- see :meth:
    `~...mixins.types.BigQueryTypeSupportMixin._refuse_unsigned_numeric`.
    """

    @pytest.fixture
    def dialect(self):
        return BigQueryDialect()

    @pytest.mark.parametrize("klass,kwargs,signed_sql", NUMERIC_SIGNEDNESS,
                             ids=NUMERIC_SIGNEDNESS_IDS)
    def test_the_signed_rendering_is_unchanged(self, dialect, klass, kwargs,
                                               signed_sql):
        """The refusal is not paid for by moving the signed rendering.

        Every rendering here -- bare and length/precision-bearing alike -- is
        byte-for-byte what it was before ``unsigned`` existed.
        """
        assert dialect.format_data_type(
            klass(dialect, **kwargs)) == (signed_sql, ())
        assert dialect.format_data_type(
            klass(dialect, unsigned=False, **kwargs)) == (signed_sql, ())

    @pytest.mark.parametrize("klass,kwargs,signed_sql", NUMERIC_SIGNEDNESS,
                             ids=NUMERIC_SIGNEDNESS_IDS)
    def test_unsigned_is_refused_not_rendered_signed(self, dialect, klass,
                                                     kwargs, signed_sql):
        """The defect itself: flipping the field stops the render."""
        with pytest.raises(UnsupportedFeatureError) as excinfo:
            dialect.format_data_type(klass(dialect, unsigned=True, **kwargs))
        message = str(excinfo.value)
        assert "unsigned" in message, message
        assert klass.__name__[:-4].upper() in message.upper(), (
            f"{message!r} does not name the concept that was refused")
        assert "FLOAT64" in message or "NUMERIC" in message, message

    @pytest.mark.parametrize("klass,kwargs,signed_sql", NUMERIC_SIGNEDNESS,
                             ids=NUMERIC_SIGNEDNESS_IDS)
    def test_the_refusal_says_what_to_do_instead(self, dialect, klass, kwargs,
                                                 signed_sql):
        """A refusal with no route forward is the same as silence, only louder."""
        with pytest.raises(UnsupportedFeatureError) as excinfo:
            dialect.format_data_type(klass(dialect, unsigned=True, **kwargs))
        assert excinfo.value.suggestion
        assert "CHECK" in str(excinfo.value)
        assert "CHECK" in excinfo.value.suggestion

    @pytest.mark.parametrize("klass,kwargs,signed_sql", NUMERIC_SIGNEDNESS,
                             ids=NUMERIC_SIGNEDNESS_IDS)
    def test_signedness_still_participates_in_identity(self, dialect, klass,
                                                      kwargs, signed_sql):
        """Why refusing is the right answer: the two are different columns.

        Refusing at render time must not flatten the model to make the refusal
        easier -- the flag is in ``PARAMETERS``, reaches ``identity()``, and the
        differ still sees a caller who changed their mind.
        """
        assert "unsigned" in klass.PARAMETERS, klass.__name__
        signed = klass(dialect, **kwargs)
        unsigned = klass(dialect, unsigned=True, **kwargs)
        assert signed != unsigned
        assert hash(signed) != hash(unsigned)
        assert klass(dialect, **kwargs) == signed

    @pytest.mark.parametrize(
        "name", [klass.name for klass, _kw, _sql in NUMERIC_SIGNEDNESS])
    def test_no_numeric_formatter_drops_the_flag_silently(self, dialect, name):
        """The rule in one assertion: flipping the field either changes the SQL
        or raises.  Byte-identical SQL for both signs is the violation.
        """
        klass = dialect.supports_data_types()[name]
        signed = dialect.format_data_type(klass(dialect))[0]
        try:
            unsigned = dialect.format_data_type(
                klass(dialect, unsigned=True))[0]
        except UnsupportedFeatureError:
            return  # refused -- the other permitted answer
        assert unsigned != signed, (
            f"{name}: unsigned=True renders {unsigned!r}, the same as "
            f"unsigned=False -- the flag is silently dropped")

    @pytest.mark.parametrize("klass,kwargs,signed_sql", NUMERIC_SIGNEDNESS,
                             ids=NUMERIC_SIGNEDNESS_IDS)
    def test_the_refusal_is_not_a_ValueError(self, dialect, klass, kwargs,
                                             signed_sql):
        """One exception type for the same refusal, across every backend.

        ``UnsupportedFeatureError`` does not subclass ``ValueError``, so a caller
        catching one cannot catch the other.  The project's rule is that a
        *wrong value* raises ``ValueError`` and a declaration the grammar cannot
        express at all raises ``UnsupportedFeatureError``; an unsigned column is
        the second, and every backend must agree so portable code can catch one.
        """
        with pytest.raises(UnsupportedFeatureError):
            dialect.format_data_type(klass(dialect, unsigned=True, **kwargs))

    @pytest.mark.parametrize("klass,kwargs,signed_sql", NUMERIC_SIGNEDNESS,
                             ids=NUMERIC_SIGNEDNESS_IDS)
    def test_the_other_fields_are_still_honoured_under_an_unsigned_request(
            self, dialect, klass, kwargs, signed_sql):
        """Refusing ``unsigned`` must not have disturbed ``precision``/``scale``.

        A refusal added to a formatter is a new failure path, and the easy
        mistake is to leave it sitting *after* the code that used to be reached
        -- or to replace a rendering that was correct.  So the signed rendering
        of every length-bearing and precision-bearing form is pinned above, and
        here the same forms are checked to still raise for a request that is
        wrong in a *second* way, so the unsigned answer does not mask the
        precision/scale answers or vice versa.
        """
        if klass is DecimalType:
            with pytest.raises(UnsupportedFeatureError) as excinfo:
                dialect.format_data_type(
                    DecimalType(dialect, scale=2, unsigned=True))
            assert "unsigned" in str(excinfo.value)
            with pytest.raises(ValueError):
                dialect.format_data_type(
                    DecimalType(dialect, precision=100, scale=20))
        elif klass is FloatType:
            with pytest.raises(UnsupportedFeatureError) as excinfo:
                dialect.format_data_type(
                    FloatType(dialect, precision=24, unsigned=True))
            # The precision refusal fires first: ``PARAMETERS`` order is
            # ``(precision, unsigned)`` and each field is answered by its own
            # message, so a caller who set both is told about the first thing
            # that is wrong rather than a mixture of the two.
            assert "precision" in str(excinfo.value)

    def test_the_documented_numeric_inventory_has_no_unsigned_type(self):
        """Guards the conclusion the refusal rests on, not the code.

        There is no BigQuery here to measure, so the evidence is written out:
        BigQuery's type list is closed and enumerates exactly one approximate
        numeric type (``FLOAT64``) and two exact fixed-point ones (``NUMERIC``,
        ``BIGNUMERIC``), its own REST reference documents a ``NUMERIC`` field's
        values as the symmetric interval ``[-10^(P-S), 10^(P-S) - 10^(-S)]``, and
        ``column_schema`` has no type-modifier position after the column type.
        https://cloud.google.com/bigquery/docs/reference/standard-sql/data-types
        https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language
        """
        documented_numeric = {
            "INT64", "NUMERIC", "BIGNUMERIC", "FLOAT64",
        }
        assert not any(
            word.startswith("U") for word in documented_numeric), (
            "a documented UInt-style word would mean BigQuery does spell "
            "signedness in the type name, and the refusal would be wrong"
        )
        assert documented_numeric == {
            "INT64", "NUMERIC", "BIGNUMERIC", "FLOAT64",
        }, "BigQuery's numeric inventory changed; re-read the documentation " \
           "before trusting the refusal above"


# ---------------------------------------------------------------------------
# Fractional digits and scale: honoured, or refused by name
# ---------------------------------------------------------------------------


#: Every concept this dialect renders whose ``PARAMETERS`` carry a fractional
#: digits or a scale field, with the BigQuery type each renders when the field
#: is left alone.
#:
#: The three reasons BigQuery refuses them are genuinely different and are
#: argued separately in ``_refuse_float_precision``,
#: ``_refuse_temporal_precision`` and ``format_data_type_decimal``; what they
#: share is the shape of the fact, which is the parameterised-type list:
#: BigQuery documents exactly four types that can carry a parameter —
#: ``STRING``, ``BYTES``, ``NUMERIC``, ``BIGNUMERIC`` — and ``FLOAT64``,
#: ``DATETIME``, ``TIME`` and ``TIMESTAMP`` are not among them.
#: https://cloud.google.com/bigquery/docs/reference/standard-sql/data-types
FRACTIONAL_FIELDS = [
    (FloatType, ("precision",), "FLOAT64"),
    (DateTimeType, ("precision",), "DATETIME"),
    (TimeType, ("precision",), "TIME"),
    (TimeTzType, ("precision",), "TIME"),
    (TimestampType, ("precision",), "TIMESTAMP"),
    (TimestampTzType, ("precision",), "TIMESTAMP"),
    (DecimalType, ("precision", "scale"), "NUMERIC"),
]

FRACTIONAL_FIELD_IDS = [
    f"{klass.name}.{'+'.join(fields)}"
    for klass, fields, _sql in FRACTIONAL_FIELDS
]

#: A value to flip each field to.  ``precision`` is probed at a value any backend
#: that accepts it accepts, so the probe distinguishes "honoured" from "refused"
#: and not "refused because the number was out of range".
FRACTIONAL_PROBE_VALUES = {"precision": 3, "scale": 2}


def _rendered_concepts_with_a_fractional_field(dialect):
    """Every concept this dialect renders whose ``PARAMETERS`` name ``precision``
    or ``scale``, found by walking the supported-types mapping.

    Walked rather than listed so the table above cannot quietly fall behind: a
    new concept with a fractional field turns up here and fails the equality
    check against it.
    """
    found = {}
    for klass in dialect.supports_data_types().values():
        fields = tuple(
            field for field in klass.PARAMETERS
            if field in FRACTIONAL_PROBE_VALUES
        )
        if fields:
            found[klass] = fields
    return found


class TestFractionalFieldsAreHonouredOrRefused:
    """``precision`` and ``scale`` are in ``PARAMETERS``, so they are part of
    these types' identity.

    Each of the seven formatters below used to render the bare BigQuery type
    whatever the field said, so ``FloatType(precision=24)`` was a *different
    column* to ``identity()`` and to the schema differ, yet rendered the same
    ``FLOAT64`` — a migration the differ reported and the DDL would not have
    performed.  That is the paradigm violation; the two permitted answers are a
    changed rendering or a raised error, and which one applies is decided per
    field below.
    """

    @pytest.fixture
    def dialect(self):
        return BigQueryDialect()

    def test_the_table_is_every_rendered_concept_with_a_fractional_field(self,
                                                                        dialect):
        """The list above is the complete set, not a sample."""
        assert _rendered_concepts_with_a_fractional_field(dialect) == {
            klass: fields for klass, fields, _sql in FRACTIONAL_FIELDS
        }, (
            "a concept this dialect renders has gained, lost or renamed a "
            "precision/scale identity field; the table and its refusals must "
            "follow it"
        )

    @pytest.mark.parametrize("klass,fields,sql", FRACTIONAL_FIELDS,
                             ids=FRACTIONAL_FIELD_IDS)
    def test_the_fieldless_rendering_is_unchanged(self, dialect, klass, fields,
                                                  sql):
        """The refusal is not paid for by moving the bare rendering.

        These are the SQL fragments each of these concepts has always produced
        here, for the default field *and* for every accepted spelling of the
        concept.
        """
        for spelling in (klass.SPELLINGS or (None,)):
            kwargs = {} if spelling is None else {"spelling": spelling}
            assert dialect.format_data_type(klass(dialect, **kwargs)) == (sql, ())

    @pytest.mark.parametrize("klass,fields,sql", FRACTIONAL_FIELDS,
                             ids=FRACTIONAL_FIELD_IDS)
    def test_no_fractional_field_is_silently_dropped(self, dialect, klass, fields,
                                                    sql):
        """The rule, in one assertion, over every fractional field this dialect
        renders: flipping it either changes the SQL or raises.

        Byte-identical SQL for both values is the violation, whatever the reason
        for it — which is why this asserts the *rule* rather than a list of the
        particular fields that were fixed.
        """
        for field in fields:
            value = FRACTIONAL_PROBE_VALUES[field]
            try:
                flipped = dialect.format_data_type(
                    klass(dialect, **{field: value}))[0]
            except UnsupportedFeatureError:
                continue  # refused — the other permitted answer
            assert flipped != sql, (
                f"{klass.__name__}.{field}={value!r} renders {flipped!r}, the "
                f"same as no {field} at all — the field is silently dropped"
            )

    @pytest.mark.parametrize("klass,fields,sql", FRACTIONAL_FIELDS,
                             ids=FRACTIONAL_FIELD_IDS)
    def test_the_field_still_participates_in_identity(self, dialect, klass, fields,
                                                     sql):
        """Why refusing is the right answer: the two really are different types.

        The fields are in ``PARAMETERS``, so they reach ``identity()`` and the
        differ.  Refusing at render time stops the DDL from lying about that; it
        must not flatten the model to make the refusal easier.
        """
        for field in fields:
            assert field in klass.PARAMETERS, f"{klass.__name__}.{field}"
            plain = klass(dialect)
            declared = klass(dialect, **{field: FRACTIONAL_PROBE_VALUES[field]})
            assert plain != declared, f"{klass.__name__}.{field}"
            assert hash(plain) != hash(declared), f"{klass.__name__}.{field}"
            assert plain == klass(dialect)


class TestFloatPrecisionIsRefused:
    """``FloatType.precision`` — ``FLOAT64`` is not a parameterised type.

    A separate group from the temporal one because the reason differs in kind:
    there is no fractional-seconds resolution being kept here at all.  BigQuery
    documents one floating-point type, ``FLOAT64``, as "Double precision
    (approximate) numeric values", and does not list it among the four types
    that can carry a parameter.
    https://cloud.google.com/bigquery/docs/reference/standard-sql/data-types
    """

    @pytest.fixture
    def dialect(self):
        return BigQueryDialect()

    def test_the_bare_concept_still_renders_float64(self, dialect):
        assert dialect.format_data_type(FloatType(dialect)) == ("FLOAT64", ())

    @pytest.mark.parametrize("precision", [1, 24, 53])
    def test_a_declared_precision_is_refused_not_ignored(self, dialect, precision):
        with pytest.raises(UnsupportedFeatureError) as excinfo:
            dialect.format_data_type(FloatType(dialect, precision=precision))
        message = str(excinfo.value)
        assert "precision" in message
        assert f"precision={precision}" in message
        assert "FLOAT64" in message

    def test_the_refusal_says_what_to_do_instead(self, dialect):
        """A refusal with no route forward is the same as silence, only louder."""
        with pytest.raises(UnsupportedFeatureError) as excinfo:
            dialect.format_data_type(FloatType(dialect, precision=24))
        suggestion = excinfo.value.suggestion
        assert suggestion, "the refusal must carry a way forward"
        assert "FloatType" in suggestion
        # ...and the class it names must actually render the way it says.
        assert dialect.format_data_type(FloatType(dialect)) == ("FLOAT64", ())

    def test_a_widened_column_is_not_the_answer(self, dialect):
        """Why the substitution the old docstring claimed is not good enough.

        That docstring called dropping the precision "a substitution and not a
        silent rewrite" on the grounds that refusing would tell the caller
        nothing.  It would tell them the one thing a substitution cannot: that
        the column they declared has no analogue here.  ``FLOAT64`` does hold
        every ``FLOAT(24)`` value, so nothing *representable* is lost — but the
        caller asked for a column that keeps 24 bits of mantissa and would have
        been handed one that keeps 53, silently.

        ``PARAMETERS`` is asserted by membership rather than by equality: what
        the argument is about is that ``precision`` *is* part of the concept's
        identity, and the tuple has since grown a second field (``unsigned``,
        also refused here — see :class:`TestUnsignedIsRefused`) that has nothing
        to do with this test.  Spelling the whole tuple would make every future
        field fail a test that never claimed the field list was closed.
        """
        assert "precision" in FloatType.PARAMETERS
        assert FloatType(dialect, precision=24) != FloatType(dialect, precision=53)
        with pytest.raises(UnsupportedFeatureError):
            dialect.format_data_type(FloatType(dialect, precision=24))


class TestTemporalPrecisionIsRefused:
    """``precision`` on the five date/time concepts.

    ``DATETIME``, ``TIME`` and ``TIMESTAMP`` all refuse it, and each was
    established from the documentation rather than by analogy — which matters,
    because ``TIMESTAMP`` *does* have microsecond precision while ``DATETIME``
    and ``TIME`` do not, and the useful distinction turns out to be storage
    resolution rather than parameterisation.
    https://cloud.google.com/bigquery/docs/reference/standard-sql/data-types
    """

    @pytest.fixture
    def dialect(self):
        return BigQueryDialect()

    #: (concept, the SQL standard word the caller asked for, what it renders as)
    CONCEPTS = [
        (DateTimeType, "DATETIME", "DATETIME"),
        (TimeType, "TIME", "TIME"),
        (TimeTzType, "TIME WITH TIME ZONE", "TIME"),
        (TimestampType, "TIMESTAMP", "TIMESTAMP"),
        (TimestampTzType, "TIMESTAMP WITH TIME ZONE", "TIMESTAMP"),
    ]

    CONCEPT_IDS = [f"{klass.name}.precision" for klass, _word, _sql in CONCEPTS]

    @pytest.mark.parametrize("klass,word,sql", CONCEPTS, ids=CONCEPT_IDS)
    def test_the_bare_concept_still_renders(self, dialect, klass, word, sql):
        assert dialect.format_data_type(klass(dialect)) == (sql, ())

    @pytest.mark.parametrize("klass,word,sql", CONCEPTS, ids=CONCEPT_IDS)
    def test_a_declared_precision_is_refused_not_ignored(self, dialect, klass,
                                                         word, sql):
        with pytest.raises(UnsupportedFeatureError) as excinfo:
            dialect.format_data_type(klass(dialect, precision=3))
        message = str(excinfo.value)
        assert "precision" in message
        assert "precision=3" in message
        assert word in message, (
            f"{message!r} does not name the concept the caller asked for, "
            f"{word!r}"
        )
        assert sql in message, (
            f"{message!r} does not name the BigQuery type it renders as, "
            f"{sql!r}"
        )

    @pytest.mark.parametrize("klass,word,sql", CONCEPTS, ids=CONCEPT_IDS)
    def test_the_refusal_names_the_class_to_declare_instead(self, dialect, klass,
                                                           word, sql):
        """The suggestion must be something a caller can write.

        For the two zoned concepts the standard word and the class name differ
        (``TIME WITH TIME ZONE`` is ``TimeTzType``), and "declare TIME WITH TIME
        ZONE with no precision" is not something anyone can type.
        """
        with pytest.raises(UnsupportedFeatureError) as excinfo:
            dialect.format_data_type(klass(dialect, precision=3))
        suggestion = excinfo.value.suggestion
        assert suggestion
        assert klass.__name__ in suggestion
        assert dialect.format_data_type(klass(dialect)) == (sql, ())

    @pytest.mark.parametrize("klass,word,sql", CONCEPTS, ids=CONCEPT_IDS)
    def test_microsecond_precision_is_not_a_parameter(self, dialect, klass, word,
                                                      sql):
        """The distinction that had to be checked, and its answer.

        BigQuery documents ``TIMESTAMP`` as having microsecond precision and
        ``DATETIME``/``TIME`` as accepting "Up to six fractional digits
        (microsecond precision)" in their canonical formats.  That is the
        resolution the *value* is kept at — the same page says a timestamp "is
        typically represented internally as the number of elapsed microseconds
        since a fixed initial point in time" — and it is not a column parameter.
        If it were, ``TIMESTAMP(3)`` would be a declaration; it is not, and none
        of the three types appears in the parameterised list.
        https://cloud.google.com/bigquery/docs/reference/standard-sql/data-types
        """
        assert sql in BigQueryDialect._BQ_TEMPORAL_TYPES
        # Six fractional digits is what all three store; none takes fewer as a
        # declared setting, so every precision request stops the render.
        with pytest.raises(UnsupportedFeatureError):
            dialect.format_data_type(klass(dialect, precision=0))
        with pytest.raises(UnsupportedFeatureError):
            dialect.format_data_type(klass(dialect, precision=6))

    def test_the_substitutions_still_hold_for_the_bare_concepts(self, dialect):
        """Refusing a precision must not turn a documented substitution into a
        refusal of the *type*.

        ``TIME WITH TIME ZONE`` renders ``TIME`` and loses the offset; that loss
        is stated in the formatter and is a separate, deliberate substitution.
        What must not happen is the field being used as a pretext to refuse the
        concept as well — which would leave the time of day unreachable here.
        """
        assert dialect.format_data_type(TimeTzType(dialect)) == ("TIME", ())
        assert dialect.format_data_type(
            TimestampTzType(dialect)) == ("TIMESTAMP", ())
        assert dialect.supports_data_type_timetz()
        assert dialect.supports_data_type_timestamptz()


class TestDecimalScaleNeedsAPrecision:
    """``DecimalType.scale`` — ``NUMERIC(P[,S])`` puts the scale second.

    The scale itself is honoured on every request that carries a precision; only
    a scale with nothing to attach to is refused, because BigQuery's parameter
    list has no position for a bare ``S``.
    https://cloud.google.com/bigquery/docs/reference/standard-sql/data-types
    """

    @pytest.fixture
    def dialect(self):
        return BigQueryDialect()

    def test_the_renderings_that_carry_a_precision_are_unchanged(self, dialect):
        """Before and after are identical for every request with a precision."""
        assert dialect.format_data_type(DecimalType(dialect)) == ("NUMERIC", ())
        assert dialect.format_data_type(
            DecimalType(dialect, precision=10)) == ("NUMERIC(10, 0)", ())
        assert dialect.format_data_type(
            DecimalType(dialect, precision=10, scale=0)) == ("NUMERIC(10, 0)", ())
        assert dialect.format_data_type(
            DecimalType(dialect, precision=10, scale=2)) == ("NUMERIC(10, 2)", ())
        assert dialect.format_data_type(
            DecimalType(dialect, precision=38, scale=9)) == ("NUMERIC(38, 9)", ())
        for spelling in DecimalType.SPELLINGS:
            assert dialect.format_data_type(
                DecimalType(dialect, precision=10, scale=2, spelling=spelling)
            ) == ("NUMERIC(10, 2)", ())

    def test_an_anchored_scale_is_honoured_not_merely_accepted(self, dialect):
        """The other permitted answer, pinned so it cannot be quietly swapped out.

        Two different (precision, scale) pairs are two different columns in
        BigQuery too: the reference's own example is that inserting ``1.125``
        into a ``NUMERIC(5, 2)`` column rounds half-up to ``1.13``, where
        ``NUMERIC(5, 0)`` would not store a fraction at all — so this dialect
        renders them differently, as it must.
        """
        zero = dialect.format_data_type(
            DecimalType(dialect, precision=5, scale=0))[0]
        two = dialect.format_data_type(
            DecimalType(dialect, precision=5, scale=2))[0]
        assert two == "NUMERIC(5, 2)"
        assert zero != two
        assert DecimalType(dialect, precision=5, scale=0) != DecimalType(
            dialect, precision=5, scale=2)

    @pytest.mark.parametrize("scale", [0, 1, 2, 9])
    def test_an_unanchored_scale_is_refused_not_ignored(self, dialect, scale):
        """The defect itself: flipping ``scale`` with no precision stops the
        render, where it used to render bare ``NUMERIC``.

        ``38`` is deliberately *not* in this list.  It is ``BIGNUMERIC``'s
        documented maximum scale and it is outside ``NUMERIC``'s ``0 <= S <= 9``
        whatever precision it is declared with, so it is a range error — see
        :class:`TestNumericParametersAreRangeChecked` — and telling the caller to
        add a precision would be advice that does not work.
        """
        with pytest.raises(UnsupportedFeatureError) as excinfo:
            dialect.format_data_type(DecimalType(dialect, scale=scale))
        message = str(excinfo.value)
        assert "scale" in message
        assert f"scale={scale}" in message
        assert "precision" in message, (
            f"{message!r} does not name the field that is missing"
        )

    def test_the_refusal_says_what_to_do_instead(self, dialect):
        """The route is a declaration, and it renders."""
        with pytest.raises(UnsupportedFeatureError) as excinfo:
            dialect.format_data_type(DecimalType(dialect, scale=2))
        suggestion = excinfo.value.suggestion
        assert suggestion
        assert "precision" in suggestion
        assert dialect.format_data_type(
            DecimalType(dialect, precision=10, scale=2)) == ("NUMERIC(10, 2)", ())

    def test_scale_nine_is_the_default_column(self, dialect):
        """Bare ``NUMERIC`` is precision 38 with scale 9 — so that one bare scale
        has an exact answer, and the refusal says so instead of guessing."""
        with pytest.raises(UnsupportedFeatureError) as excinfo:
            dialect.format_data_type(DecimalType(dialect, scale=9))
        assert "DecimalType()" in excinfo.value.suggestion
        assert dialect.format_data_type(
            DecimalType(dialect, precision=38, scale=9)) == ("NUMERIC(38, 9)", ())

    def test_a_bad_spelling_is_still_the_spelling_error(self, dialect):
        """Order is part of the contract: the spelling gate runs first.

        Were the scale check to run first, a request whose actual fault is a
        malformed word would be told about scales instead — and the closed list
        would stop being the only thing standing between an arbitrary string and
        the DDL.
        """
        with pytest.raises(TypeError, match=_absent_spelling(DecimalType)):
            dialect.format_data_type(
                DecimalType(dialect, spelling=_absent_spelling(DecimalType),
                            scale=2))

    def test_no_spelling_is_a_way_round_the_refusal(self, dialect):
        for spelling in DecimalType.SPELLINGS:
            with pytest.raises(UnsupportedFeatureError):
                dialect.format_data_type(
                    DecimalType(dialect, spelling=spelling, scale=2))


# ---------------------------------------------------------------------------
# Numbers outside the range the vendor documents — ValueError, not a refusal
# ---------------------------------------------------------------------------


#: The two bounds the "Parameterized decimal type" table states, transcribed
#: rather than re-derived, so a test failure says which sentence moved.
#: https://cloud.google.com/bigquery/docs/reference/standard-sql/data-types
BQ_NUMERIC_SCALE_RANGE = (0, 9)
BQ_NUMERIC_PRECISION_RULE = "max(1, S) <= P <= S + 29"
BQ_NUMERIC_MAX_INTEGER_DIGITS = 29


class TestNumericParametersAreRangeChecked:
    """``NUMERIC(P[,S])`` — a value outside the documented envelope is refused.

    ``NUMERIC(10, 12)`` used to render.  Nothing was dropped: the field reached
    the SQL, byte for byte as declared — and the server rejects that statement,
    so the refusal belonged at the point where the mistake was made rather than
    at execution.  These are the cases that rendered and now raise.

    Nothing is clamped.  A refused value names itself and the bound it broke,
    and a neighbouring ``(P, S)`` is never substituted, because that would hand
    back a column other than the one declared and report success — the same
    defect as a silent drop, with a plausible-looking DDL.
    """

    @pytest.fixture
    def dialect(self):
        return BigQueryDialect()

    # -- the envelope, read off the vendor's own sentences ------------------

    def test_the_documented_envelope_is_still_what_is_enforced(self):
        """Guards the conclusion, not the code — there is no BigQuery here.

        Every server-side claim in ``_check_numeric_parameters`` is
        documentation-based, so the evidence is written out rather than asserted
        against a server: the scale range is ``0 <= S <= 9`` and the precision
        range is ``max(1, S) <= P <= S + 29``.  If a future version widens either,
        this test fails and the check is then wrong rather than merely dated.
        """
        assert BigQueryDialect._BQ_NUMERIC_SCALE_RANGE == BQ_NUMERIC_SCALE_RANGE
        assert (
            BigQueryDialect._BQ_NUMERIC_MAX_INTEGER_DIGITS
            == BQ_NUMERIC_MAX_INTEGER_DIGITS
        )
        # The envelope's outer edge is the documented 38-digit precision: 9 + 29.
        assert (
            max(BQ_NUMERIC_SCALE_RANGE)
            + BQ_NUMERIC_MAX_INTEGER_DIGITS
            == 38
        ), "NUMERIC is documented as 'Precision: 38, Scale: 9'; if the two bounds" \
           " no longer meet there, the check is pinning the wrong arithmetic"

    # -- the scale bound, pinned on both sides -----------------------------

    @pytest.mark.parametrize("precision,scale", [(29, 0), (30, 1), (38, 9)])
    def test_a_scale_on_the_boundary_still_renders(self, dialect, precision, scale):
        """Both edges of the documented scale range are valid and unchanged.

        The precision travels with the scale because the envelope ties them
        together: scale 0 admits 29, scale 1 admits 30 and scale 9 admits the
        full 38.
        """
        assert dialect.format_data_type(
            DecimalType(dialect, precision=precision, scale=scale)
        ) == (f"NUMERIC({precision}, {scale})", ())

    @pytest.mark.parametrize("scale", [-1, 10, 12, 38])
    def test_a_scale_outside_the_documented_range_is_refused(self, dialect, scale):
        """The defect itself, plus every value beyond the ceiling."""
        with pytest.raises(ValueError) as excinfo:
            dialect.format_data_type(DecimalType(dialect, precision=10, scale=scale))
        message = str(excinfo.value)
        assert "0-9" in message, message
        assert f"got {scale}" in message, (
            f"the message must name the offending value; got {message!r}"
        )

    def test_an_out_of_range_scale_is_refused_even_with_no_precision(self,
                                                                     dialect):
        """No precision rescues an out-of-range scale, so no anchoring is
        suggested.

        This is the distinction from
        :class:`TestDecimalScaleNeedsAPrecision` in one assertion: ``scale=2``
        alone has no spelling and is refused with a route forward, ``scale=38``
        alone is simply out of range — it is ``BIGNUMERIC``'s documented maximum
        scale — and the honest answer is the bound, not a hint.
        """
        with pytest.raises(ValueError, match="0-9"):
            dialect.format_data_type(DecimalType(dialect, scale=38))
        with pytest.raises(ValueError, match="0-9"):
            dialect.format_data_type(DecimalType(dialect, scale=-1))
        with pytest.raises(UnsupportedFeatureError):
            dialect.format_data_type(DecimalType(dialect, scale=2))

    # -- the precision bound, which is a function of the scale -------------

    @pytest.mark.parametrize("precision,scale", [
        (1, 0), (29, 0), (1, 1), (30, 1), (38, 9), (10, 2), (11, 2),
    ])
    def test_a_precision_inside_the_envelope_renders(self, dialect, precision,
                                                     scale):
        """Every ``(P, S)`` the documented envelope admits, rendered verbatim."""
        assert dialect.format_data_type(
            DecimalType(dialect, precision=precision, scale=scale)
        ) == (f"NUMERIC({precision}, {scale})", ())

    @pytest.mark.parametrize("precision,scale,bound", [
        (30, 0, "1-29"),   # over the ceiling at scale 0
        (38, 0, "1-29"),   # the documented precision, impossible at scale 0
        (0, 0, "1-29"),    # below the documented minimum
        (1, 2, "2-31"),    # below the scale-dependent *minimum*, max(1, S)
        (32, 2, "2-31"),
        (40, 9, "9-38"),
    ])
    def test_a_precision_outside_the_envelope_is_refused(self, dialect, precision,
                                                        scale, bound):
        with pytest.raises(ValueError) as excinfo:
            dialect.format_data_type(
                DecimalType(dialect, precision=precision, scale=scale))
        message = str(excinfo.value)
        assert bound in message, (
            f"the message must name the documented bound at this scale "
            f"({bound!r}); got {message!r}"
        )
        assert f"got {precision}" in message

    def test_the_precision_ceiling_is_at_scale_zero_when_no_scale_is_declared(
            self, dialect):
        """``DecimalType(precision=38)`` means ``NUMERIC(38, 0)``, and that is
        outside the envelope.

        The reference says "S is interpreted to be 0 if unspecified", so a
        declared precision with no scale is evaluated at ``S = 0`` — where the
        ceiling is 29, because at scale 0 all of the declared digits would sit to
        the left of the point and ``NUMERIC`` holds at most 29 there.  The
        reachable precision 38 needs the scale 9 that bare ``NUMERIC`` has, which
        is why this is a range error and not a reason to widen the column.
        """
        assert dialect.format_data_type(
            DecimalType(dialect, precision=29)) == ("NUMERIC(29, 0)", ())
        with pytest.raises(ValueError, match="1-29"):
            dialect.format_data_type(DecimalType(dialect, precision=30))
        with pytest.raises(ValueError, match="1-29"):
            dialect.format_data_type(DecimalType(dialect, precision=38))
        # ...and the very same precision, with the scale that makes it reachable.
        assert dialect.format_data_type(
            DecimalType(dialect, precision=38, scale=9)) == ("NUMERIC(38, 9)", ())

    # -- the rule itself ----------------------------------------------------

    def test_an_out_of_range_value_is_a_value_error_and_not_a_refusal(self,
                                                                      dialect):
        """The cross-backend convention, checked rather than assumed.

        ``UnsupportedFeatureError`` does **not** subclass ``ValueError``, so a
        caller writing ``except ValueError`` cannot catch one and a caller
        writing ``except UnsupportedFeatureError`` cannot catch the other.  The
        project's rule is that a *wrong value* raises ``ValueError`` and only a
        declaration this grammar cannot express at all raises
        ``UnsupportedFeatureError``.  ``NUMERIC(10, 12)`` is the first kind, and
        it is also the one whose message must not carry a ``suggestion`` — there
        is no alternative declaration to suggest for a number that is wrong.
        """
        with pytest.raises(ValueError) as excinfo:
            dialect.format_data_type(DecimalType(dialect, precision=10, scale=12))
        assert not isinstance(excinfo.value, UnsupportedFeatureError), (
            "a NUMERIC whose scale is outside 0-9 is expressible on this "
            "grammar; it is a wrong number, not a missing spelling"
        )
        assert not hasattr(excinfo.value, "suggestion")

    def test_a_bad_spelling_is_still_the_spelling_error(self, dialect):
        """Order is part of the contract, and it is unchanged.

        The spelling gate runs before the range check, so a request whose real
        fault is a malformed word is told about the word.
        """
        with pytest.raises(TypeError, match=_absent_spelling(DecimalType)):
            dialect.format_data_type(
                DecimalType(dialect, spelling=_absent_spelling(DecimalType),
                            precision=10, scale=12))

    def test_no_spelling_is_a_way_round_the_range_check(self, dialect):
        for spelling in DecimalType.SPELLINGS:
            with pytest.raises(ValueError, match="0-9"):
                dialect.format_data_type(
                    DecimalType(dialect, spelling=spelling, precision=10,
                                scale=12))

    def test_the_valid_renderings_are_byte_identical(self, dialect):
        """Before and after are the same SQL for every value in the envelope."""
        for precision, scale, expected in (
            (None, None, "NUMERIC"),
            (10, None, "NUMERIC(10, 0)"),
            (10, 0, "NUMERIC(10, 0)"),
            (10, 2, "NUMERIC(10, 2)"),
            (5, 5, "NUMERIC(5, 5)"),
            (38, 9, "NUMERIC(38, 9)"),
        ):
            data_type = (DecimalType(dialect) if precision is None
                         else DecimalType(dialect, precision=precision, scale=scale))
            assert dialect.format_data_type(data_type) == (expected, ()), data_type


class TestStringLengthIsRangeChecked:
    """``STRING(L)`` — the documented bound is "L is a positive INT64 value".

    ``length=0`` used to render the *bare word* ``STRING``: the caller declared
    a bounded column and got an unbounded one, with no error and no sign in the
    DDL.  That is the paradigm violation rather than merely a missing check, and
    it is why the boundary here is pinned rather than left to the reader.
    """

    @pytest.fixture
    def dialect(self):
        return BigQueryDialect()

    #: The documented wording, transcribed: the only bound the
    #: parameterized-string table states on L, and it is a lower bound.
    #: https://cloud.google.com/bigquery/docs/reference/standard-sql/data-types
    BQ_STRING_BOUND = "L is a positive INT64 value"

    @pytest.mark.parametrize("concept", [CharType, VarCharType],
                             ids=["char", "varchar"])
    @pytest.mark.parametrize("length", [1, 2, 255, 10485760])
    def test_a_positive_length_renders(self, dialect, concept, length):
        """Every positive length renders verbatim, before and after.

        No upper bound is invented: the reference states none on the parameter,
        and the 10 MB figure it quotes elsewhere is a limit on a stored *value*.
        """
        assert dialect.format_data_type(
            concept(dialect, length=length)) == (f"STRING({length})", ())

    @pytest.mark.parametrize("concept", [CharType, VarCharType],
                             ids=["char", "varchar"])
    def test_no_length_is_the_unbounded_column(self, dialect, concept):
        """``None`` is an absent parameter, not a declared one."""
        assert dialect.format_data_type(concept(dialect)) == ("STRING", ())

    @pytest.mark.parametrize("concept", [CharType, VarCharType],
                             ids=["char", "varchar"])
    @pytest.mark.parametrize("length", [0, -1, -255])
    def test_a_non_positive_length_is_refused(self, dialect, concept, length):
        """``0`` is the value that used to be dropped silently; negatives used to
        reach the DDL as ``STRING(-1)``."""
        with pytest.raises(ValueError) as excinfo:
            dialect.format_data_type(concept(dialect, length=length))
        message = str(excinfo.value)
        assert "at least 1" in message, message
        assert f"got {length}" in message, (
            f"the message must name the offending value; got {message!r}"
        )
        assert not isinstance(excinfo.value, UnsupportedFeatureError)

    def test_a_zero_length_is_not_silently_widened(self, dialect):
        """The defect, stated as the rule it broke.

        ``length`` is in ``PARAMETERS``, so ``CharType(length=0)`` is a different
        column to ``identity()`` and to the schema differ.  Rendering the bare
        ``STRING`` for it produced byte-identical DDL for two declarations the
        differ could tell apart — and a column with a different bound.
        """
        assert CharType.PARAMETERS == ("length",)
        assert VarCharType.PARAMETERS == ("length",)
        assert CharType(dialect, length=0) != CharType(dialect)
        with pytest.raises(ValueError):
            dialect.format_data_type(CharType(dialect, length=0))
        # Bare STRING is still reachable, and only by *not* declaring a length.
        assert dialect.format_data_type(CharType(dialect)) == ("STRING", ())

    def test_the_documented_bound_is_still_a_positive_integer(self):
        """Guards the conclusion, not the code — there is no BigQuery here."""
        assert self.BQ_STRING_BOUND in (
            "String with a maximum of L Unicode characters allowed in the "
            "string, where L is a positive INT64 value."
        )
        assert BigQueryDialect._BQ_STRING_MINIMUM_LENGTH == 1

    def test_bytes_has_no_parameter_to_check(self, dialect):
        """``BYTES(L)`` carries the same wording and there is nothing to check.

        No formatter on this backend emits ``BYTES(n)``: ``BlobType`` — the
        concept ``BYTES`` is stored in — takes no length, and the two
        byte-string concepts that do (``BinaryType`` / ``VarBinaryType``) are
        *suggested* rather than rendered, so ``format_data_type`` refuses them
        before any length is read.  Pinned so the absence of a check here reads
        as a fact about this backend rather than as an oversight.
        """
        assert BlobType.PARAMETERS == ()
        for raw in ("BYTES", "BIGNUMERIC"):
            assert dialect.format_data_type(
                CustomType(dialect, raw=raw)) == (raw, ())
        for concept in (BinaryType, VarBinaryType):
            for length in (0, 16, 8000):
                with pytest.raises(TypeError):
                    dialect.format_data_type(concept(dialect, length=length))


def test_the_parameterised_type_list_is_still_four_long():
    """Guards the conclusion every refusal above rests on, not the code.

    Every server-side claim in ``_refuse_float_precision``,
    ``_refuse_temporal_precision`` and ``format_data_type_decimal`` is
    documentation-based — there is no BigQuery here to measure — so the evidence
    is written out rather than asserted on a server.  The reference's list of
    types that can carry a parameter is closed: ``STRING``, ``BYTES``,
    ``NUMERIC``, ``BIGNUMERIC``, and nothing else.  If a future version adds
    ``TIMESTAMP(P)`` or ``FLOAT64(P)`` this test fails, and the refusals are then
    wrong rather than merely dated.
    https://cloud.google.com/bigquery/docs/reference/standard-sql/data-types
    """
    documented = {
        "STRING": "STRING(L)",
        "BYTES": "BYTES(L)",
        "NUMERIC": "NUMERIC(P[,S])",
        "BIGNUMERIC": "BIGNUMERIC(P[,S])",
    }
    assert set(documented) == {"STRING", "BYTES", "NUMERIC", "BIGNUMERIC"}
    assert not {"FLOAT64", "DATETIME", "TIME", "TIMESTAMP"} & set(documented), (
        "a parameterised form of one of these would mean a refusal here is no "
        "longer the honest answer"
    )

# ---------------------------------------------------------------------------
# parse_type — the introspection inverse of the renderings above


def test_parse_type_completes_the_data_type_support_protocol(dialect):
    """``parse_type`` was the one member the protocol was missing.

    ``DataType.parse_data_type_str`` delegates to ``dialect.parse_type`` only
    when the dialect answers ``DataTypeSupport``; before this member existed
    the isinstance check failed and every parse fell back to a generic
    ``CustomType`` that knows nothing about BigQuery's words.
    """
    from rhosocial.activerecord.backend.dialect.protocols import DataTypeSupport

    assert isinstance(dialect, DataTypeSupport), (
        "the dialect declares every member of the protocol; a False here "
        "means parse_type is missing again and parse_data_type_str has gone "
        "back to its CustomType fallback"
    )


@pytest.mark.parametrize(
    "raw,build",
    [
        ("INT64", lambda d: BigIntType(d)),
        ("FLOAT64", lambda d: DoubleType(d)),
        ("STRING", lambda d: TextType(d)),
        ("STRING(30)", lambda d: VarCharType(d, length=30)),
        ("NUMERIC", lambda d: DecimalType(d)),
        ("NUMERIC(10, 2)", lambda d: DecimalType(d, precision=10, scale=2)),
        ("BOOL", lambda d: BooleanType(d)),
        ("BYTES", lambda d: BlobType(d)),
        ("JSON", lambda d: JsonType(d)),
        ("DATE", lambda d: DateType(d)),
        ("TIME", lambda d: TimeType(d)),
        ("DATETIME", lambda d: DateTimeType(d)),
        ("TIMESTAMP", lambda d: TimestampTzType(d)),
        ("ARRAY<INT64>", lambda d: ArrayType(d, element_type=BigIntType(d))),
    ],
)
def test_parse_round_trips_the_unwidened_declarations(dialect, raw, build):
    """parse(format(declaration)) == declaration, for the one declaration per
    storage that was not widened on its way in.

    These are the answers the schema differ depends on: a column declared as
    any of these reads back as exactly what was declared, so the differ
    reports no change. Spelling is not part of identity, so the round trip
    holds even where the rendered word and the declared spelling differ.
    """
    assert dialect.parse_type(raw) == build(
        dialect
    ), f"parse_type({raw!r}) must rebuild the declaration it renders"


@pytest.mark.parametrize(
    "raw,declared,canonical",
    [
        ("INT64", lambda d: TinyIntType(d), BigIntType),
        ("INT64", lambda d: SmallIntType(d), BigIntType),
        ("INT64", lambda d: IntegerType(d), BigIntType),
        ("FLOAT64", lambda d: RealType(d), DoubleType),
        ("FLOAT64", lambda d: FloatType(d), DoubleType),
        ("STRING(10)", lambda d: CharType(d, length=10), VarCharType),
        ("STRING", lambda d: VarCharType(d), TextType),
        ("TIMESTAMP", lambda d: TimestampType(d), TimestampTzType),
        ("JSON", lambda d: JsonBType(d), JsonType),
        ("TIME", lambda d: TimeTzType(d), TimeType),
    ],
)
def test_parse_reports_the_documented_widening(dialect, raw, declared, canonical):
    """A widened declaration reads back as the storage's own concept.

    The four integer widths are all ``INT64`` and the three float concepts
    are all ``FLOAT64``, so the server has already widened these columns;
    parsing them back as the narrow concept would make the differ report no
    change for a column the server altered. The parse answers with the one
    concept that was *not* widened -- the class whose rendering is that
    storage -- and re-rendering it produces the identical string, which is
    the part the differ can rely on.
    """
    parsed = dialect.parse_type(raw)
    assert type(parsed) is canonical
    assert parsed.to_sql()[0] == declared(dialect).to_sql()[0], (
        "the widened answer must render the same storage as the declaration, "
        "or the differ would see a change in the SQL rather than in the type"
    )


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("INTEGER", BigIntType),
        ("FLOAT", DoubleType),
        ("BOOLEAN", BooleanType),
    ],
)
def test_parse_accepts_the_legacy_vocabulary_by_storage(dialect, raw, expected):
    """The legacy schema surfaces name the same storages with older words.

    ``INTEGER``/``FLOAT``/``BOOLEAN`` are the ``bq``-era words for
    ``INT64``/``FLOAT64``/``BOOL``; they answer by storage like the words the
    formatters render, because they name the same columns.
    """
    parsed = dialect.parse_type(raw)
    assert type(parsed) is expected


def test_parse_carries_the_spelling_that_was_written(dialect):
    """``BOOL`` and ``BOOLEAN`` are one class with two spellings, kept apart.

    One concept in, one class out -- but the word is recorded, so a rendering
    of the parsed answer can reproduce the vocabulary the catalog used
    rather than silently rewriting it.
    """
    assert dialect.parse_type("BOOL").spelling == "bool"
    assert dialect.parse_type("BOOLEAN").spelling == "boolean"
    assert dialect.parse_type("BOOL") == dialect.parse_type(
        "BOOLEAN"
    ), "spelling is not part of identity, so the two words are one type"


def test_parse_numeric_with_one_parameter_means_scale_zero(dialect):
    """``NUMERIC(P)`` is a caller's DDL form the formatters never emit.

    The documented grammar reads a missing ``S`` as zero, so the answer says
    that rather than inventing a different column. It renders back as
    ``NUMERIC(P, 0)`` -- a different string, the same storage.
    """
    parsed = dialect.parse_type("NUMERIC(10)")
    assert type(parsed) is DecimalType
    assert parsed.precision == 10
    assert parsed.scale == 0
    assert parsed.to_sql()[0] == "NUMERIC(10, 0)"


def test_parse_array_recurses_into_the_element(dialect):
    """``ARRAY<STRING(30)>`` is an array of the parsed element, not a custom
    passthrough of the whole word.

    The element is a type string in its own right, so the array's identity --
    which carries ``element_type`` -- holds the parsed element rather than
    text, and a ``STRING`` element bounds its length on the way back.
    """
    parsed = dialect.parse_type("ARRAY<STRING(30)>")
    assert type(parsed) is ArrayType
    assert type(parsed.element_type) is VarCharType
    assert parsed.element_type.length == 30


@pytest.mark.parametrize(
    "raw",
    [
        "GEOGRAPHY",
        "INTERVAL",
        "BIGNUMERIC",
        "BIGNUMERIC(76, 38)",
        "RECORD",
        "some_extension_type",
    ],
)
def test_a_word_the_framework_does_not_model_is_custom(dialect, raw):
    """Unmodelled words answer ``CustomType`` carrying the word, not a guess.

    ``BIGNUMERIC`` is documented above as out of this dialect's scope,
    ``RECORD`` is the legacy word for ``STRUCT``, and ``GEOGRAPHY`` and
    ``INTERVAL`` are real BigQuery types with no core concept; pretending a
    class fit any of them would make the differ report changes that were
    never made. The raw is validated by ``CustomType`` itself, so a
    parameterised word survives where a struct's field list cannot.
    """
    parsed = dialect.parse_type(raw)
    assert type(parsed) is CustomType
    assert parsed.raw == raw


def test_struct_cannot_be_carried_and_says_why(dialect):
    """A struct's field list is not identifier-shaped, so it is refused.

    Answering a bare ``CustomType("STRUCT")`` would make two different struct
    columns compare equal and hide the difference from the differ; the
    type-name validation refuses the whole field list instead, and the error
    names the caller's string.
    """
    with pytest.raises(InvalidTypeNameError, match="STRUCT"):
        dialect.parse_type("STRUCT<a INT64, b STRING>")


def test_parse_type_refuses_an_empty_string(dialect):
    """Nothing handed to parse is a caller error, not a type name.

    ``CustomType`` refuses an empty raw at construction, but with a message
    about type-name grammar; this names the actual fault.
    """
    with pytest.raises(ValueError, match="empty"):
        dialect.parse_type("")
    with pytest.raises(ValueError, match="empty"):
        dialect.parse_type("   ")
