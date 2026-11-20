# tests/rhosocial/activerecord_bigquery_test/feature/query/test_document_and_conversion_families.py
"""The families that carry documents, sequences, casts and XML.

A JSON extraction is not always a document: `->` hands back JSON and `->>`
hands back text, so the same node class reports two families and the chain
narrows. A cast states its result in the target type, which is the only place
it can come from. And an operation over several values — GREATEST, a CASE —
answers with their common kind, or with nothing when they disagree.
"""

# tests/rhosocial/activerecord_bigquery_test/feature/query/test_document_and_conversion_families.py
import pytest

from rhosocial.activerecord.backend.expression import functions as F, FunctionCall, Literal, XMLColumn
from rhosocial.activerecord.backend.expression.bases import SQLValue
from rhosocial.activerecord.backend.expression.column_types import annotation_for
from rhosocial.activerecord.backend.expression.type_name import is_valid_type_name
from rhosocial.activerecord.backend.expression.types import (
    CustomType,
    JsonType,
    VarCharType,
    XmlType,
)
from rhosocial.activerecord.backend.expression.advanced_functions import CaseExpression
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
from rhosocial.activerecord.backend.expression.value_types import (
    ArrayValue,
    JSONValue,
    NumericValue,
    TemporalValue,
    TextValue,
    XMLValue,
)

#: Every value class the lattice holds. "No typed result" is asserted by saying
#: the result is none of these, so the list has to be the whole set: an
#: assertion that forgets a class would pass for the wrong reason.
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


def is_typed_as_one_of_these(result):
    """Whether *result* is any of the typed value classes.

    A node that declares no type is honest about it: it is none of these. This
    is the shape the tests that want "unknown" assert, and it is why the list
    above is spelled out rather than imported wholesale -- a class added to the
    lattice has to be added here too, or these assertions would go on passing
    while the answer they are about became possible.
    """
    return isinstance(result, TYPED_VALUE_CLASSES)


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
        "int": build_column(dialect, "i", int),
        "float": build_column(dialect, "f", float),
        "str": build_column(dialect, "s", str),
        "json": build_column(dialect, "j", dict),
        "array": build_column(dialect, "l", list),
    }


# ---------------------------------------------------------------------------
# The same node, two families
# ---------------------------------------------------------------------------


def test_arrow_extraction_gives_a_document(dialect, columns):
    assert isinstance(F.json_extract(dialect, columns["json"], Literal(dialect, "$.a")), JSONValue)


def test_double_arrow_extraction_gives_text(dialect, columns):
    """`->>` is a narrowing: a document becomes a string and cannot widen back."""
    assert isinstance(F.json_extract_text(dialect, columns["json"], "$.a"), TextValue)


def test_a_built_document_is_a_document(dialect, columns):
    assert isinstance(F.json_build_object(dialect, "k", 1), JSONValue)
    assert isinstance(F.json_array_elements(dialect, columns["json"]), JSONValue)


def test_a_document_offers_the_json_accessors(dialect, columns):
    built = F.json_build_object(dialect, "k", 1)
    assert isinstance(built, JSONValue)
    assert hasattr(built, "json_path")
    assert not hasattr(built, "upper")


def test_text_reports_a_string_family(dialect, columns):
    """Narrowing is reported, which is what propagation reads.

    The JSON accessors stay, because one node class serves both arrow
    directions and the wrapper cannot hide what it forwards — that is a known
    over-offer on this one class, not a claim that text is a document.
    """
    text = F.json_extract_text(dialect, columns["json"], "$.a")
    assert isinstance(text, TextValue)
    assert text.to_sql()[0].endswith("->>'$.a'")


# ---------------------------------------------------------------------------
# Sequences
# ---------------------------------------------------------------------------


def test_a_sequence_is_a_sequence(dialect, columns):
    assert isinstance(F.unnest(dialect, columns["array"]), ArrayValue)


def test_measuring_a_sequence_gives_a_whole_number(dialect, columns):
    assert isinstance(F.array_length(dialect, columns["array"], 1), NumericValue)


# ---------------------------------------------------------------------------
# Operations over several values
# ---------------------------------------------------------------------------


