# src/rhosocial/activerecord/backend/impl/bigquery/mixins/column_type.py
"""Which column class BigQuery suggests for each common Python type.

This is BigQuery's answer to the eighteen-entry closed list the
:class:`~rhosocial.activerecord.backend.dialect.protocols.ColumnTypeSupport`
protocol names: ``bool``, ``int``, ``float``, ``decimal.Decimal``, ``str``,
``bytes``, ``bytearray``, ``datetime.date``, ``datetime.time``,
``datetime.datetime``, ``datetime.timedelta``, ``uuid.UUID``, ``dict``,
``list``, ``tuple``, ``set``, ``frozenset``, ``enum.Enum``. Everything here is
a **column** decision -- what operations a value carries -- and none of it is a
storage decision: whether ``ARRAY<T>`` or ``JSON`` spells the column is the DDL
layer's separate answer (see :class:`~...mixins.types.BigQueryTypeSupportMixin`),
and this table never reads it.

Evidence level: 文档（待云验）
----------------------------
**Every cell below is documentation-only.** No BigQuery instance was reachable
while this was written -- the emulator at ``localhost:9050`` is not running and
no cloud credentials exist -- so nothing here was measured. Each answer cites
the official page it rests on, and each claim that documentation *cannot* settle
is named as such rather than asserted. A ``待云验`` marker in a docstring means
"a scenario server run must confirm this before a caller relies on it"; the
contract tests assert the *declaration*, never the server's agreement with it.

Pages cited (all fetched 2026-10-09):

* ``operators`` -- https://cloud.google.com/bigquery/docs/reference/standard-sql/operators
* ``data-types`` -- https://cloud.google.com/bigquery/docs/reference/standard-sql/data-types
* ``ddl`` -- https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language
* ``query-syntax`` -- https://cloud.google.com/bigquery/docs/reference/standard-sql/query-syntax
* ``string_functions`` / ``array_functions`` / ``json_functions`` -- the
  corresponding pages under ``.../reference/standard-sql/``

What is *not* answered ``None``, and why that is not a hole
-----------------------------------------------------------
No entry here answers ``None``, and that is a finding rather than an omission.
``None`` is the protocol's last resort -- "this backend genuinely has no column
class for this value family" -- and the two ends that must refuse are Firebird
(``dict`` and ``list`` -- no JSON functions, no arrays at all) and MySQL < 5.7 /
MariaDB < 10.2 (``dict`` -- no JSON functions). BigQuery has a native
``ARRAY<T>`` and a documented ``JSON`` type, so it has nothing to refuse. A
``None`` here would state a limit this backend does not have, which is as wrong
as a missing key.

Three things are deliberately recorded as **not decided here**, because
answering them would be a ruling nobody has made:

* **``dict``: ``STRUCT`` versus ``JSON`` (议题 A).** Whether a structured value
  belongs to a ``STRUCT`` column class -- and whether that class belongs in core
  at all, the same question ClickHouse's ``Tuple`` / ``Map`` raise -- is
  undecided. BigQuery makes it harder rather than easier: ``STRUCT<T>`` and
  ``JSON`` are two documented types, neither marked Preview on the data-types
  page, with overlapping purpose, and their operation surfaces differ (a
  ``STRUCT`` is projected with ``expression.fieldname`` and has no path syntax;
  a ``JSON`` value is read with ``JSON_QUERY`` / ``JSON_VALUE`` and indexed by
  path). The cell answers
  :class:`~...column_types.JSONColumn` because BigQuery's ``JSON`` type is the
  one whose operations :class:`~...column_types.JSONColumn` already describes
  (``json_path``, ``json_value``, key existence, array length, validity) --
  **but the answer is provisional and will move if 议题 A rules otherwise.** The
  alternative is named in the cell comment so a reader is not left to guess it:
  a ``STRUCTColumn`` does not exist in core, and inventing one is the core-level
  decision 议题 A exists to make.
* **``tuple`` as a carrier for a heterogeneous value.** ``ARRAY<T>`` declares
  one element type, so a heterogeneous Python tuple has no native carrier on
  this backend other than ``STRUCT`` -- which is 议题 A again. ``tuple``
  answers :class:`~...column_types.ArrayColumn` because that is the protocol's
  agreed BigQuery row and because the permissive fallback it used to reach no
  longer exists, not because ``ARRAY<T>`` can hold mixed types. A one-dimensional
  ``ARRAY`` also cannot nest directly ("an array can't directly contain another
  array"), which this backend's array formatter refuses explicitly.
* **``RANGE<DATE|DATETIME|TIMESTAMP>`` (fix item #8).** Documented as
  ``RANGE<DATE>`` / ``RANGE<DATETIME>`` / ``RANGE<TIMESTAMP>`` on the data-types
  page, but this backend's ``parse_type`` cannot carry the parameterised form
  and raises ``InvalidTypeNameError`` (bare ``RANGE`` works, as a word-carrying
  ``CustomType``). That gap is the DataType layer's and stays open here; it is
  named so a reader does not read this table as covering it.

Two rendering facts recorded here and **not** acted on, because rendering is
Phase 2b's:

* ``LENGTH`` is one name for two things on this backend -- characters on
  ``STRING`` (``CHAR_LENGTH`` is the explicit spelling) and bytes on ``BYTES``
  (``BYTE_LENGTH``) -- so a length operation must say which it means.
* ``NUMERIC`` and ``FLOAT64`` do not implicitly mix in arithmetic; the docs
  require an explicit cast. That is a rendering obligation on the numeric
  formatters, not a missing capability, so no operation is narrowed for it.
"""

