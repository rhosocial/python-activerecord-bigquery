# src/rhosocial/activerecord/backend/impl/bigquery/introspection/type_parser.py
"""BigQuery's type-spelling parser (read direction, introspection-only).

Core's ``DataType.parse_data_type_str`` is now a no-op that returns a
``CustomType``; parsing a server-reported type spelling back into a ``DataType``
is a backend concern and is not a dialect protocol member. This helper lives
under introspection and is used only when reading back a column's declared type.

It is deliberately NOT installed on the dialect as ``dialect.parse_type``:
there is no compatibility shim on the dialect, and construction of DataType
values in normal code uses the expression classes directly.
"""
from rhosocial.activerecord.backend.expression.types import (
    ArrayType,
    BigIntType,
    BlobType,
    BooleanType,
    CustomType,
    DataType,
    DateTimeType,
    DateType,
    DecimalType,
    DoubleType,
    JsonType,
    TextType,
    TimeType,
    TimestampTzType,
    VarCharType,
)

from .._scan import Scanner


def _leading_word(text: str, word: str) -> "Scanner | None":
    """A scanner positioned after *word*, when *text* starts with that word.

    The comparison is case-insensitive, as the type vocabulary is
    (``string(30)`` is ``STRING(30)``).  It is a whole-word comparison: the
    scanner consumes the maximal letter-and-underscore run, so ``STRINGX``
    is the word ``STRINGX`` and is not the word ``STRING``.
    """
    scanner = Scanner(text)
    found = scanner.take_word()
    if found is None or found.upper() != word:
        return None
    return scanner


def _call(text: str, word: str) -> "tuple[bool, str | None]":
    """Split ``WORD`` or ``WORD(<arguments>)`` and say whether it is that shape.

    Returns ``(matched, arguments)``.  *matched* is ``False`` when *text* is
    not exactly this word, optionally followed by one parenthesised group;
    trailing text refuses it, as the anchored expressions did.  *arguments*
    is the group's interior, or ``None`` when the word was bare.
    """
    scanner = _leading_word(text, word)
    if scanner is None:
        return False, None
    arguments = scanner.take_group("(", ")")
    if not scanner.at_end():
        return False, None
    return True, arguments


def _single_number(arguments: str) -> "str | None":
    """The one digit run in *arguments*, or ``None`` when it is anything else."""
    scanner = Scanner(arguments)
    number = scanner.take_digits()
    if number is None or not scanner.at_end():
        return None
    return number


def _numeric_parameters(arguments: str) -> "tuple[str, str | None] | None":
    """A ``P`` or ``P, S`` pair of digit runs, or ``None`` when it is anything else.

    ``S`` is ``None`` when the comma was absent, which the caller answers as
    scale zero rather than as an error.
    """
    scanner = Scanner(arguments)
    precision = scanner.take_digits()
    if precision is None:
        return None
    scale = None
    if scanner.take_char(","):
        scale = scanner.take_digits()
        if scale is None:
            return None
    if not scanner.at_end():
        return None
    return precision, scale