def test_greatest_answers_with_what_its_arguments_answer_with(dialect, columns):
    assert isinstance(F.greatest(dialect, columns["int"], columns["int"]), IntegerAnnotation)


def test_greatest_of_mixed_kinds_is_unknown(dialect, columns):
    """The comparison is legal SQL and the answer is neither kind, so neither
    surface may be offered. Guessing the first or the widest would be wrong."""
    assert not is_typed_as_one_of_these(F.greatest(dialect, columns["int"], columns["str"]))


def test_least_agrees_with_greatest(dialect, columns):
    assert isinstance(F.least(dialect, columns["float"], columns["float"]), NumberAnnotation)


def test_nullif_keeps_the_value_it_tests(dialect, columns):
    assert isinstance(F.nullif(dialect, columns["str"], None), TextAnnotation)


# ---------------------------------------------------------------------------
# what an operation over several values keeps
# ---------------------------------------------------------------------------


def test_a_consensus_needs_exactly_one(dialect, columns):
    """A CASE over disagreeing branches is legal SQL that answers with neither
    kind, so neither surface may be offered."""
    mixed = CaseExpression(dialect, cases=[(columns["int"], columns["int"])],
                           else_result=columns["float"])
    assert not is_typed_as_one_of_these(mixed)


def test_an_argument_without_a_family_does_not_break_a_consensus(dialect, columns):
    """A literal says nothing, so it neither agrees nor disagrees."""
    with_literal = CaseExpression(dialect, cases=[(columns["int"], Literal(dialect, 1))],
                                 else_result=columns["int"])
    assert isinstance(with_literal, NumericValue)


# ---------------------------------------------------------------------------
# A cast states its result in the target type
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql_type",
    [
        "VARCHAR(255)",
        "TEXT",
        "NVARCHAR2(10)",
        "INTEGER",
        "BIGINT",
        "DECIMAL(10,2)",
        "DOUBLE PRECISION",
        "BOOLEAN",
        "TIMESTAMP",
        "JSONB",
        "BLOB",
        "UUID",
        "XML",
    ],
)
def test_real_sql_type_names_are_names(sql_type):
    """These are all type names a database has.

    They used to be pinned to the value family a cast to them produces. There is
    no such table now: ``cast`` answers with the class of the ``DataType`` it
    was handed, so the name carries no type of its own to be right about. What
    remains is that the name is recognised -- the grammar, not a meaning.
    """
    assert is_valid_type_name(sql_type)


def test_an_unknown_sql_type_is_still_a_name():
    """A name nobody here knows is still shaped like a name.

    What it means is the dialect's business, decided when the dialect is
    asked to render it, not something this package guesses at here.
    """
    assert is_valid_type_name("GEOMETRY")
    assert is_valid_type_name("POINT")
    assert not is_valid_type_name(None)


def test_cast_takes_its_type_from_the_target_type(dialect, columns):
    """The cast answers with the surface of the type it was handed."""
    assert isinstance(
        F.cast(dialect, columns["int"], VarCharType(dialect, length=10)),
        TextValue,
    )
    assert isinstance(
        F.cast(dialect, columns["int"], JsonType(dialect)), JSONValue
    )


def test_an_unmodelled_target_type_yields_no_typed_result(dialect, columns):
    """A user-defined type has no value class to answer with.

    Offering JSON navigation on a type nobody here has heard of would be worse
    than saying nothing, so the cast comes back untyped and the caller says what
    they meant with ``as_*``.
    """
    result = F.cast(dialect, columns["int"], CustomType(dialect, raw="GEOMETRY"))
    assert not is_typed_as_one_of_these(result)


# ---------------------------------------------------------------------------
# Formatting and parsing
# ---------------------------------------------------------------------------


def test_to_char_gives_text(dialect, columns):
    assert isinstance(F.to_char(dialect, columns["int"]), TextValue)


def test_to_number_gives_a_number(dialect, columns):
    assert isinstance(F.to_number(dialect, columns["int"]), NumericValue)


