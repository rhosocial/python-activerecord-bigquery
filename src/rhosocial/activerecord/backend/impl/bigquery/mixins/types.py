# src/rhosocial/activerecord/backend/impl/bigquery/mixins/types.py
"""BigQuery type support mixin."""
from __future__ import annotations

import re

from typing import Dict, Tuple

from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError

# Imported for real, not under TYPE_CHECKING: the spelling gates below pass the
# concept class to ``_check_spelling`` as a *value* (it reads ``SPELLINGS`` off
# it), so these names have to exist at runtime. The core types package imports
# no backend, so this does not close a cycle.
from rhosocial.activerecord.backend.expression.types import (
    ArrayType,
    BigIntType,
    BlobType,
    BooleanType,
    CharType,
    CustomType,
    DataType,
    DateTimeType,
    DateType,
    DecimalType,
    DoubleType,
    FloatType,
    IntegerType,
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
    VarCharType,
)


class BigQueryTypeSupportMixin:
    """BigQuery data type support and formatting.

    Maps generic expression-layer types onto BigQuery Standard SQL column types.

    Why this backend owns no ``DataType`` subclass
    ---------------------------------------------
    BigQuery's type list is closed, documented and short, and almost every
    entry is a *spelling* of a concept core already models: ``INT64`` is an
    integer, ``STRING`` is character data, ``NUMERIC`` is exact fixed-point,
    ``BOOL`` is a boolean, ``BYTES`` is a byte string, ``JSON`` is JSON. So the
    backend declares formatters for the core concepts and substitutes the rest
    (see :meth:`suggested_data_types`), and a subclass of ``DataType`` would
    only add a second name for a type that already has one.

    The three BigQuery types with no core concept — ``GEOGRAPHY``,
    ``BIGNUMERIC`` and ``RANGE`` — are reachable today as a
    :class:`~...expression.types.custom.CustomType`, which this mixin renders;
    when they grow classes of their own, they sit on the root ``DataType`` and
    their docstrings must say why there is no core concept to inherit.

    Every concept is *declared* one way or the other: rendered (a
    ``format_data_type_<name>`` / ``supports_data_type_<name>`` pair) or
    substituted (an entry in ``suggested_data_types()``). Silence is the one
    answer that is not allowed — it leaves a caller who asked told only that
    the type is unsupported.

    Where several concepts render as the same BigQuery type — the four integer
    widths are all ``INT64``, the three character concepts are all ``STRING``
    — that is a documented substitution, not an accident: the concepts differ
    in a range or a length convention, and BigQuery does not encode either in
    the column type. Each formatter says which.

    Collapsing a *width* is one thing; collapsing the signedness field would be
    another, and it does not happen here: ``unsigned`` is in the integer
    concepts' ``PARAMETERS``, and since BigQuery has no unsigned integer to
    collapse it onto, every one of the four integer formatters refuses it by
    name rather than rendering the same ``INT64`` either way. See
    :meth:`_refuse_unsigned_integer`.

    The same rule governs every other field that is part of a type's identity,
    and on this backend it comes down to one fact: **BigQuery's own reference
    enumerates which of its types can carry a parameter at all, and the list has
    four members** — ``STRING``, ``BYTES``, ``NUMERIC``, ``BIGNUMERIC`` — for
    each of which the same page documents a parameterised form under its own
    heading (``STRING(L)``, ``BYTES(L)``, ``NUMERIC(P[,S])``,
    ``BIGNUMERIC(P[,S])``).  ``FLOAT64``, ``DATETIME``, ``TIME`` and
    ``TIMESTAMP`` have no such heading, no such row and no entry in the list;
    and ``CREATE TABLE``'s ``column_schema`` is a ``simple_type`` followed by
    column attributes, with no type-modifier position at all, so ``FLOAT64(24)``
    or ``TIMESTAMP(3)`` is not a declaration BigQuery's grammar admits.
    https://cloud.google.com/bigquery/docs/reference/standard-sql/data-types
    https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language

    So the fields that cannot be honoured are refused, one group at a time, and
    each group is refused on its own evidence rather than by analogy with the
    next one:

    * ``unsigned`` on the four integer concepts — see
      :meth:`_refuse_unsigned_integer`;
    * ``precision`` on ``FloatType`` — see :meth:`_refuse_float_precision`;
    * ``precision`` on the five date/time concepts — see
      :meth:`_refuse_temporal_precision`, whose docstring says why ``DATETIME``,
      ``TIME`` and ``TIMESTAMP`` reach the same answer by three different
      documented routes;
    * ``scale`` on ``DecimalType`` when no ``precision`` accompanies it — see
      :meth:`format_data_type_decimal`.

    None of these is the *third* answer, "this field does not belong to the
    concept, so remove it from ``PARAMETERS``", and the distinction is worth
    stating because it is the one that is easy to get wrong.  ``precision``
    belongs to ``FLOAT[(p)]``, ``TIME[(p)]`` and ``TIMESTAMP[(p)]`` in
    SQL:2016 and is honoured by the backends whose types can carry it;
    deleting it from ``PARAMETERS`` would make ``FloatType(precision=24)`` and
    ``FloatType(precision=53)`` the *same column on every backend*, including the
    ten that render them differently.  What is missing here is not the field but
    the place to put it, which is a fact about this backend's type list and
    nothing about the concept — precisely the case :attr:`DataType.PARAMETERS`
    says to answer with a refusal.

    The other direction needs saying too, because the four parameterised types
    are also where a *number* can be wrong.  A refusal says "this grammar has no
    way to say that"; a range check says "this server will reject that number",
    and the two are answered with different exceptions on purpose:

    * a value outside the range the vendor documents raises ``ValueError`` —
      see :meth:`_check_numeric_parameters` for ``NUMERIC``'s
      ``0 <= S <= 9`` / ``max(1, S) <= P <= S + 29`` and
      :meth:`_check_string_length` for ``STRING(L)``'s "a positive ``INT64``
      value";
    * a declaration with no spelling at all raises ``UnsupportedFeatureError``,
      which carries the dialect name and a ``suggestion``.

    Neither answer clamps.  Rounding a scale into range or writing a neighbouring
    ``(P, S)`` would hand the caller a column other than the one they declared,
    which is the same defect as dropping the field on the floor.
    """

    # ------------------------------------------------------------------
    # Integer family — all four concepts are INT64 here
    # ------------------------------------------------------------------

    def _refuse_unsigned_integer(
        self,
        data_type: "TinyIntType | SmallIntType | IntegerType | BigIntType",
        concept_word: str,
    ) -> None:
        """Refuse ``unsigned=True``, because BigQuery has no unsigned integer.

        The core integer concepts carry signedness as a field rather than as a
        class, so ``IntegerType(unsigned=True)`` is constructible and the flag
        reaches the formatter.  It is also in ``PARAMETERS``, hence in
        ``__eq__``/``__hash__``, hence two declarations differing only in it are
        different columns — so the flag has to change the rendered SQL or stop
        the render.  Writing ``INT64`` for an unsigned request would create a
        column that accepts the negatives the caller declared it would not, and
        report success: the same silent loss as accepting the flag and
        discarding it, which is what this replaces.

        What the documentation says, which is why the answer is a refusal
        rather than a rewrite:

        * BigQuery's type list is **closed and enumerated**, and it has exactly
          one integer entry: ``INT64``, documented as -9223372036854775808 to
          9223372036854775807.  ``INT``, ``SMALLINT``, ``INTEGER``, ``BIGINT``,
          ``TINYINT`` and ``BYTEINT`` are documented *aliases of that same
          ``INT64``* — one type under seven names, not seven widths and not two
          signednesses.  The rest of the inventory is ``NUMERIC``,
          ``BIGNUMERIC``, ``FLOAT64``, ``BOOL``, ``STRING``, ``BYTES``,
          ``DATE``, ``DATETIME``, ``TIME``, ``TIMESTAMP``, ``GEOGRAPHY``,
          ``JSON``, ``ARRAY``, ``STRUCT``, ``RANGE`` and ``INTERVAL``: there is
          no unsigned row anywhere, and a closed list is what makes the absence
          evidence rather than a gap.
          https://cloud.google.com/bigquery/docs/reference/standard-sql/data-types
        * There is not even a spelling that would parse.  ``CREATE TABLE``
          takes ``<column_definition> ::= column_name column_schema``, and
          ``column_schema`` is ``column_type`` followed by ``NOT NULL``,
          ``DEFAULT``, ``PRIMARY KEY``, ``REFERENCES``, ``DESC``,
          ``CLUSTER BY`` and ``OPTIONS(...)`` — a nullability and a set of
          column attributes, never a type modifier.  ``INT64 UNSIGNED`` is not
          a column declaration BigQuery's grammar admits.
          https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language
        * ``INTERVAL`` is the one place an unsigned-looking word appears near
          an integer, and it is not one: ``INTERVAL int64_expression
          datetime_part`` is the *operand* of date arithmetic, an ``INT64``
          count of one unit, and ``INTERVAL`` is a duration type rather than a
          column type on this backend at all (see
          :meth:`suggested_data_types`).

        The signed range does cover every width's unsigned range, so nothing is
        lost by dropping the *concept* on this backend; what would be lost is
        the caller's statement that this particular column holds no negative
        value, and that belongs in a ``CHECK`` constraint.

        ``concept_word`` is the width the caller asked for, not the word this
        backend writes — all four render ``INT64``, so naming the requested
        width is the only way the message can say *which* of the four was
        refused.
        """
        if not data_type.unsigned:
            return
        raise UnsupportedFeatureError(
            self.name,
            f"an unsigned {concept_word} column "
            f"(BigQuery has no unsigned integer type; every integer concept is "
            f"INT64, one signed 64-bit type documented as -9223372036854775808 "
            f"to 9223372036854775807, and INT, SMALLINT, INTEGER, BIGINT, "
            f"TINYINT and BYTEINT are documented aliases of that same signed "
            f"type rather than widths of their own)",
            suggestion=(
                "Declare the column signed and enforce the range with a CHECK "
                "constraint if negatives must be rejected."
            ),
        )

    def supports_data_type_tinyint(self) -> bool:
        return True

    def format_data_type_tinyint(self, data_type: TinyIntType) -> Tuple[str, tuple]:
        """``TINYINT`` / ``INT1`` — the 1-byte integer concept, rendered ``INT64``.

        BigQuery has exactly one integer type: ``INT64``, a signed 64-bit value
        in an 8-byte column. So the four integer concepts do not differ in
        *storage* on this backend — they differ only in the range a value is
        expected to occupy, and that range is checked when the value is read or
        written rather than by the column's type. Rendering the narrowest of
        them as ``INT64`` is therefore a documented widening: the column is
        eight bytes where a 1-byte column would have been. Every value a
        ``TINYINT`` could hold is representable, so nothing is lost but the
        space.

        Both spellings are accepted because the caller asked for one concept,
        not for a word. Refusing either would make the concept unusable here
        without adding anything a widened column does not already say.

        ``unsigned`` is refused rather than ignored; see
        :meth:`_refuse_unsigned_integer`, which is also where the reason for
        the refusal is written down.
        """
        self._check_spelling(data_type, TinyIntType)
        self._refuse_unsigned_integer(data_type, "TINYINT")
        return "INT64", ()

    def supports_data_type_smallint(self) -> bool:
        return True

    def format_data_type_smallint(self, data_type: SmallIntType) -> Tuple[str, tuple]:
        """``SMALLINT`` / ``INT2`` — the 2-byte integer concept, rendered ``INT64``.

        Widened for the reason given in :meth:`format_data_type_tinyint`: one
        integer type on this backend, so the width is a value constraint rather
        than a storage property.

        ``unsigned`` is refused rather than ignored; see
        :meth:`_refuse_unsigned_integer`.
        """
        self._check_spelling(data_type, SmallIntType)
        self._refuse_unsigned_integer(data_type, "SMALLINT")
        return "INT64", ()

    def supports_data_type_integer(self) -> bool:
        return True

    def format_data_type_integer(self, data_type: IntegerType) -> Tuple[str, tuple]:
        """``INTEGER`` / ``INT`` — rendered ``INT64``.

        ``INT`` is SQL's own shorthand for ``INTEGER``, so both spellings are
        accepted; BigQuery writes neither and writes ``INT64``, which is the
        same 8-byte signed integer under its own name.

        ``unsigned`` is refused rather than ignored; see
        :meth:`_refuse_unsigned_integer`.
        """
        self._check_spelling(data_type, IntegerType)
        self._refuse_unsigned_integer(data_type, "INT")
        return "INT64", ()

    def supports_data_type_bigint(self) -> bool:
        return True

    def format_data_type_bigint(self, data_type: BigIntType) -> Tuple[str, tuple]:
        """``BIGINT`` / ``INT8`` — rendered ``INT64``.

        The only integer width BigQuery names, so this one is a rename rather
        than a widening: ``INT8`` and ``BIGINT`` are 64-bit signed integers and
        ``INT64`` is 64-bit signed. It is rendered as ``INT64`` because
        ``BIGINT`` is not in BigQuery's DDL grammar at all.

        ``unsigned`` is refused rather than ignored; see
        :meth:`_refuse_unsigned_integer`.
        """
        self._check_spelling(data_type, BigIntType)
        self._refuse_unsigned_integer(data_type, "BIGINT")
        return "INT64", ()

    # ------------------------------------------------------------------
    # Floating point — all three concepts are FLOAT64 here
    # ------------------------------------------------------------------

    def supports_data_type_real(self) -> bool:
        return True

    def format_data_type_real(self, data_type: RealType) -> Tuple[str, tuple]:
        """``REAL`` — the 4-byte IEEE 754 binary32 concept, rendered ``FLOAT64``.

        BigQuery has one floating-point type, ``FLOAT64``, which is 8-byte
        binary64, so the column is twice as wide as a ``REAL`` column would be.
        The widening loses nothing representable: every binary32 value is
        exactly a binary64 value.

        ``unsigned`` is refused rather than ignored; see
        :meth:`_refuse_unsigned_numeric`, and note what this particular refusal
        has to say, because it is the case the briefing for this field got
        backwards.

        **On this backend the field is being dropped on a concept whose storage
        is a *different* concept**, so the message must name the concept rather
        than the word that is about to be written.  A ``REAL`` column here is
        physically a ``FLOAT64`` column — binary64, the storage
        :class:`DoubleType` would also ask for — while T-SQL and SQLite both keep
        ``REAL`` distinct from their double-precision type.  Two declarations
        differing only in ``unsigned`` therefore produce two byte-identical
        ``FLOAT64`` columns differing only in what they *store*, and a caller
        reading "an unsigned FLOAT64 column" could reasonably conclude a
        ``REAL`` and a ``DOUBLE`` are the same column here.  They are not: they
        remain different concepts, and the helper is handed ``"REAL"`` precisely
        so the message says which one was refused.

        The refusal is checked before the widening is returned and there is
        nothing else to check first: ``RealType`` carries ``unsigned`` as its
        only parameter, and ``FLOAT64`` takes neither ``precision`` nor
        ``scale`` (BigQuery's own REST reference: "It is invalid to set
        precision or scale if type != 'NUMERIC' and != 'BIGNUMERIC'").  A signed
        ``RealType`` still renders ``FLOAT64``, unchanged.

        No live BigQuery server was reachable from the machine this was written
        on, so the citations here are BigQuery's documentation and not a
        measurement.
        """
        self._refuse_unsigned_numeric(data_type, "REAL")
        return "FLOAT64", ()

    def _refuse_unsigned_numeric(self, data_type, concept_word: str) -> None:
        """Refuse ``unsigned=True`` on ``DECIMAL``, ``FLOAT``, ``REAL`` or ``DOUBLE``.

        The same field reaches these four concepts that it reaches the four
        integer widths -- ``DecimalType``, ``FloatType``, ``RealType`` and
        ``DoubleType`` each carry ``unsigned`` in ``PARAMETERS``, hence in
        ``__eq__``/``__hash__``, hence two declarations differing only in it are
        different columns -- and BigQuery's answer is the same refusal as
        :meth:`_refuse_unsigned_integer`, on this backend's own grounds:

        * **The inventory is closed and has no unsigned row for any of them.**
          BigQuery documents exactly one approximate-numeric entry, ``FLOAT64``
          ("Double precision (approximate) numeric values"), and exactly two
          exact fixed-point ones, ``NUMERIC`` and ``BIGNUMERIC``.  That is the
          whole of it: ``INT64``, ``NUMERIC``, ``BIGNUMERIC``, ``FLOAT64``,
          ``BOOL``, ``STRING``, ``BYTES``, ``DATE``, ``DATETIME``, ``TIME``,
          ``TIMESTAMP``, ``GEOGRAPHY``, ``JSON``, ``ARRAY``, ``STRUCT``,
          ``RANGE`` and ``INTERVAL``.  An approximate type is not something a
          signedness attribute can be attached to, and a closed list is what
          makes the absence evidence rather than a gap.
          https://cloud.google.com/bigquery/docs/reference/standard-sql/data-types
        * **``FLOAT64`` is IEEE binary64, whose field layout has a signed
          exponent**, so there is no unsigned binary format for a column to be.
          ``NUMERIC`` is signed just as visibly: BigQuery's own REST reference
          documents the values a ``NUMERIC`` field may hold as the symmetric
          interval ``[-10^(P-S), 10^(P-S) - 10^(-S)]`` when precision ``P`` and
          scale ``S`` are set, and ``[-10^P + 1, 10^P - 1]`` when only ``P`` is.
          https://googleapis.dev/dotnet/Google.Apis.Bigquery.v2/v2.0.0/Api/Google.Apis.Bigquery.v2.Data.TableFieldSchema.html
        * **The parameter surface is exactly ``(precision, scale)``, and nothing
          else.**  That same REST entry says of ``Precision``/``Scale``: "It is
          invalid to set precision or scale if type != 'NUMERIC' and !=
          'BIGNUMERIC'", and "If scale is specified but not precision, then it is
          invalid" -- so the two numbers are the only modifiers BigQuery's own
          API admits on its exact fixed-point type, and neither one is a
          signedness.
        * **There is not even a spelling that would parse.**
          ``CREATE TABLE`` takes ``<column_definition> ::= column_name
          column_schema``, ``column_schema`` is ``column_type`` followed by
          ``NOT NULL``, ``DEFAULT``, ``PRIMARY KEY``, ``REFERENCES``, ``DESC``,
          ``CLUSTER BY`` and ``OPTIONS(...)``, and ``column_type`` is a bare type
          name from the list above.  That is a nullability and a set of column
          attributes, never a type modifier, so ``NUMERIC UNSIGNED`` and
          ``FLOAT64 UNSIGNED`` are not column declarations BigQuery's grammar
          admits.
          https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language

        Writing bare ``NUMERIC`` or ``FLOAT64`` for an unsigned request would
        create a column that accepts the negatives the caller declared it would
        not, and report success: the same silent loss as accepting the flag and
        discarding it, which is what this replaces.

        ``concept_word`` is the concept the caller asked for, not the word this
        backend writes -- ``FLOAT``, ``REAL`` and ``DOUBLE PRECISION`` all render
        ``FLOAT64``, and ``DECIMAL``/``NUMERIC``/``DEC`` all render ``NUMERIC``
        -- so naming the requested concept is the only way the message can say
        *which* of them was refused.  ``REAL`` is the sharpest case: BigQuery has
        no 4-byte floating-point type at all, so an unsigned ``REAL`` would be
        dropped on a column whose storage is the same ``FLOAT64`` a
        ``DOUBLE PRECISION`` asks for, and a message naming only the rendered
        word would leave the caller thinking the two concepts are one column.

        No live BigQuery server was reachable from the machine this was written
        on, so the citations above are BigQuery's documentation and not a
        measurement.

        Note that ``_refuse_float_precision`` already refuses ``precision`` for
        ``FLOAT`` and this refuses ``unsigned`` for the same concept: two fields,
        two reasons, two messages.  Neither is a version gate.  ``FloatType()``
        with neither set still renders ``FLOAT64`` perfectly well.

        ``UnsupportedFeatureError``, not ``ValueError``: a declaration this
        grammar cannot express at all, not a wrong value.  The two do not share
        a base class, and the project's cross-backend rule keeps them apart so a
        caller can catch one type for the same refusal everywhere.
        """
        if not data_type.unsigned:
            return
        raise UnsupportedFeatureError(
            self.name,
            f"an unsigned {concept_word} column "
            f"(BigQuery has no unsigned floating-point or fixed-point type: its "
            f"inventory is closed and enumerates one approximate numeric type, "
            f"FLOAT64, documented as 'Double precision (approximate) numeric "
            f"values', and two exact fixed-point ones, NUMERIC and BIGNUMERIC, "
            f"with no unsigned row for any of them; FLOAT64 is IEEE binary64 "
            f"whose field layout has a signed exponent; and BigQuery's own REST "
            f"reference documents a NUMERIC field's values as the symmetric "
            f"interval [-10^(P-S), 10^(P-S) - 10^(-S)], so there is no second, "
            f"unsigned numeric type for the request to move to)",
            suggestion=(
                "Declare the column signed and enforce the range with a CHECK "
                "constraint if negatives must be rejected."
            ),
        )

    def _refuse_float_precision(self, data_type: FloatType) -> None:
        """Refuse ``precision``, because ``FLOAT64`` is not a parameterised type.

        ``precision`` is in ``FloatType.PARAMETERS``, so it reaches
        ``identity()``: ``FloatType(precision=24)`` and ``FloatType(precision=53)``
        are *different columns* as far as the schema differ is concerned, and it
        reports a change between them.  The formatter used to render ``FLOAT64``
        for both, so that change produced byte-identical DDL and the differ
        reported a migration that would not have changed anything.  That is the
        paradigm violation, and it is not redeemed by the fact that ``FLOAT64``
        happens to be a *wider* type than the one requested: the caller asked for
        a column that keeps 24 bits of mantissa and got one that keeps 53, and
        nothing said so.

        What the documentation says, which is why the answer is a refusal:

        * BigQuery has **one** floating-point type.  Its entry reads, in full,
          ``FLOAT64 — Double precision (approximate) numeric values``; there is
          no second row, and the page documents no ``FLOAT64(p)``.
          https://cloud.google.com/bigquery/docs/reference/standard-sql/data-types
        * ``FLOAT64`` is not among the types that can carry a parameter.  The
          page's "Parameterized data types" section says: "You can use
          parameters to specify constraints for the following data types:
          STRING, BYTES, NUMERIC, BIGNUMERIC" — a closed list of four, each with
          its own parameterised heading on the same page.  A closed list is what
          makes the absence evidence rather than a gap.  The three that *are*
          parameterised take one kind of parameter each — a maximum character
          count, a maximum byte count, a precision and a scale — and none of them
          is a binary mantissa width.
        * There is no spelling that would parse either.  ``column_schema`` is
          ``simple_type`` followed by ``PRIMARY KEY``, ``DEFAULT``, ``NOT NULL``
          and ``OPTIONS(...)``, and ``simple_type`` is a bare ``data_type`` (or
          ``STRING COLLATE ...``): the grammar has no type-modifier position, so
          ``FLOAT64(24)`` is not a column declaration BigQuery admits.
          https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language

        Nothing is version-gated here.  The parameterised list above is the whole
        list, not a snapshot of one release, and the release notes mention
        "parameterized" only for *parameterized queries* in the query editor —
        never a parameterised ``TIMESTAMP`` or ``FLOAT64``.  So the refusal does
        not belong in ``supports_data_type_float()``, which stays unconditional:
        ``FloatType()`` with no precision still renders ``FLOAT64`` perfectly
        well, and it is only the *field* that cannot be honoured.
        https://cloud.google.com/bigquery/docs/release-notes
        """
        if data_type.precision is None:
            return
        raise UnsupportedFeatureError(
            self.name,
            f"a FLOAT(p) column declared with precision="

            f"{data_type.precision} (BigQuery has one floating-point type, "
            f"FLOAT64, documented as 'Double precision (approximate) numeric "
            f"values', and FLOAT64 is not one of the four types BigQuery's own "
            f"reference says can carry a parameter - STRING, BYTES, NUMERIC and "
            f"BIGNUMERIC - so there is no FLOAT(p) declaration to write, and no "
            f"second floating-point type for the request to move to)",
            suggestion=(
                "Declare FloatType with no precision, which is the FLOAT64 "
                "column this backend stores; if the request was about digits "
                "rather than binary mantissa width, DecimalType is BigQuery's "
                "exact fixed-point type and does take a precision and a scale "
                "(NUMERIC(P,S))."
            ),
        )

    def supports_data_type_float(self) -> bool:
        return True

    def format_data_type_float(self, data_type: FloatType) -> Tuple[str, tuple]:
        """``FLOAT(p)`` — a binary precision — rendered ``FLOAT64``.

        SQL's ``FLOAT(p)`` names a *precision*, and BigQuery has no
        parameterised floating-point type to put it in: ``FLOAT64`` is the only
        one, and it is always binary64.  So the concept survives as the column
        it can be — 8-byte binary64, which holds every binary32 value exactly,
        so nothing representable is lost — but the *precision* cannot, and it is
        refused by name rather than thrown away; see
        :meth:`_refuse_float_precision`, which is also where the evidence is
        written down.

        The distinction matters because a widening is a substitution and a
        discarded precision is not.  A caller who declared ``FLOAT(24)`` is not
        asking for a wider column to be substituted for a narrower one; they
        declared a column whose storage they believe is 24 bits of mantissa, and
        a substitution cannot answer that, only a refusal can.

        ``unsigned`` is refused too, and for the same reason from the other end:
        see :meth:`_refuse_unsigned_numeric`.  The two refusals are checked in
        the order the fields are declared in ``PARAMETERS``, so the precision one
        fires first for a request that set both.
        """
        self._refuse_float_precision(data_type)
        self._refuse_unsigned_numeric(data_type, "FLOAT")
        return "FLOAT64", ()

    def supports_data_type_double(self) -> bool:
        return True

    def format_data_type_double(self, data_type: DoubleType) -> Tuple[str, tuple]:
        """``DOUBLE`` / ``DOUBLE PRECISION`` — rendered ``FLOAT64``.

        ``FLOAT64`` *is* this concept: 8-byte IEEE 754 binary64, under
        BigQuery's name. Neither ``DOUBLE`` nor ``DOUBLE PRECISION`` is in
        BigQuery's DDL grammar, so both spellings are accepted and normalised.

        ``unsigned`` is refused rather than ignored; see
        :meth:`_refuse_unsigned_numeric`.  Nothing is lost by that on this
        backend: ``FLOAT64`` is binary64 either way, whose range is symmetric
        about zero and whose field layout has a signed exponent, so there is no
        unsigned double-precision column for the request to have become.
        """
        self._check_spelling(data_type, DoubleType)
        self._refuse_unsigned_numeric(data_type, "DOUBLE PRECISION")
        return "FLOAT64", ()

    # ------------------------------------------------------------------
    # Exact fixed-point
    # ------------------------------------------------------------------

    def supports_data_type_decimal(self) -> bool:
        return True

    #: BigQuery's own scale range for ``NUMERIC``, transcribed from the
    #: "Parameterized decimal type" table: "Maximum scale range: 0 <= S <= 9".
    #: The bare ``NUMERIC`` is documented as "Precision: 38, Scale: 9", so 9 is
    #: also the largest scale the type has.
    #: https://cloud.google.com/bigquery/docs/reference/standard-sql/data-types
    _BQ_NUMERIC_SCALE_RANGE = (0, 9)

    #: The ``29`` in the precision bound below.  ``NUMERIC``'s precision is
    #: documented as a function of the scale — "Maximum precision range:
    #: max(1, S) <= P <= S + 29" — because precision and scale share one budget of
    #: 38 digits, of which at most this many may sit to the left of the point.
    #: The same page's minimum magnitude ("Minimum value greater than 0 that can
    #: be handled: 1e-9") and maximum ("9.9999999999999999999999999999999999999E+28")
    #: are that budget restated: nine fractional digits, twenty-nine integer ones.
    #: https://cloud.google.com/bigquery/docs/reference/standard-sql/data-types
    _BQ_NUMERIC_MAX_INTEGER_DIGITS = 29

    def _check_numeric_parameters(self, data_type: DecimalType) -> None:
        """Refuse a precision or a scale outside BigQuery's documented envelope.

        The reference states two bounds for ``NUMERIC(P[,S])`` /
        ``DECIMAL(P[,S])``, and both are checked here rather than left to the
        server:

        * "Maximum scale range: 0 <= S <= 9";
        * "Maximum precision range: max(1, S) <= P <= S + 29".

        https://cloud.google.com/bigquery/docs/reference/standard-sql/data-types

        **The precision bound is not "1 to 38".**  It is stated *relative to the
        scale*, and that is the whole of the envelope: precision and scale share
        one 38-digit budget, and 29 of them may sit to the left of the point.  The
        page's own numbers agree — bare ``NUMERIC`` is "Precision: 38, Scale: 9",
        and 38 is exactly 9 + 29, the formula at its largest, while its minimum
        magnitude is ``1e-9`` and its maximum is ``...E+28``, the same statement
        from the other end.  So the reachable precisions are 1 to 38 as a set, but
        only at the scales that allow them: at scale 9 the ceiling is the
        documented 38, and at scale 0 it is 29.

        That has a consequence worth stating rather than hiding:
        ``NUMERIC(38, 0)`` is *outside* the envelope, and not because 38 is too
        many digits — it is the documented maximum — but because at scale 0 it
        asks for 38 digits to the left of the point, and the type holds at most
        29.  So the check is on the pair, and the error says which pair it was.

        Nothing is clamped, rounded or defaulted into range.  Writing the
        declaration anyway sends the caller a statement the server rejects;
        substituting a neighbouring ``(P, S)`` is worse still, because it hands
        back a column that is not the one that was declared and reports success.
        A value outside the envelope therefore names itself and the bound it
        broke.

        ``ValueError``, and not ``UnsupportedFeatureError``: ``NUMERIC(P[,S])``
        is a parameterised form this grammar expresses perfectly well, so this is
        not a declaration BigQuery cannot say.  It is a number outside the range
        this server accepts.  The two exceptions are not interchangeable — they
        do not share a base class — and only the second one carries a route
        forward, which is why the distinction is kept rather than blurred.
        """
        lowest_scale, highest_scale = self._BQ_NUMERIC_SCALE_RANGE
        scale = data_type.scale
        if scale is not None and not (lowest_scale <= scale <= highest_scale):
            raise ValueError(
                f"BigQuery NUMERIC scale must be "
                f"{lowest_scale}-{highest_scale}, got {scale} "
                f"(BigQuery's own parameterized-decimal table documents 'Maximum "
                f"scale range: 0 <= S <= 9', and the same table bounds the "
                f"precision by 'max(1, S) <= P <= S + 29' - so a scale of "
                f"{scale} is outside the NUMERIC envelope whatever precision it "
                f"is declared with)"
            )
        precision = data_type.precision
        if precision is None:
            return
        # A declared precision with no scale is NUMERIC(P[,0]): the reference
        # says "S is interpreted to be 0 if unspecified", which is also what the
        # bare NUMERIC(p) form means.  So the envelope is evaluated at S = 0 -
        # and that is precisely why a large precision cannot be declared alone.
        effective_scale = lowest_scale if scale is None else scale
        lowest_precision = max(1, effective_scale)
        highest_precision = effective_scale + self._BQ_NUMERIC_MAX_INTEGER_DIGITS
        if lowest_precision <= precision <= highest_precision:
            return
        raise ValueError(
            f"BigQuery NUMERIC precision must be {lowest_precision}-"
            f"{highest_precision} at scale {effective_scale}, got {precision} "
            f"(BigQuery's own parameterized-decimal table documents 'Maximum "
            f"precision range: max(1, S) <= P <= S + 29' - precision and scale "
            f"share one 38-digit budget of which at most "
            f"{self._BQ_NUMERIC_MAX_INTEGER_DIGITS} digits may sit left of the "
            f"point, so the reachable precisions run 1 to "
            f"{highest_scale + self._BQ_NUMERIC_MAX_INTEGER_DIGITS} across all "
            f"scales but only up to {highest_precision} at the scale declared "
            f"here; the {highest_scale + self._BQ_NUMERIC_MAX_INTEGER_DIGITS} "
            f"figure is the documented precision of bare NUMERIC, which is "
            f"scale {highest_scale})"
        )

    def format_data_type_decimal(self, data_type: DecimalType) -> Tuple[str, tuple]:
        """``DECIMAL`` / ``NUMERIC`` / ``DEC`` — rendered ``NUMERIC``.

        BigQuery's exact fixed-point type, and it takes the same
        ``NUMERIC(precision, scale)`` parameters, so a precision and scale
        declared on the generic type survive unchanged.

        ``NUMERIC`` here is 38 digits of precision with 9 digits of scale by
        default. BigQuery also has ``BIGNUMERIC`` (76 digits, scale 38), which
        is the wider fixed-point type and has no core concept; it is reachable
        as a ``CustomType`` rather than as a substitution for this one, because
        it is a genuinely different storage size rather than a different
        spelling of ``NUMERIC``.

        **A scale with no precision is refused**, and it is refused rather than
        defaulted because BigQuery's parameter list puts the scale *second*:
        ``NUMERIC(P[,S])``, documented as "A NUMERIC or DECIMAL type with a
        maximum precision of P and maximum scale of S, where P and S are INT64
        types.  S is interpreted to be 0 if unspecified" — that last clause is
        about omitting *S*, and there is no reading in which ``S`` appears on its
        own.  ``0 <= S <= 9`` and ``max(1, S) <= P <= S + 29`` confirm it: the
        scale is a bound on the second parameter, never a standalone one.
        https://cloud.google.com/bigquery/docs/reference/standard-sql/data-types

        Writing bare ``NUMERIC`` for a request that named a scale would also be
        quietly *wrong* rather than merely imprecise.  Bare ``NUMERIC`` is
        precision 38 with scale 9, so it is a different column from the
        ``NUMERIC(P, s)`` the caller had in mind; and a bare ``NUMERIC(P)`` —
        the only other way to reach a scale on this grammar — means scale 0, not
        the default scale of 9.  Saying which of the two is wanted is the
        caller's to make, so the render stops instead of guessing.  PostgreSQL's
        ``numeric(precision, scale)`` has the same shape and is refused there for
        the same reason.

        **A precision or a scale outside the documented envelope is refused
        too**, with ``ValueError`` rather than with the refusal above, because the
        two faults are different: ``scale=2`` alone is a request this grammar
        has no spelling for, while ``scale=12`` or ``precision=30`` are numbers
        ``NUMERIC`` cannot hold at all.  See :meth:`_check_numeric_parameters`,
        which is where both bounds are written out and why the precision bound is
        a function of the scale.

        Note what this is *not*: the scale itself is honoured, loudly and
        visibly, on every request that carries a precision — ``NUMERIC(10, 2)``
        is a different column from ``NUMERIC(10, 0)`` and renders differently.
        Only the un-anchorable request and the out-of-range value are refused.

        ``unsigned`` is refused as well, and by the same method that refuses it
        for the two floating-point concepts; see :meth:
        _refuse_unsigned_numeric`.  It is checked first, before the spelling and
        the parameter envelope, because it is the one of the four
        ``DecimalType`` identity fields that this grammar cannot express at all
        — the other three are all checked below.  ``NUMERIC`` is documented with
        a symmetric signed value range, and ``column_schema`` has no
        type-modifier position, so there is no ``NUMERIC UNSIGNED`` to write.
        """
        self._refuse_unsigned_numeric(data_type, "DECIMAL")
        self._check_spelling(data_type, DecimalType)
        self._check_numeric_parameters(data_type)
        if data_type.scale is not None and data_type.precision is None:
            ranges = (
                "BigQuery requires 0 <= S <= 9 and max(1, S) <= P <= S + 29, so "
                "a bare scale has to be attached to a precision"
            )
            if data_type.scale == 9:
                # Bare NUMERIC *is* precision 38 with scale 9, so this one bare
                # scale has an exact answer and it is the bare declaration.
                opening = (
                    "A bare NUMERIC is already precision 38 with scale 9, so "
                    "DecimalType() is that column"
                )
            else:
                opening = f"Name the precision too: {ranges}"
            raise UnsupportedFeatureError(
                self.name,
                f"a NUMERIC(P,S) column declared with scale={data_type.scale} "
                f"and no precision (BigQuery's parameter list puts the scale "
                f"second: NUMERIC(P[,S]), documented as a maximum precision of "
                f"P and a maximum scale of S where 'S is interpreted to be 0 if "
                f"unspecified', so a scale cannot be declared without a "
                f"precision to put it next to - and there is no other spelling, "
                f"because column_schema has no type-modifier position; "
                f"{ranges})",
                suggestion=(
                    f"{opening}; DecimalType(precision=P, scale=S) renders "
                    f"NUMERIC(P, S), which is the only place a scale has room "
                    f"to go"
                ),
            )
        if getattr(data_type, "precision", None) is not None:
            scale = getattr(data_type, "scale", 0) or 0
            return f"NUMERIC({data_type.precision}, {scale})", ()
        return "NUMERIC", ()

    # ------------------------------------------------------------------
    # Boolean
    # ------------------------------------------------------------------

    def supports_data_type_boolean(self) -> bool:
        return True

    def format_data_type_boolean(self, data_type: BooleanType) -> Tuple[str, tuple]:
        """``BOOLEAN`` / ``BOOL`` — rendered ``BOOL``.

        ``BOOL`` is BigQuery's own (and SQLite's) spelling of the SQL standard's
        ``BOOLEAN``; the standard's word is not in BigQuery's DDL grammar. Both
        spellings are accepted and normalised, since the concept is the same
        two-valued column either way.
        """
        self._check_spelling(data_type, BooleanType)
        return "BOOL", ()

    # ------------------------------------------------------------------
    # Character data — every concept is STRING here
    # ------------------------------------------------------------------

    def supports_data_type_char(self) -> bool:
        return True

    #: The only bound BigQuery's own reference states on the ``L`` of
    #: ``STRING(L)``: "where L is a positive INT64 value".  There is no documented
    #: *ceiling* on ``L`` in the parameterized-string table, so none is invented
    #: here — the 10 MB figure the same reference quotes is a limit on the size of
    #: a stored *value*, not on the declared parameter, and treating it as a
    #: bound would refuse declarations the documentation permits.
    #: https://cloud.google.com/bigquery/docs/reference/standard-sql/data-types
    _BQ_STRING_MINIMUM_LENGTH = 1

    def _check_string_length(self, length) -> None:
        """Refuse a ``STRING(L)`` length BigQuery's own reference excludes.

        The parameterized-string table reads, in full: "String with a maximum of
        L Unicode characters allowed in the string, where **L is a positive
        INT64 value**.  If a string with more than L Unicode characters is
        assigned, throws an OUT_OF_RANGE error."
        https://cloud.google.com/bigquery/docs/reference/standard-sql/data-types

        So the documented bound on the parameter is a lower bound and nothing
        else: ``L >= 1``.  ``None`` means the parameter was not declared at all,
        which is a different thing from declaring one — bare ``STRING`` is
        unbounded — and it is the only other answer this formatter has.

        This is not a cosmetic check.  ``length=0`` used to fall through a
        truthiness test and render the *bare word* ``STRING``: a caller who
        declared a bounded column got an unbounded one and no error at all, which
        is the paradigm violation — the declared column is not the column
        rendered, the SQL does not say so, and nothing reports it.  ``length=-1``
        reached the DDL as ``STRING(-1)``.  Both are now refused, naming the
        value and the bound.

        Nothing is rounded up to 1.  Clamping would be the same defect as the
        silent drop it replaces, wearing a smaller hat: the caller would get
        ``STRING(1)`` rather than the column they asked about.

        ``ValueError``, not ``UnsupportedFeatureError``: ``STRING(L)`` is one of
        the four parameterised forms this grammar has, so there is no missing
        spelling here — the number is simply below the documented minimum.  See
        :meth:`_check_numeric_parameters` for the same distinction applied to
        ``NUMERIC``.

        ``BYTES(L)`` carries the same wording ("where L is a positive INT64
        value") but has nothing to check here: no formatter on this backend emits
        ``BYTES(n)``.  :class:`~...expression.types.blob.BlobType` takes no
        length at all, and the two byte-string concepts that do —
        ``BinaryType`` / ``VarBinaryType`` — are *suggested* rather than
        rendered, so ``format_data_type`` refuses them before any length is read.
        That is the absence of a gap rather than a gap in a check.
        """
        if length is None:
            return
        if length < self._BQ_STRING_MINIMUM_LENGTH:
            raise ValueError(
                f"BigQuery STRING length must be at least "
                f"{self._BQ_STRING_MINIMUM_LENGTH}, got {length} "
                f"(BigQuery's own parameterized-string table documents "
                f"STRING(L) as 'a maximum of L Unicode characters allowed in the "
                f"string, where L is a positive INT64 value'; a length of "
                f"{length} is below that minimum, and 0 in particular cannot be "
                f"rendered as STRING(0) either - bare STRING is unbounded, so "
                f"silently widening a declared bound to no bound at all would "
                f"hand back a column other than the one declared)"
            )

    def format_data_type_char(self, data_type: CharType) -> Tuple[str, tuple]:
        """``CHAR`` / ``CHARACTER`` — rendered ``STRING``.

        BigQuery has one character type, ``STRING``: variable-length UTF-8 up
        to 10 MB, optionally declared with a maximum length. There is no
        fixed-length string and no distinction between blank-padded and
        unpadded text, so when a length is declared it becomes the maximum
        BigQuery enforces — values are not blank-filled and are not required to
        occupy it. The concept is preserved (a bounded run of characters) and
        the *kind* of bound is not, which is the substitution worth stating.

        Both spellings are accepted and render identically.

        A declared length is range-checked against the one bound the reference
        states; see :meth:`_check_string_length`.
        """
        self._check_spelling(data_type, CharType)
        length = getattr(data_type, "length", None)
        self._check_string_length(length)
        # ``is not None`` rather than a truthiness test: a length of 0 is an
        # out-of-range value, not an absent one, and it is refused above instead
        # of quietly widening the column to unbounded STRING.
        return (f"STRING({length})", ()) if length is not None else ("STRING", ())

    def supports_data_type_varchar(self) -> bool:
        return True

    def format_data_type_varchar(self, data_type: VarCharType) -> Tuple[str, tuple]:
        """``VARCHAR`` / ``CHARACTER VARYING`` — rendered ``STRING``.

        Same substitution as :meth:`format_data_type_char`, and here it is not
        even a substitution: a variable-length bounded string is exactly what
        ``STRING(length)`` is. Both spellings render identically, and a declared
        length is range-checked the same way; see :meth:`_check_string_length`.
        """
        self._check_spelling(data_type, VarCharType)
        length = getattr(data_type, "length", None)
        self._check_string_length(length)
        return (f"STRING({length})", ()) if length is not None else ("STRING", ())

    def supports_data_type_text(self) -> bool:
        return True

    def format_data_type_text(self, data_type: TextType) -> Tuple[str, tuple]:
        """``TEXT`` / ``CLOB`` — rendered ``STRING``.

        Unbounded character data, which is what ``STRING`` is. BigQuery has no
        ``TEXT`` type and no ``CLOB``, so both spellings are accepted and
        normalised to the one type that holds this concept. Refusing ``CLOB``
        would refuse a spelling of a type BigQuery does have, which tells the
        caller less than the widened column does.
        """
        self._check_spelling(data_type, TextType)
        return "STRING", ()

    # ------------------------------------------------------------------
    # Date and time
    # ------------------------------------------------------------------

    #: BigQuery's three date/time types, each documented with the fractional
    #: digits it *stores*.  Copied in the refusals below because none of the
    #: three is in BigQuery's own list of types that can carry a parameter, and
    #: "up to six fractional digits (microsecond precision)" is a property of the
    #: stored value, not a knob the column type exposes.
    #: https://cloud.google.com/bigquery/docs/reference/standard-sql/data-types
    _BQ_TEMPORAL_TYPES = {
        "DATETIME": "0001-01-01 00:00:00 to 9999-12-31 23:59:59.999999",
        "TIME": "00:00:00 to 23:59:59.999999",
        "TIMESTAMP": (
            "0001-01-01 00:00:00 to 9999-12-31 23:59:59.999999 UTC"
        ),
    }

    def _refuse_temporal_precision(
        self,
        data_type: "DateTimeType | TimeType | TimeTzType | TimestampType | TimestampTzType",
        concept_word: str,
        bq_word: str,
    ) -> None:
        """Refuse a fractional-seconds ``precision`` on any of the five temporal
        concepts, because none of BigQuery's three temporal types is
        parameterised.

        All five carry ``precision`` in ``PARAMETERS``, so two declarations
        differing only in it are different columns and the differ reports them
        as such.  The formatters used to render the bare word in every case, so
        the differ reported a change that produced byte-identical DDL — and, worse,
        the caller had asked for a column that rounds to a different number of
        fractional digits and had been handed one that does not.

        The five were established separately rather than by analogy, because they
        are not the same case — and the first two must not be assumed uniform
        either, which is what the third one is here to show:

        * ``DATETIME`` — documented "0001-01-01 00:00:00 to 9999-12-31
          23:59:59.999999", "It includes the year, month, day, hour, minute,
          second, and subsecond", and its canonical format's fractional field as
          "Up to six fractional digits (microsecond precision)".  There is no
          ``DATETIME(P)``: the ``(p)`` in SQL's ``DATETIME(P)`` has nowhere to go.
        * ``TIME`` — same shape, documented "00:00:00 to 23:59:59.999999" and the
          same "Up to six fractional digits (microsecond precision)".  The upper
          bound is what the *value* may carry; a ``TIME(3)`` column that rounds
          every reading to milliseconds is a different type, and BigQuery does not
          have one.
        * ``TIMESTAMP`` — this is the one that *looks* different, and it is worth
          spelling out, because it is the reason the other two must not be
          assumed uniform either.  ``TIMESTAMP`` is documented "with microsecond
          precision", and it *has* an internal microsecond resolution.  But that
          is the resolution of the stored value, not a parameter of the type: the
          same page says a timestamp "is typically represented internally as the
          number of elapsed microseconds since a fixed initial point in time",
          which is a statement about how the instant is *kept*, and it is exactly
          why ``TIMESTAMP`` is absent from the parameterised list rather than
          present in it.  Where the reference does accept a microsecond count it
          is as a *date-arithmetic operand* — ``TIMESTAMP_ADD(ts, INTERVAL n
          MICROSECOND)``, ``TIMESTAMP_MICROS(ts)`` — never as a column
          declaration.

        The common evidence is the parameterised list itself, and it is a closed
        one: "You can use parameters to specify constraints for the following data
        types: STRING, BYTES, NUMERIC, BIGNUMERIC", each with its own
        parameterised heading on the same page (``STRING(L)``, ``BYTES(L)``,
        ``NUMERIC(P[,S])``, ``BIGNUMERIC(P[,S])``).  ``DATETIME``, ``TIME`` and
        ``TIMESTAMP`` have no row in it.
        https://cloud.google.com/bigquery/docs/reference/standard-sql/data-types

        And there is no spelling that would parse, because the grammar has no
        type-modifier position: ``column_schema`` is ``simple_type`` followed by
        ``PRIMARY KEY``, ``DEFAULT``, ``NOT NULL`` and ``OPTIONS(...)``, and
        ``simple_type`` is a bare ``data_type``.  ``DATETIME(3)``, ``TIME(3)``
        and ``TIMESTAMP(3)`` are not column declarations BigQuery admits.
        https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language

        Nothing here is version-gated.  The parameterised list is the whole list,
        and the release notes mention "parameterized" only for *parameterized
        queries* in the query editor — there is no release in which ``TIMESTAMP``
        became parameterisable, so no ``supports_data_type_*`` gate belongs here.
        The types themselves stay unconditionally supported: it is the *field*
        that cannot be honoured, not the type.
        https://cloud.google.com/bigquery/docs/release-notes

        ``concept_word`` is the concept the caller asked for and ``bq_word`` the
        BigQuery type it renders as; they differ for the two zoned concepts
        (``TIME WITH TIME ZONE`` and ``TIMESTAMP WITH TIME ZONE`` both render as
        the unzoned BigQuery type), and naming both is what lets the message say
        which declaration was refused rather than only which one would have been
        written.  The suggestion names the *class* instead, read off the instance,
        because "declare TimeTzType with no precision" is something a caller can
        act on and "declare TIME WITH TIME ZONE with no precision" is not.
        """
        if data_type.precision is None:
            return
        raise UnsupportedFeatureError(
            self.name,
            f"a {concept_word} column declared with "
            f"precision={data_type.precision} (BigQuery's {bq_word} takes no "
            f"parameter: its own reference says only STRING, BYTES, NUMERIC and "
            f"BIGNUMERIC can carry one, so {bq_word}(p) is not a declaration "
            f"BigQuery's grammar admits, and {bq_word} already stores "
            f"{self._BQ_TEMPORAL_TYPES[bq_word]} - up to six fractional "
            f"digits, which is the resolution of the value rather than a setting "
            f"of the column type)",
            suggestion=(
                f"Declare {type(data_type).__name__} with no precision, which is "
                f"the {bq_word} column this backend stores; if the value must be "
                f"rounded to fewer fractional digits, truncate it in the "
                f"application, since BigQuery offers no column type that rounds "
                f"for you."
            ),
        )

    def supports_data_type_date(self) -> bool:
        return True

    def format_data_type_date(self, data_type: DateType) -> Tuple[str, tuple]:
        """``DATE`` — a calendar date with no time and no zone."""
        return "DATE", ()

    def supports_data_type_time(self) -> bool:
        return True

    def format_data_type_time(self, data_type: TimeType) -> Tuple[str, tuple]:
        """``TIME`` — a time of day with no date and no zone.

        A declared fractional-seconds ``precision`` is refused rather than
        ignored; see :meth:`_refuse_temporal_precision`.
        """
        self._refuse_temporal_precision(data_type, "TIME", "TIME")
        return "TIME", ()

    def supports_data_type_timetz(self) -> bool:
        return True

    def format_data_type_timetz(self, data_type: TimeTzType) -> Tuple[str, tuple]:
        """``TIME WITH TIME ZONE`` — rendered ``TIME``.

        BigQuery has one time-of-day type and it carries no zone: ``TIME`` is
        the wall-clock reading of a time, unanchored to any offset. So the zone
        part of the concept is dropped and the column does not record which
        offset a reading was written in. That is a real loss and it is a
        substitution, not a rename — it is stated here because the alternative,
        refusing the type, would leave the time of day unreachable on this
        backend.

        The ``precision`` field is a *separate* loss and it is refused, not
        folded into the substitution above: this concept is substituted for
        ``TIME`` and rendered as ``TIME``, and a requested precision still stops
        the render, because ``TIME`` is the very type with no parameter to put it
        in.  See :meth:`_refuse_temporal_precision`.
        """
        self._refuse_temporal_precision(data_type, "TIME WITH TIME ZONE", "TIME")
        return "TIME", ()

    def supports_data_type_datetime(self) -> bool:
        return True

    def format_data_type_datetime(self, data_type: DateTimeType) -> Tuple[str, tuple]:
        """``DATETIME`` — a date and time with no zone and no offset.

        BigQuery has a ``DATETIME`` type with exactly these semantics, so this
        is a rename rather than a substitution.  What is *not* a rename is a
        requested fractional-seconds precision: ``DATETIME`` is documented as
        storing up to six fractional digits and takes no parameter, so that field
        is refused rather than ignored; see :meth:`_refuse_temporal_precision`.
        """
        self._refuse_temporal_precision(data_type, "DATETIME", "DATETIME")
        return "DATETIME", ()

    def supports_data_type_timestamp(self) -> bool:
        return True

    def format_data_type_timestamp(self, data_type: TimestampType) -> Tuple[str, tuple]:
        """``TIMESTAMP`` — rendered ``TIMESTAMP``.

        BigQuery has no zone-less timestamp type to distinguish it from: its
        ``TIMESTAMP`` is an absolute instant normalised to UTC, so the concept
        renders as written.

        ``TIMESTAMP`` does have microsecond precision, which is why it is worth
        saying explicitly that having a precision is not the same as having a
        *parameter*: the microsecond is the resolution the value is stored at, so
        a declared ``precision`` still stops the render.  See
        :meth:`_refuse_temporal_precision`.
        """
        self._refuse_temporal_precision(data_type, "TIMESTAMP", "TIMESTAMP")
        return "TIMESTAMP", ()

    def supports_data_type_timestamptz(self) -> bool:
        return True

    def format_data_type_timestamptz(self, data_type: TimestampTzType) -> Tuple[str, tuple]:
        """``TIMESTAMP WITH TIME ZONE`` — rendered ``TIMESTAMP``.

        Exactly this concept, under BigQuery's name: its ``TIMESTAMP`` is an
        absolute point in time independent of any time zone or daylight-saving
        rule, which is what ``WITH TIME ZONE`` means. The instant survives the
        round trip; the original offset does not, because BigQuery does not
        record one.

        A declared ``precision`` is refused on the same grounds as
        :meth:`format_data_type_timestamp` — one BigQuery type, one storage
        resolution, no parameter; see :meth:`_refuse_temporal_precision`.
        """
        self._refuse_temporal_precision(
            data_type, "TIMESTAMP WITH TIME ZONE", "TIMESTAMP")
        return "TIMESTAMP", ()

    # ------------------------------------------------------------------
    # Binary
    # ------------------------------------------------------------------

    def supports_data_type_blob(self) -> bool:
        return True

    def format_data_type_blob(self, data_type: BlobType) -> Tuple[str, tuple]:
        """``BLOB`` / ``BYTEA`` — rendered ``BYTES``.

        ``BYTES`` is BigQuery's byte-string type and has the same storage shape
        as ``BYTEA``: variable-length, unbounded by the type, up to 8 MB. Neither
        ``BLOB`` nor ``BYTEA`` is in BigQuery's DDL grammar, so both spellings
        are accepted and normalised.

        The fixed- and variable-length byte-string concepts do **not** render
        here at all — see :meth:`suggested_data_types` for why ``BYTES``'s
        declared length is a maximum rather than a width.
        """
        self._check_spelling(data_type, BlobType)
        return "BYTES", ()

    # ------------------------------------------------------------------
    # Semi-structured
    # ------------------------------------------------------------------

    def supports_data_type_json(self) -> bool:
        return True

    def format_data_type_json(self, data_type: JsonType) -> Tuple[str, tuple]:
        """``JSON`` — BigQuery's own JSON type.

        A real column type here rather than text holding JSON: BigQuery's
        ``JSON`` rejects a value that is not well-formed JSON at write time,
        which is a constraint the text type does not provide.
        """
        return "JSON", ()

    def supports_data_type_jsonb(self) -> bool:
        return True

    def format_data_type_jsonb(self, data_type: JsonBType) -> Tuple[str, tuple]:
        """``JSONB`` — rendered ``JSON``.

        The binary JSON representation PostgreSQL calls ``JSONB`` is not a
        distinct type in BigQuery: there is one ``JSON`` type and it is the
        binary one, so this is a rename rather than a substitution.

        ``JSONB`` stays a separate concept from ``JsonType`` for the same
        reason ``xml`` does: which backend writes both, and what its operations
        are, are facts about the backend rather than about the value.
        """
        return "JSON", ()

    # ------------------------------------------------------------------
    # Arrays
    # ------------------------------------------------------------------

    def supports_data_type_array(self) -> bool:
        return True

    def format_data_type_array(self, data_type: ArrayType) -> Tuple[str, tuple]:
        """``ARRAY<T>`` — BigQuery's own spelling for the array container.

        BigQuery's array is not a second type bolted onto the element type: an
        ``ARRAY<T>`` column stores each row's ``T`` values contiguously, which
        is why the element type is mandatory in the DDL and why the framework's
        ``ArrayType`` requires one too. Legacy DDL spells the same column
        ``REPEATED T``; ``ARRAY<T>`` is the current form and the one the
        documentation uses.

        Two shapes BigQuery genuinely has no type for are refused here rather
        than approximated:

        * **Nesting** — there is no array of arrays, so ``Array(Array(T))`` is
          refused. The check belongs in the formatter because whether nesting is
          legal is a fact about the backend, not about arrays.
        * **More than one dimension** — a BigQuery array is
          one-dimensional, so ``dimensions > 1`` is refused for the same
          reason. PostgreSQL's ``int[][]`` is a real two-dimensional type; there
          is no such thing here.
        """
        if isinstance(data_type.element_type, ArrayType):
            raise UnsupportedFeatureError(
                self.name,
                "ARRAY<ARRAY<T>>",
                suggestion=(
                    "BigQuery has no array of arrays; flatten the column to a "
                    "single ARRAY and nest the data in a STRUCT instead."
                ),
            )
        if data_type.dimensions != 1:
            raise UnsupportedFeatureError(
                self.name,
                f"an array with {data_type.dimensions} dimensions",
                suggestion="A BigQuery ARRAY is always one-dimensional.",
            )
        element_sql, element_params = self.format_data_type(data_type.element_type)
        return f"ARRAY<{element_sql}>", element_params

    # ------------------------------------------------------------------
    # Types with no core concept
    # ------------------------------------------------------------------

    def supports_data_type_custom(self) -> bool:
        return True

    def format_data_type_custom(self, data_type: CustomType) -> Tuple[str, tuple]:
        """The raw name, verbatim.

        This is what makes a BigQuery type the framework does not model
        reachable: ``GEOGRAPHY``, ``BIGNUMERIC`` and ``RANGE`` have no core
        concept, and a caller who wants one can write it as a ``CustomType``
        today instead of being told the type is unsupported.

        The name was validated by ``CustomType.__init__`` against the package's
        type-name grammar, which is what makes rendering it here safe without a
        second check: a type name lands in a position that cannot take a bound
        parameter, so the grammar is where an injected fragment has to stop,
        and every formatter shares that one gate.

        It is also why BigQuery's parameterised names cannot be spelled this
        way — ``ARRAY<INT64>`` is not a type name in that grammar, and
        :class:`~...expression.types.array.ArrayType` is the route for it.
        """
        return data_type.raw, ()

    # ------------------------------------------------------------------
    # Core types BigQuery stores some other way
    # ------------------------------------------------------------------

    def suggested_data_types(self) -> Dict[str, type]:
        """Core types BigQuery stores some other way.

        BigQuery's type list is closed, documented and short, so most core
        concepts map onto one BigQuery type by name and are rendered above.
        These are the ones it does not have at all, named here so that a caller
        who declares one learns what this backend stores instead of being told
        only that the type is unsupported.

        ``binary`` / ``varbinary``
            BigQuery has exactly one byte-string type, ``BYTES``:
            variable-length, up to 8 MB. It has no fixed-length byte string at
            all, and the length it can declare is a *maximum* rather than a
            width — a ``BYTES(16)`` column holds at most 16 bytes and is
            neither blank-padded nor required to fill them. So a
            fixed-width column's padding behaviour does not exist here, which is
            why the fixed-length concept cannot be rendered at all, and why a
            declared length is not carried into either suggestion: an upper
            bound on a variable-length column is a property of the column, not
            of the type it was declared with. Both resolve to the unbounded
            byte string BigQuery does have.

        ``enum``
            BigQuery has no enum type, so a model declaring one would be told
            the type is unsupported with no route forward. The value is stored
            as ``STRING`` and constrained outside the type, so that is what the
            meaning becomes here.

        ``interval``
            BigQuery has no duration type. ``INTERVAL`` appears in its grammar
            only as the operand of date arithmetic — ``DATE_ADD(d, INTERVAL n
            DAY)`` — where ``n`` is an ``INT64`` count of one unit, and the
            functions that produce or consume a duration read and return that
            count. The unit belongs to the function rather than to the value,
            so no column type holds "a span"; what BigQuery stores is the count.

        ``uuid``
            BigQuery has no UUID type. A UUID is a 36-character canonical string
            in a ``STRING`` column and nothing at the type level checks the
            format, so the suggestion names the character type the identifier
            is held in.

        ``xml``
            BigQuery has no XML type. An XML document is stored as ``STRING``,
            with no schema validation and no XPath support beyond functions that
            parse the text on demand — which is exactly what unbounded text
            describes, so this is an accurate account of the storage rather than
            a compromise. BigQuery's ``JSON`` *is* a real type and is rendered
            above, not suggested; XML stays a separate concept from it because
            the operations and the standard behind them differ.

        Types rendered above are deliberately absent: they already have a
        rendering path here, so there is nothing to suggest (suggested and
        supported keys are disjoint by contract).
        """
        return {
            "binary": BlobType,
            "varbinary": BlobType,
            "enum": VarCharType,
            "interval": IntegerType,
            "uuid": VarCharType,
            "xml": TextType,
        }

    #: ``ARRAY<T>`` with the element as a captured group, so the element can be
    #: handed back to :meth:`parse_type` itself. Decided before any word list
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

    def parse_type(self, raw: str) -> DataType:
        """Turn a BigQuery type string back into the ``DataType`` it names.

        Canonical, with the same shape of contract the other backends hold:

        **One concept in, one class out.** Every word below answers with the
        *one* class whose rendering is that storage. Where a declaration was
        widened on the way in — the four integer widths are all ``INT64``, the
        three float concepts are all ``FLOAT64`` — the parse answers with the
        storage's own concept, which is the one that was *not* widened:
        ``INT64`` is the 64-bit integer (``BigIntType``, the "eight bytes" the
        ``tinyint`` formatter names), ``FLOAT64`` is double precision
        (``DoubleType``), bare ``STRING`` is unbounded text (``TextType``),
        ``STRING(L)`` is the variable-length bounded string the ``varchar``
        formatter documents ``STRING(length)`` as being, and ``TIMESTAMP`` is
        the absolute instant BigQuery documents — the ``timestamptz`` concept,
        because a BigQuery ``TIMESTAMP`` is UTC-normalised rather than naive.
        A narrowed declaration reading back as its widened concept is the
        differ reporting a real widening, which is what happened on the
        server; it is not a parse error.

        **The vocabulary is doubled, and the second half is legacy.** The
        formatters above are one vocabulary; the legacy schema surfaces (the
        ``bq`` tool and the legacy-format column list) are a second one naming
        the same storages: ``INTEGER``/``FLOAT``/``BOOLEAN`` answer by
        storage, and ``RECORD`` — the legacy word for ``STRUCT`` — falls
        through to ``CustomType``, the framework having no concept for it.

        **A word the framework does not model is ``CustomType``, not a
        guess.** ``GEOGRAPHY``, ``INTERVAL`` and ``BIGNUMERIC`` are real
        BigQuery types with no core concept (the last is documented above the
        formatters as out of this dialect's scope), so they answer
        ``CustomType`` carrying the word, exactly as MySQL's parse answers
        words MySQL does not write. ``STRUCT<...>`` cannot even be carried —
        a struct's field list is not identifier-shaped, so the type-name
        validation refuses it — and the resulting ``InvalidTypeNameError``
        names the caller's string rather than misreporting the column as a
        bare ``STRUCT`` two different tables would compare equal.

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
            raise ValueError("parse_type needs a type string; an empty one names nothing")
        upper = stripped.upper()

        # ARRAY<T> first: the element is itself a type string, so the word
        # lists below must not see it. Nested arrays answer structurally —
        # whether the *server* can hold one is a declaration question the
        # formatter already refuses by name.
        array_match = self._PARSE_ARRAY_RE.match(stripped)
        if array_match is not None:
            return ArrayType(dialect=self, element_type=self.parse_type(array_match.group(1)))

        # STRING(L) is decided before STRING: a bounded string and an
        # unbounded one are two concepts, not one.
        string_match = self._PARSE_STRING_RE.match(stripped)
        if string_match is not None:
            length = string_match.group(1)
            if length is None:
                return TextType(dialect=self)
            return VarCharType(dialect=self, length=int(length))

        # NUMERIC and its parameters. A single parameter means scale 0 — the
        # "S is interpreted to be 0 if unspecified" the decimal formatter
        # quotes — so the answer says it rather than inventing a different
        # column. This form never comes from a rendering above; it comes from
        # a caller's DDL, and the answer renders back as NUMERIC(P, 0),
        # which is the same storage the server holds.
        numeric_match = self._PARSE_NUMERIC_RE.match(stripped)
        if numeric_match is not None:
            precision, scale = numeric_match.group(1), numeric_match.group(2)
            if precision is None:
                return DecimalType(dialect=self)
            if scale is None:
                return DecimalType(dialect=self, precision=int(precision), scale=0)
            return DecimalType(dialect=self, precision=int(precision), scale=int(scale))

        # Words with no parameters at all: the rendered vocabulary and the
        # legacy one, each answered by its storage. The spelling is carried
        # where the concept has more than one word, so BOOL and BOOLEAN stay
        # distinguishable in the rendering without ever being two classes.
        if upper in ("INT64", "INTEGER"):
            return BigIntType(dialect=self)
        if upper in ("FLOAT64", "FLOAT"):
            return DoubleType(dialect=self)
        if upper == "BOOL":
            return BooleanType(dialect=self, spelling="bool")
        if upper == "BOOLEAN":
            return BooleanType(dialect=self, spelling="boolean")
        if upper == "BYTES":
            return BlobType(dialect=self)
        if upper == "JSON":
            return JsonType(dialect=self)
        if upper == "DATE":
            return DateType(dialect=self)
        if upper == "TIME":
            return TimeType(dialect=self)
        if upper == "DATETIME":
            return DateTimeType(dialect=self)
        if upper == "TIMESTAMP":
            # A BigQuery TIMESTAMP is an absolute point in time,
            # UTC-normalised, exactly the instant the timestamptz concept
            # names. A naive TIMESTAMP declaration reads back as this, which
            # the differ reports as the widening the server performed.
            return TimestampTzType(dialect=self)

        # Everything else is a word the framework has no concept for, and the
        # honest answer carries the word rather than guessing: GEOGRAPHY,
        # INTERVAL, BIGNUMERIC, RECORD, an extension type. STRUCT<...> never
        # reaches CustomType, because its field list is not identifier-shaped
        # and the type-name validation refuses it by design.
        return CustomType(dialect=self, raw=stripped)


__all__ = ["BigQueryTypeSupportMixin"]