import datetime
import decimal
import enum
import uuid
from typing import Any, Dict, Type

from rhosocial.activerecord.backend.dialect.mixins import ColumnTypeMixin
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

#: The full table: ``{common Python type: ColumnBase subclass}``.
#:
#: Every entry of the protocol's closed list is answered, and no entry is
#: ``None``: BigQuery has a documented type for each value family, so the last
#: resort never applies (see the module docstring).
#:
#: Deviations worth naming: the three numeric entries. ``float`` and ``Decimal``
#: both answer :class:`~...column_types.NumericColumn`, the one numeric class
#: core declares -- "one class for every numeric width and precision", because
#: the operations are the same whatever the value was declared as. BigQuery's
#: documented storage still makes the split legible -- ``FLOAT64`` is an
#: approximate double, ``NUMERIC`` / ``BIGNUMERIC`` are exact fixed-point with a
#: declared precision and scale, and the two do not implicitly mix in
#: arithmetic (待云验: the non-mixing is documented, not measured) -- but that
#: difference is the DDL layer's ``DataType`` and a rendering obligation on the
#: numeric formatters, not a different column surface. Everything else below
#: restates the baseline, and the group comments say what the documentation
#: behind it was.
BIGQUERY_COLUMN_TYPES: Dict[Any, Type[ColumnBase]] = {
    # --- numbers core keeps together -----------------------------------
    # Documented as three distinct families: `INT64` is a 64-bit integer,
    # `NUMERIC` has 38 digits of precision (scale declared, defaulted to 0
    # when unspecified) and `BIGNUMERIC` approximately 76.8, and `FLOAT64`
    # is an approximate double precision value. The widths are the DDL
    # layer's business; what the column class says is the operation set,
    # and that is what differs between the integer, the two exact decimals
    # and the approximate float. 文档（待云验）.
    int: IntegerColumn,
    float: NumericColumn,
    decimal.Decimal: NumericColumn,
    # --- booleans ------------------------------------------------------
    # `BOOL`, with `BOOLEAN` documented as an SQL alias of the same type
    # (data-types: "SQL type name: BOOL / SQL aliases: BOOLEAN"). The
    # column class is unaffected by the alias: the boolean-domain surface
    # (`is_true` / `is_false` / `&` / `|` / `~`) is
    # `BooleanColumn`'s, and `IS [NOT] TRUE` / `IS [NOT] FALSE` are in the
    # documented operator list. 文档（待云验）.
    bool: BooleanColumn,
    # --- text and bytes ------------------------------------------------
    # One text type (`STRING`, parameterised as `STRING(L)` for a maximum
    # length -- an upper bound, not a width) and one byte type (`BYTES`,
    # parameterised the same way; `BYTES(L)` is currently carried as a
    # word-carrying `CustomType`, a DataType-layer note rather than a column
    # one). Both document the same comparison surface, so `StringColumn`
    # and `BinaryColumn` are the answers. Note `LENGTH` is characters on
    # `STRING` and bytes on `BYTES`: a Phase 2b rendering obligation, not a
    # narrowing. 文档（待云验）.
    str: StringColumn,
    bytes: BinaryColumn,
    bytearray: BinaryColumn,
    # --- date / time ---------------------------------------------------
    # `DateTimeColumn` for all three temporal entries, the shared baseline.
    # Worth pinning because it is a known gap rather than an answer: core
    # has no `DateColumn` / `TimeColumn` yet, while BigQuery has had native
    # `DATE` and `TIME` for years (this repository's investigation appendix
    # D-①). The tz distinction is a *storage* fact -- `TIMESTAMP` is an
    # absolute point in time, `DATETIME` a wall clock with no zone -- and
    # both entries answer the same column class, which is correct because
    # the column class says what the value can do, not how it is written.
    # 文档（待云验）.
    datetime.date: DateTimeColumn,
    datetime.time: DateTimeColumn,
    datetime.datetime: DateTimeColumn,
    # A timedelta is a number of seconds here, answered by the numeric
    # surface, and the reason is documented rather than convenient: BigQuery
    # expresses a duration as the *operand of a function*
    # (`DATE_ADD(date, INTERVAL n DAY)`), where the unit belongs to the
    # function and the value is an `INT64` count. The standalone `INTERVAL`
    # type exists and is documented ("A duration of time, without referring
    # to any specific point in time. SQL type name: INTERVAL"), but it is
    # marked **Preview** on the same page, and core has no `IntervalColumn`
    # to aim at either way -- so the numeric answer is what there is, and
    # the `Interval*` question rides with core's missing class. 文档（待云验）.
    datetime.timedelta: NumericColumn,
    # BigQuery has no UUID type: the documented type list (the `SQL type
    # name:` rows) has none, and `GENERATE_UUID()` produces a value in a
    # `STRING` column. The column class is still `UUIDColumn`, because that
    # class carries no UUID-specific operator -- portable SQL has none, so a
    # UUID column supports exactly what any other value column does -- and
    # the `STRING` storage is the DataType layer's answer (this backend
    # suggests `uuid` -> `STRING` there). Storage is not what this cell
    # decides. 文档（待云验）.
    uuid.UUID: UUIDColumn,
    # --- documents ------------------------------------------------------
    # **Provisional, and deliberately visible about it.** `JSON` is a
    # documented, non-Preview type ("Represents JSON, a lightweight
    # data-interchange format. SQL type name: JSON") and its operations are
    # what `JSONColumn` already describes: `JSON_QUERY` / `JSON_VALUE` for
    # document and scalar access (which this backend already renders, see
    # `BigQueryCapabilityMixin.format_json_function_expression`),
    # `JSON_EXTRACT_SCALAR`, `JSON_QUERY_ARRAY_LENGTH`, `JSON_KEYS`,
    # `TO_JSON_STRING`, `PARSE_JSON` / `JSON_EXTRACT_SCALAR_ARRAY`.
    #
    # **The alternative, and why the cell may move:** `STRUCT<T>` is also a
    # documented, non-Preview type ("Container of ordered fields each with
    # a type (required) and field name (optional)") and is what a Python
    # dict most literally resembles -- named fields, typed. Whether a
    # structured value belongs to a `STRUCT` column class is **议题 A**, and
    # it is open: core has no `StructColumn`, and ClickHouse's `Tuple` /
    # `Map` raise the same question. BigQuery sharpens it rather than
    # settling it, because the two candidates are *not* interchangeable:
    # a `STRUCT` is projected with `expression.fieldname` (the documented
    # field-access operator) and its subscript form takes a positional
    # index, with no path syntax at all, while a `JSON` value is read by
    # path and indexed by `JSON_QUERY`. Choosing `STRUCT` here would mean
    # choosing an operation surface over a type name, and inventing the
    # class is the core-level decision 议题 A exists to make.
    #
    # So the cell answers `JSONColumn` -- the class whose operation set
    # BigQuery's `JSON` functions actually implement -- and says here that
    # it is provisional rather than letting a reader assume the question
    # was settled. 待云验 as well as 议题 A: the `JSON`-type-availability
    # version gate is not declared anywhere in this backend (unlike
    # ClickHouse's 26.0), and nothing below narrows on one, because a
    # `dict` field annotated today would have to answer on servers both
    # above and below it. 文档（待云验）.
    dict: JSONColumn,
    # --- arrays ----------------------------------------------------------
    # `ARRAY<T>`, declared with angle brackets ("Declaring an array type
    # ARRAY<T> ... ARRAY<INT64>") and stored in **REPEATED** mode: the DDL
    # reference is explicit that "ARRAY columns have REPEATED mode and can be
    # empty but cannot be NULL". The operations are documented too --
    # `ARRAY_LENGTH`, the `UNNEST` operator (with `WITH OFFSET`, and
    # `JOIN UNNEST`), `ARRAY_REVERSE` / `ARRAY_SLICE` /
    # `ARRAY_TO_STRING`, and the quantified `LIKE ... ANY UNNEST(...)` form
    # -- so `ArrayColumn`'s `array_length` / `unnest` are native here rather
    # than emulated through a document. This is the one backend cell where
    # `ARRAY<T>` is the agreed answer and no capability is taken away from
    # it. 文档（待云验）.
    list: ArrayColumn,
    # A tuple is heterogeneous and `ARRAY<T>` declares one element type, so
    # a mixed tuple has no native carrier here other than `STRUCT` -- which
    # is 议题 A again. This cell answers the protocol's agreed BigQuery row,
    # not a ruling that `ARRAY<T>` holds mixed types; see the module
    # docstring. 议题 A, 待云验.
    tuple: ArrayColumn,
    # A set is an `ARRAY` with the duplicates already removed by Python; the
    # server does not re-deduplicate, so "set-ness" is a value-layer
    # property and the storage family is `ARRAY<T>`.
    set: ArrayColumn,
    frozenset: ArrayColumn,
    # BigQuery has no `ENUM` type -- the documented `SQL type name:` rows do
    # not include one -- so the value is stored as `STRING` and constrained
    # outside the type, which is what this backend's `suggested_data_types`
    # already says for `enum`. The column class is unaffected: comparison,
    # `IN` and `ORDER BY` are the text surface, which is `StringColumn`'s.
    #
    # **One guarantee this backend cannot give, recorded rather than
    # narrowed.** On backends with a native enum type, or with `TEXT` +
    # `CHECK`, an illegal member is refused by the server. BigQuery has
    # **no CHECK constraint**: the `CREATE TABLE` grammar's
    # `constraint_definition` admits only `primary_key` and `foreign_key`,
    # and both are documented as unenforced ("BigQuery only supports
    # unenforced primary keys"). So a value outside the Python enum is
    # stored, not refused. That is a fact about *what the schema enforces*,
    # not about which operations the value column carries, so no operation
    # is narrowed for it -- there is no `StringColumn` operation that stops
    # working because of it. It is written down because the enum guarantee
    # in the protocol's `§7` list assumes a rejection mechanism this backend
    # does not have. 文档（待云验）.
    enum.Enum: StringColumn,
}


class BigQueryColumnTypeMixin(ColumnTypeMixin):
    """BigQuery's answer to the column-type protocol.

    Composed into ``BigQueryDialect`` as the whole table: the rebuilt core
    declares no generic common-type table to sit behind it, so
    :meth:`suggested_column_types` here is the answer the model layer reads for
    every one of the eighteen common types, and
    :meth:`~rhosocial.activerecord.backend.dialect.mixins.column_type.ColumnTypeMixin.suggested_extra_column_types`
    stays empty because this backend models no Python type of its own.

    Evidence level for the whole table is 文档（待云验） -- see the module
    docstring. Nothing here was measured against a server.
    """

    def suggested_column_types(self) -> Dict[Any, Type[ColumnBase]]:
        """A fresh copy of :data:`BIGQUERY_COLUMN_TYPES`, one class per entry.

        All eighteen entries of the protocol's closed list are answered, and
        none is ``None``: BigQuery has a documented type for every value
        family, so the protocol's last resort never applies here.
        """
        return dict(BIGQUERY_COLUMN_TYPES)


__all__ = ["BIGQUERY_COLUMN_TYPES", "BigQueryColumnTypeMixin"]