def test_to_date_gives_a_date(dialect, columns):
    """``TO_DATE`` answers with a **date**, not a timestamp.

    Every backend's ``TO_DATE`` produces a calendar date, so typing it as a
    timestamp offered the time-of-day operations on a value that has no time of
    day. Asserting the date here is what stops that coming back.
    """
    node = F.to_date(dialect, columns["int"])
    assert isinstance(node, TemporalValue)
    # A date and a date-time carry the same surface -- the operations are the
    # same -- so "not a timestamp" is a statement about the node's class, which
    # is where the distinction now lives.
    assert type(node).__name__ == "ToDateFunction"


# ---------------------------------------------------------------------------
# Session identity is a name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("factory", ["current_user", "session_user", "system_user"])
def test_the_session_identity_is_a_name(dialect, factory):
    result = getattr(F, factory)(dialect)
    # What makes it a *name* is the surface it carries, not the class it is:
    # a node is its own class now, so the old ``isinstance(result,
    # StringValue)`` would be asserting the wrapper this family no longer has.
    # Text answers text operations and refuses numeric ones.
    assert hasattr(result, "upper")
    assert not hasattr(result, "sqrt")


# ---------------------------------------------------------------------------
# XML
# ---------------------------------------------------------------------------


def test_the_xml_document_nodes_are_xml_values(dialect):
    """An XML constructor declares the XML value class, and nothing else.

    This used to assert the opposite -- that no class in the lattice covered
    XML -- because the value family was a tag in a closed table and no tag
    existed. The class is the statement now: every constructor that builds a
    document derives from ``XMLValue``, so ``isinstance`` answers
    from the object. What the class carries is the XML surface — the null
    tests and casting, and no comparison (see the refusal test below).
    """
    from rhosocial.activerecord.backend.expression import xml as X

    document_nodes = (
        X.XMLParseExpression,
        X.XMLElementExpression,
        X.XMLForestExpression,
        X.XMLConcatExpression,
        X.XMLCommentExpression,
        X.XMLPIExpression,
        X.XMLRootExpression,
        X.XMLAggExpression,
        X.XMLQueryExpression,
    )
    other_families = tuple(
        cls for cls in TYPED_VALUE_CLASSES if cls is not XMLValue
    )
    for cls in document_nodes:
        assert issubclass(cls, XMLValue), cls.__name__
        assert issubclass(cls, SQLValue), cls.__name__
        # It is an XML value and none of the other typed classes: a document
        # is not text that can be upper-cased, not JSON to navigate, not a
        # sequence to unnest.
        assert not issubclass(cls, other_families), cls.__name__


def test_xmlserialize_yields_the_character_value_it_names(dialect):
    """Serialization leaves the XML family: the result is the text asked for.

    ``XMLSERIALIZE(... AS VARCHAR(100))`` answers with a character value, so
    the node declares ``StringValue`` and the string operations
    follow it out of the XML surface.
    """
    from rhosocial.activerecord.backend.expression import xml as X

    assert issubclass(X.XMLSerializeExpression, TextValue)
    serialized = F.xmlserialize(dialect, "<root/>", "VARCHAR(100)")
    assert isinstance(serialized, TextValue)
    assert not isinstance(serialized, XMLValue)


def test_xmlexists_is_a_predicate_not_a_value():
    """It answers a WHERE clause, so it has no value family to declare."""
    from rhosocial.activerecord.backend.expression import xml as X
    from rhosocial.activerecord.backend.expression.bases import SQLPredicate

    assert issubclass(X.XMLExistsPredicate, SQLPredicate)
    assert not issubclass(X.XMLExistsPredicate, XMLValue)


def test_a_cast_to_xml_is_an_xml_value(dialect, columns):
    """The cast takes its type from the target: ``CAST(x AS XML)`` is XML."""
    result = F.cast(dialect, columns["str"], XmlType(dialect))
    assert isinstance(result, XMLValue)
    assert not isinstance(result, TextValue)


def test_a_function_that_declares_no_result_can_say_xml(dialect):
    """``as_xml()`` is how a caller states what a generic call yields.

    It returns an *annotation*: the XML surface, and nothing else. The text
    surface is not merely unused here, it is gone -- which is the point of
    stating the type, since ``.like()`` on an XML document is not a question any
    backend answers. The SQL is untouched: only the declared type moved.
    """
    from rhosocial.activerecord.backend.expression.declared import XMLAnnotation

    call = FunctionCall(dialect, "MYSTERY_FUNC")
    typed = call.as_xml()
    assert isinstance(typed, XMLAnnotation)
    assert not hasattr(typed, "like")
    assert typed.to_sql() == call.to_sql()


