# src/rhosocial/activerecord/backend/impl/bigquery/mixins/data_type_suggestions.py
"""BigQuery's **suggested data types**: what a bare field is declared as here.

The DDL half of the type answer; :mod:`.column_type` is the operation half --
that table says which operations a value carries, this one says what a column
*is* when a field writes only a Python type and no ``UseSqlType``.

BigQuery's type list is closed, documented and short, and that shapes every
answer below:

* **the scalar names are BigQuery's own.** ``BOOL``, ``INT64``, ``FLOAT64``,
  ``NUMERIC``, ``STRING`` and ``BYTES`` are what this server stores; the
  generic ``DataType`` classes render onto them, so nothing here needs a
  BigQuery-specific subclass (this backend deliberately owns none).
* **the only container is ``ARRAY<T>``.** A BigQuery array is always
  one-dimensional and cannot directly hold another array, and the element type
  is mandatory in the DDL -- ``ARRAY<T>`` is not a type without a ``T``. A
  bare annotation names no element, so the sequence entries declare
  ``ARRAY<STRING>``: the text element is the neutral carrier the adapters
  already write for mixed values, and the field that wants
  ``ARRAY<INT64>`` or another element says so with ``UseSqlType``. A ``dict``
  is not an array; it takes ``JSON``, the documented type whose operations
  (:class:`~...column_types.JSONColumn`) BigQuery's ``JSON_QUERY`` /
  ``JSON_VALUE`` implement. ``STRUCT<T>`` is the other documented container
  and is *not* chosen here: it is 议题 A in :mod:`.column_type`, and core has
  no ``StructColumn`` to pair it with.
* **``TIMESTAMP`` stores microseconds and takes no precision parameter.**
  "Up to six fractional digits (microsecond precision)" is a property of the
  stored value, not a knob the column type exposes -- the backend's temporal
  formatter refuses a declared precision rather than ignoring it. So
  ``datetime.datetime`` declares bare ``TIMESTAMP``; writing
  ``TimestampType(precision=3)`` here would produce a suggestion this dialect
  cannot render.
* **``AwareDatetime`` is an instant, and BigQuery's ``TIMESTAMP`` already is
  one.** A bare ``datetime`` is a wall-clock reading and declares the same
  ``TIMESTAMP`` only for want of a zone-less concept; ``AwareDatetime`` means
  it. The type is UTC-normalised, so it answers ``TimestampTzType`` -- which
  renders to the very same ``TIMESTAMP`` through this dialect's
  ``format_data_type_timestamptz``. No separate storage is needed for the
  aware concept.
* **there is no duration type.** ``INTERVAL`` appears in BigQuery's grammar as
  the operand of date arithmetic (``DATE_ADD(d, INTERVAL n DAY)``), where the
  unit belongs to the function and the value is an ``INT64`` count; no column
  holds "a span". ``datetime.timedelta`` therefore names the text carrier its
  neutral adapter writes.
* **there is no UUID type.** ``GENERATE_UUID()`` yields a value in a ``STRING``
  column, and the canonical form is 36 characters, so ``uuid.UUID`` is
  ``STRING(36)`` -- a declared length on BigQuery is a maximum, which the
  canonical form always meets.
* **there is no enum type.** The value lives in ``STRING(255)`` and is
  constrained outside the type; BigQuery has no ``CHECK`` constraint, so an
  illegal member is stored rather than refused. The width is the shared
  default the other backends also use.

The complex families carry a parameter a bare annotation does not say, so they
name text carriers and a field that wants the server's native type declares it
with ``UseSqlType``:

* ``Geometry`` -- ``GEOGRAPHY`` is a documented native type, but the framework
  has no ``DataType`` class that means "geography" and this backend owns no
  ``DataType`` subclass on purpose (see
  :class:`~...mixins.types.BigQueryTypeSupportMixin`). The neutral geometry
  adapter writes plain 2D WKT, so ``STRING`` is the declaration that
  round-trips; ``CustomType("GEOGRAPHY")`` is the route to native storage.
* ``Vector`` -- no dimension is declared by an annotation; the adapter's JSON
  text (``[1.0,2.0]``) round-trips through ``STRING``.
* ``BitString`` -- ``BIT(n)`` would need a width the annotation does not carry;
  the adapter writes the digits as text.
* ``Range`` / ``Multirange`` -- the element type decides the spelling
  (``RANGE<DATE|DATETIME|TIMESTAMP>`` on BigQuery), and that is the column's
  decision; the neutral range literal is text.
* ``MacAddress`` -- the canonical 17-character form (six two-hex-digit pairs
  and five separators) is ``STRING(17)``.
* ``IPAddress`` -- no native IP type; the canonical text form fits in at most
  45 characters (a compressed IPv6 address), so it is ``STRING(45)``.

No key answers ``None``: a suggestion is what a bare field gets, and taking the
table away from the caller is not an answer.

Each call returns a **fresh dict** whose values are this module's read-only
templates; the derivation binds a dialect on a copy of the single entry it uses.

Evidence level: 文档（待云验） -- no BigQuery instance was reachable, so every
answer rests on the documented type list rather than on a measured schema.
"""
from __future__ import annotations