class BigQueryTypeParser:
    """Parse a raw BigQuery type spelling into a ``DataType``, bound to a dialect."""

    def __init__(self, dialect):
        self.dialect = dialect

    def parse(self, raw: str) -> DataType:
        """Turn a BigQuery type string back into the ``DataType`` it names.

        **One concept in, one class out.** Every word below answers with the
        *one* class whose rendering is that storage. Where a declaration was
        widened on the way in — the four integer widths are all ``INT64``, the
        three float concepts are all ``FLOAT64`` — the parse answers with the
        storage's own concept, which is the one that was *not* widened:
        ``INT64`` is the 64-bit integer (``BigIntType``), ``FLOAT64`` is double
        precision (``DoubleType``), bare ``STRING`` is unbounded text
        (``TextType``), ``STRING(L)`` is the variable-length bounded string
        (``VarCharType``), and ``TIMESTAMP`` is the absolute instant
        (``TimestampTzType``), because a BigQuery ``TIMESTAMP`` is
        UTC-normalised rather than naive.

        **The vocabulary is doubled, and the second half is legacy.** The
        formatters are one vocabulary; the legacy schema surfaces (the ``bq``
        tool and the legacy-format column list) are a second one naming the
        same storages: ``INTEGER``/``FLOAT``/``BOOLEAN`` answer by storage, and
        ``RECORD`` — the legacy word for ``STRUCT`` — falls through to
        ``CustomType``, the framework having no concept for it.

        **A word the framework does not model is ``CustomType``, not a guess.**
        ``GEOGRAPHY``, ``INTERVAL`` and ``BIGNUMERIC`` are real BigQuery types
        with no core concept, so they answer ``CustomType`` carrying the word.
        ``STRUCT<...>`` cannot even be carried — a struct's field list is not
        identifier-shaped, so the type-name validation refuses it and the
        resulting ``InvalidTypeNameError`` names the caller's string.

        Args:
            raw: a type string as the catalog reports it, or as a caller's
                DDL spells it.

        Returns:
            The ``DataType`` naming that storage.

        Raises:
            ValueError: *raw* is empty — nothing was handed to parse.
            InvalidTypeNameError: *raw* names a type whose text cannot be
                carried as a type name at all (``STRUCT<...>``).
        """
        stripped = raw.strip()
        if not stripped:
            raise ValueError("type parser needs a type string; an empty one names nothing")
        upper = stripped.upper()

        # ARRAY<T> first: the element is itself a type string, so the word
        # lists below must not see it. Nested arrays answer structurally —
        # whether the server can hold one is a declaration question the
        # formatter already refuses by name. The angle brackets are counted,
        # so the inner ``>`` of a nested array closes the inner group.
        array_scanner = _leading_word(stripped, "ARRAY")
        if array_scanner is not None:
            element = array_scanner.take_group("<", ">")
            # An empty interior is not an array spelling at all: the outer
            # word lists must see the whole string, as they did before.
            if element is not None and element != "" and array_scanner.at_end():
                return ArrayType(
                    dialect=self.dialect,
                    element_type=self.parse(element),
                )

        # STRING(L) is decided before STRING: a bounded string and an
        # unbounded one are two concepts, not one. A parenthesised form that
        # is not a single length is not answered here at all — it falls
        # through to ``CustomType`` carrying the caller's spelling.
        string_matched, string_arguments = _call(stripped, "STRING")
        if string_matched:
            if string_arguments is None:
                return TextType(dialect=self.dialect)
            length = _single_number(string_arguments)
            if length is not None:
                return VarCharType(dialect=self.dialect, length=int(length))

        # NUMERIC and its parameters. A single parameter means scale 0. This
        # form never comes from a rendering; it comes from a caller's DDL.
        # ``BIGNUMERIC`` is a separate BigQuery type this dialect does not
        # render; it is one word, not the word ``NUMERIC``, so it never
        # reaches these answers.
        numeric_matched, numeric_arguments = _call(stripped, "NUMERIC")
        if numeric_matched:
            if numeric_arguments is None:
                return DecimalType(dialect=self.dialect)
            parameters = _numeric_parameters(numeric_arguments)
            if parameters is not None:
                precision, scale = parameters
                if scale is None:
                    return DecimalType(
                        dialect=self.dialect, precision=int(precision), scale=0
                    )
                return DecimalType(
                    dialect=self.dialect, precision=int(precision), scale=int(scale)
                )

        # Words with no parameters at all: the rendered vocabulary and the
        # legacy one, each answered by its storage. The spelling is carried
        # where the concept has more than one word, so BOOL and BOOLEAN stay
        # distinguishable in the rendering without ever being two classes.
        if upper in ("INT64", "INTEGER"):
            return BigIntType(dialect=self.dialect)
        if upper in ("FLOAT64", "FLOAT"):
            return DoubleType(dialect=self.dialect)
        if upper == "BOOL":
            return BooleanType(dialect=self.dialect, spelling="bool")
        if upper == "BOOLEAN":
            return BooleanType(dialect=self.dialect, spelling="boolean")
        if upper == "BYTES":
            return BlobType(dialect=self.dialect)
        if upper == "JSON":
            return JsonType(dialect=self.dialect)
        if upper == "DATE":
            return DateType(dialect=self.dialect)
        if upper == "TIME":
            return TimeType(dialect=self.dialect)
        if upper == "DATETIME":
            return DateTimeType(dialect=self.dialect)
        if upper == "TIMESTAMP":
            # A BigQuery TIMESTAMP is an absolute point in time, UTC-normalised.
            return TimestampTzType(dialect=self.dialect)

        # Everything else is a word the framework has no concept for, and the
        # honest answer carries the word rather than guessing: GEOGRAPHY,
        # INTERVAL, BIGNUMERIC, RECORD, an extension type.
        return CustomType(dialect=self.dialect, raw=stripped)


__all__ = ["BigQueryTypeParser"]