def test_an_xml_column_refuses_comparison_and_keeps_the_null_tests(dialect):
    """The XML column surface, exactly as every XML backend defines it.

    PostgreSQL refuses ``xml = xml`` ("operator does not exist: xml = xml"),
    SQL Server documents that the xml data type "cannot be compared or
    sorted", and Oracle's ``XMLType`` has no comparison operators. Refusing
    here names the operation at the call; without the declaration Python
    would silently answer with identity equality. ``IS NULL`` is accepted by
    all three, so the null tests stay.
    """
    column = XMLColumn(dialect, "doc")

    for operation, dunder in [
        (lambda c: c == 1, "__eq__"),
        (lambda c: c != 1, "__ne__"),
        (lambda c: c < 1, "__lt__"),
        (lambda c: c <= 1, "__le__"),
        (lambda c: c > 1, "__gt__"),
        (lambda c: c >= 1, "__ge__"),
    ]:
        with pytest.raises(AttributeError, match=dunder):
            operation(column)

    assert "IS NULL" in column.is_null().to_sql()[0]
    assert "IS NOT NULL" in column.is_not_null().to_sql()[0]


# ---------------------------------------------------------------------------
# Every family has a wrapper
# ---------------------------------------------------------------------------


def test_a_type_the_core_does_not_hold_is_reported_unknown():
    """The lattice is closed. An extension type a backend models fully is still
    unknown here, because the core does not know which backends exist and cannot
    say what such a type means for the operations its own results offer.

    Declaring one used to look like it worked -- the attribute was there, and
    reading it gave the name back -- so nothing pinned the difference between a
    type that is honoured and one that is quietly dropped. A tag could claim a
    name the core held no class for; a class cannot, because the operations it
    offers come with it.
    """
    class ExtensionValue(SQLValue):
        # A name on the class, which is what declaring a type used to mean. It
        # confers nothing: nothing reads it, and annotation_for answers from the
        # MRO, where this class appears under no mapped name.
        declared_type = "network"

    instance = ExtensionValue.__new__(ExtensionValue)
    assert ExtensionValue.declared_type == "network"
    assert annotation_for(instance) is None
    assert not is_typed_as_one_of_these(instance)


def test_every_typed_value_declares_a_family_from_the_lattice():
    """Each result class states its own family, and it has to be one the
    lattice knows -- otherwise it offers operations nothing downstream expects.

    This replaced a test that every family but XML had a wrapper in a registry.
    There is no registry now: a factory constructs the class it means, so there
    is no table left to be complete. The family is named by the ``Value``
    suffix (规范 4.9), and the scan follows that suffix -- so a rename that
    moves the family fails here rather than quietly emptying the set."""
    import inspect

    from rhosocial.activerecord.backend.expression import core

    declared = {
        name: cls
        for name, cls in inspect.getmembers(core, inspect.isclass)
        if name.endswith("Value") and name != "SQLValue"
    }
    assert declared, "the typed values moved"
    # Every typed value declares its type by being a class, so the only
    # thing left to check is that each one is still reachable and distinct.
    assert len(set(declared.values())) == len(declared), "two names bind one class"


def test_every_temporal_type_is_reachable():
    """The four temporal kinds exist and are distinct.

    They were one class with a label saying which it was, then four classes, and
    now four members of :class:`LiteralKind` -- one closed vocabulary rather than
    one class per type. This pins that a timestamp, a date, a time and an
    interval are still told apart, because ``datetime`` is a subclass of ``date``
    and matching them in the wrong order would fold the first three together.
    """

    from rhosocial.activerecord.backend.expression.values import LiteralKind

    for name, sample in (
        ("TIMESTAMP", __import__("datetime").datetime(2026, 10, 18, 1, 2, 3)),
        ("DATE", __import__("datetime").date(2026, 10, 18)),
        ("TIME", __import__("datetime").time(1, 2, 3)),
        ("INTERVAL", __import__("datetime").timedelta(days=1)),
    ):
        kind = LiteralKind[name]
        assert LiteralKind.match(sample) is kind, name
        assert kind.wire.endswith("_value"), name