import datetime
import decimal
import enum
import uuid
from typing import Any, Dict, Optional

from rhosocial.activerecord.backend.suggestion.definitions import (
    DataTypeSuggestion,
    ExtraDataTypeSuggestion,
)

from rhosocial.activerecord.backend.adapters import (
    AwareDatetime,
    BitString,
    Geometry,
    IPAddress,
    MacAddress,
    Multirange,
    Range,
    Vector,
)
from rhosocial.activerecord.backend.expression.types import (
    ArrayType,
    BlobType,
    BooleanType,
    DateType,
    DecimalType,
    DoubleType,
    IntegerType,
    JsonType,
    TextType,
    TimeType,
    TimestampType,
    TimestampTzType,
    VarCharType,
)

#: BigQuery's suggested declaration per framework-committed Python type.
BIGQUERY_DATA_TYPE_SUGGESTIONS: Dict[Any, Optional[Any]] = {
    bool: BooleanType(),
    int: IntegerType(),
    float: DoubleType(),
    decimal.Decimal: DecimalType(),
    str: TextType(),
    bytes: BlobType(),
    bytearray: BlobType(),
    datetime.date: DateType(),
    datetime.time: TimeType(),
    # An instant: BigQuery's TIMESTAMP is UTC-normalised, so the tz-aware
    # concept renders to the same storage as the bare datetime below.
    AwareDatetime: TimestampTzType(),
    # No precision: TIMESTAMP stores microseconds here and the formatter
    # refuses a parameter rather than silently dropping it.
    datetime.datetime: TimestampType(),
    # No duration type; the adapter's text form is the carrier.
    datetime.timedelta: TextType(),
    # No UUID type: the canonical form is 36 characters in a STRING column.
    uuid.UUID: VarCharType(length=36),
    dict: JsonType(),
    # ARRAY<T> needs an element type, and an annotation names none; STRING is
    # the neutral carrier, one-dimensional as BigQuery requires.
    list: ArrayType(element_type=TextType()),
    tuple: ArrayType(element_type=TextType()),
    set: ArrayType(element_type=TextType()),
    frozenset: ArrayType(element_type=TextType()),
    # No ENUM type; the shared 255-wide text spelling, constrained outside the
    # type (and BigQuery has no CHECK to do the constraining).
    enum.Enum: VarCharType(length=255),
    # -- Complex families ------------------------------------------------
    # No core DataType means geography; the WKT text carrier round-trips.
    Geometry: TextType(),
    # A dimension is column policy; the adapter's JSON text round-trips.
    Vector: TextType(),
    # BIT(n) needs a width the annotation does not carry; digits as text.
    BitString: TextType(),
    # The element type is column policy, and the range literal is text.
    Range: TextType(),
    Multirange: TextType(),
    # Six hex pairs plus five separators: the canonical MAC form.
    MacAddress: VarCharType(length=17),
    # No native IP type; canonical text fits in at most 45 characters.
    IPAddress: VarCharType(length=45),
}


class BigQueryDataTypeSuggestionsMixin:
    """BigQuery's answer to "what declaration does a bare field get here".

    Plain class, not a ``DataTypeMixin`` subclass: it supplies one table and
    holds no refusal or dispatch logic of its own. Composed into
    ``BigQueryDialect`` ahead of the mixins that provide the type-family
    defaults, because a suggestion placed after the class it overrides never
    wins the lookup.
    """

    def suggest_data_types(self) -> DataTypeSuggestion:
        """A fresh copy of :data:`BIGQUERY_DATA_TYPE_SUGGESTIONS`.

        All framework-committed Python types are answered, none is ``None``,
        and every value is a ``DataType`` this dialect renders.
        """
        return DataTypeSuggestion(table=dict(BIGQUERY_DATA_TYPE_SUGGESTIONS))

    def suggest_extra_data_types(self) -> ExtraDataTypeSuggestion:
        """No backend-owned extra data types."""
        return ExtraDataTypeSuggestion(table={})


__all__ = ["BIGQUERY_DATA_TYPE_SUGGESTIONS", "BigQueryDataTypeSuggestionsMixin"]
