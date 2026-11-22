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
import re

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


class BigQueryTypeParser:
    """Parse a raw BigQuery type spelling into a ``DataType``, bound to a dialect."""

    #: ``ARRAY<T>`` with the element as a captured group, so the element can be
    #: handed back to :meth:`parse` itself. Decided before any word list
    #: because the element is a type string and the word is not.
    _PARSE_ARRAY_RE = re.compile(r"^ARRAY\s*<\s*(.+?)\s*>$", re.IGNORECASE)
    #: ``STRING`` or ``STRING(L)`` — two answers, not one: the bounded form is a
    #: different concept from the unbounded one.
    _PARSE_STRING_RE = re.compile(r"^STRING(?:\s*\(\s*(\d+)\s*\))?$", re.IGNORECASE)
    #: ``NUMERIC`` / ``NUMERIC(P)``, ``NUMERIC(P, S)``. ``BIGNUMERIC`` does not
    #: match: it is a separate BigQuery type this dialect does not render, and
    #: the word list below never reaches it.
    _PARSE_NUMERIC_RE = re.compile(
        r"^NUMERIC(?:\s*\(\s*(\d+)\s*(?:,\s*(\d+)\s*)?\))?$", re.IGNORECASE
    )

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
        # formatter already refuses by name.
        array_match = self._PARSE_ARRAY_RE.match(stripped)
        if array_match is not None:
            return ArrayType(
                dialect=self.dialect,
                element_type=self.parse(array_match.group(1)),
            )

        # STRING(L) is decided before STRING: a bounded string and an
        # unbounded one are two concepts, not one.
        string_match = self._PARSE_STRING_RE.match(stripped)
        if string_match is not None:
            length = string_match.group(1)
            if length is None:
                return TextType(dialect=self.dialect)
            return VarCharType(dialect=self.dialect, length=int(length))

        # NUMERIC and its parameters. A single parameter means scale 0. This
        # form never comes from a rendering; it comes from a caller's DDL.
        numeric_match = self._PARSE_NUMERIC_RE.match(stripped)
        if numeric_match is not None:
            precision, scale = numeric_match.group(1), numeric_match.group(2)
            if precision is None:
                return DecimalType(dialect=self.dialect)
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
