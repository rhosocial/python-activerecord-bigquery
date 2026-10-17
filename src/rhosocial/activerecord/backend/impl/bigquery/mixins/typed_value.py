# src/rhosocial/activerecord/backend/impl/bigquery/mixins/typed_value.py
"""BigQuery's spellings for the typed value nodes (``expression.values``).

Evidence level: 文档（not server-verified）
-------------------------------------------
**No spelling below was measured.** No BigQuery instance is reachable from
this repository's test environment and the CI emulator does not adjudicate
literal grammar, so every form is transcribed from the official reference
pages, read 2026-10-17:

* lexical structure and syntax -- bytes literals (``b``/``B`` prefix), the
  escape-sequence table (``\\xhh``: exactly 2 hex digits, one byte), ``DATE``/
  ``TIME``/``DATETIME``/``TIMESTAMP`` literals (keyword + quoted canonical
  format), ``NUMERIC``/``BIGNUMERIC`` literals (keyword + quoted value) and
  interval literals (``INTERVAL step_size step_unit``, unquoted):
  https://cloud.google.com/bigquery/docs/reference/standard-sql/lexical
* data types -- NUMERIC (precision 38, scale 9), BIGNUMERIC (approximately
  76.8 digits, scale 38), TIME ("a time of day, independent of a specific
  date and time zone"), the interval-supported datetime parts:
  https://cloud.google.com/bigquery/docs/reference/standard-sql/data-types

What is overridden, and why
---------------------------
The kinds BigQuery agrees with the base on -- NULL, booleans (``TRUE`` /
``FALSE``), ``INT64``/``FLOAT64`` numeric text, and strings -- keep the
base's rendering (strings inline correctly because the dialect overrides
``_escape_sql_string`` for GoogleSQL's backslash escaping; see
:mod:`...impl.bigquery.dialect`). Everything else this grammar spells its
own way:

* **binary** -- ``b'\\x01\\x02'``: the bytes-literal prefix with every byte
  as a ``\\xhh`` hex escape, the one form that is valid whatever the bytes
  contain.
* **UUID** -- the bare quoted text: BigQuery has no UUID type, and
  ``GENERATE_UUID()`` returns a ``STRING``, so the canonical form is the
  whole of what a ``STRING`` column holds.
* **INTERVAL** -- the unquoted numeric form ``INTERVAL 5 DAY``, mapped over
  the ``timedelta``'s days / seconds / microseconds.
* **Decimal** -- ``NUMERIC '...'`` / ``BIGNUMERIC '...'``: the keyword form
  is the only exact-decimal literal; bare ``3.14`` would be a ``FLOAT64``
  literal and the precision the value exists to carry would be lost.
* **date / time / datetime / timestamp** -- the keyword-prefixed typed
  literals (``DATE '...'``, ``TIME '...'``): BigQuery's canonical literals
  carry the type keyword, and a bare quoted string is a ``STRING`` that
  only *coerces* where the position happens to expect the type. For a
  ``datetime`` the naive/aware distinction picks the type: naive is
  zoneless ``DATETIME``, aware is ``TIMESTAMP`` with the offset spelled.
"""

import decimal
from typing import TYPE_CHECKING, Tuple

if TYPE_CHECKING:  # pragma: no cover
    from rhosocial.activerecord.backend.expression.values import TypedValue

#: BIGNUMERIC's documented range, transcribed from the data-types reference
#: (not server-verified, read 2026-10-17). The integer part at the bound is
#: 39 digits -- the partial "77th digit" of the ~76.8-digit precision -- so
#: the magnitude is compared against the bounds themselves, not against a
#: digit count. The two bounds differ by one unit because the type is a
#: scaled fixed point: the negative side holds one step more than the
#: positive one, exactly as the documented Min/Max lines spell them.
_BIGNUMERIC_MIN = decimal.Decimal(
    "-5.7896044618658097711785492504343953926634992332820282019728792003956564819968E+38"
)
_BIGNUMERIC_MAX = decimal.Decimal(
    "5.7896044618658097711785492504343953926634992332820282019728792003956564819967E+38"
)


class BigQueryTypedValueMixin:
    """BigQuery's tier-2 value literals and its typed tier-1 spellings.

    Stands alone rather than inheriting the core :class:`TypedValueMixin`,
    matching SQLite's mixin: the dialect composes this class ahead of the
    core one, and the overridden methods win by that position. The kinds
    not written here are the ones BigQuery spells the base's way.
    """

    def format_binary_value(self, expr: "TypedValue") -> Tuple[str, tuple]:
        """A bytes literal: ``b'\\x01\\x02'``, every byte as a hex escape.

        The ``b`` prefix is the documented bytes-literal form, and
        ``\\xhh`` -- exactly 2 hex digits, decoding to one byte -- is the
        documented escape that is valid for any byte value, so every byte
        is spelled that way rather than only the unprintable ones.
        """
        if not type(expr).inline_params:
            return self._bind_value(expr)
        return "b'" + "".join(f"\\x{b:02x}" for b in bytes(expr.value)) + "'", ()

    def format_uuid_value(self, expr: "TypedValue") -> Tuple[str, tuple]:
        """A UUID as quoted text -- BigQuery's UUIDs live in ``STRING``.

        There is no UUID type and ``GENERATE_UUID()`` returns ``STRING``,
        so the canonical text is the whole value.
        """
        if not type(expr).inline_params:
            return self._bind_value(expr)
        return self.format_literal(str(expr.value)), ()

    def format_interval_value(self, expr: "TypedValue") -> Tuple[str, tuple]:
        """An interval literal: the unquoted ``INTERVAL n UNIT`` form.

        GoogleSQL's single-datetime-part literal is ``INTERVAL step_size
        step_unit`` with an ``INT64`` step, unquoted (the quoted
        ``'datetime_parts_string'`` range form is the other literal and is
        not derived here). The step is mapped over the ``timedelta``'s own
        days / seconds / microseconds as one exact integer count of
        microseconds, then spelled in the largest unit that divides it --
        ``INTERVAL 1 DAY``, ``INTERVAL 90 MINUTE``, ``INTERVAL 25 HOUR``,
        ``INTERVAL 86402 SECOND`` for a day-plus-two-seconds span -- and in
        ``MICROSECOND`` when no larger unit divides it exactly, an odd
        microsecond count for instance. ``YEAR`` / ``QUARTER`` / ``MONTH``
        are calendar units a ``timedelta`` cannot state (the core node's
        docstring says so), and ``WEEK`` is seven ``DAY``s exactly, so the
        mapping keeps to the units that carry the value's own magnitude.

        Raises:
            ValueError: The step in the chosen unit does not fit a signed
                ``INT64``. The exact minimum is refused along with anything
                beyond it, because whether a parser negates before or after
                the range check is not documented; every step whose literal
                parses unambiguously is spelled.
        """
        if not type(expr).inline_params:
            return self._bind_value(expr)
        value = expr.value
        total_micros = (value.days * 86_400 + value.seconds) * 1_000_000 + value.microseconds
        # The largest unit that divides the span exactly; MICROSECOND, the
        # one unit no remainder can escape, is the default.
        unit, step = "MICROSECOND", total_micros
        for candidate, micros_per in (
            ("DAY", 86_400_000_000),
            ("HOUR", 3_600_000_000),
            ("MINUTE", 60_000_000),
            ("SECOND", 1_000_000),
            ("MILLISECOND", 1_000),
        ):
            if total_micros % micros_per == 0:
                unit, step = candidate, total_micros // micros_per
                break
        if not -(2**63) < step <= 2**63 - 1:
            raise ValueError(
                f"INTERVAL {step} {unit} does not fit a signed INT64 step "
                "size; the interval literal grammar takes an INT64, so this "
                "span cannot be spelled as one part"
            )
        return f"INTERVAL {step} {unit}", ()

    def format_decimal_value(self, expr: "TypedValue") -> Tuple[str, tuple]:
        """An exact-decimal literal: ``NUMERIC '...'`` or ``BIGNUMERIC '...'``.

        The keyword followed by a quoted value is the documented literal,
        and the only exact one -- bare numeric text is a ``FLOAT64``
        literal, which is the approximation the value exists to avoid.
        The keyword is chosen by which type's documented range holds the
        value (data types, read 2026-10-17, not server-verified):

        * ``NUMERIC`` -- precision 38, scale 9, documented range
          ``+/-9.9999999999999999999999999999999999999E+28``. That bound
          is exactly 29 integer digits with scale 9, which is the form
          checked here.
        * ``BIGNUMERIC`` -- scale 38, documented range
          ``-5.789604...9968E+38`` to ``5.789604...9967E+38``. The
          integer part at the bound is 39 digits -- the partial digit of
          the "approximately 76.8 digits" precision -- so the magnitude
          is compared against the documented bounds themselves
          (:data:`_BIGNUMERIC_MIN` / :data:`_BIGNUMERIC_MAX`), which are
          one unit apart: the negative side holds one step more than the
          positive one.

        A value beyond both is refused here rather than written into SQL
        the server must reject.

        Raises:
            ValueError: The value is non-finite, its scale is past
                ``BIGNUMERIC``'s 38, or its magnitude is outside both
                types' documented range.
        """
        if not type(expr).inline_params:
            return self._bind_value(expr)
        value = expr.value
        if not value.is_finite():
            raise ValueError(
                "non-finite Decimal cannot be inlined into SQL (the base "
                "refuses it for every dialect; BigQuery spells it no way "
                "either)"
            )
        _, digits, exponent = value.as_tuple()
        scale = -exponent if exponent < 0 else 0
        integer_digits = (
            len(digits) + exponent if exponent >= 0 else max(len(digits) - scale, 0)
        )
        if scale <= 9 and integer_digits <= 29:
            keyword = "NUMERIC"
        elif scale <= 38 and _BIGNUMERIC_MIN <= value <= _BIGNUMERIC_MAX:
            keyword = "BIGNUMERIC"
        else:
            raise ValueError(
                f"{value} is outside the documented range of both decimal "
                f"types: scale {scale} is past BIGNUMERIC's 38, or the "
                "magnitude is past NUMERIC's 29 integer digits at scale 9 "
                "and past BIGNUMERIC's documented bounds; no decimal "
                "literal can hold it"
            )
        text = str(value)
        if "E" in text:
            # The exponent marker is spelling, not value: the documented
            # literal examples write it in lower case.
            text = text.replace("E", "e")
        return f"{keyword} {self.format_literal(text)}", ()

    def format_date_value(self, expr: "TypedValue") -> Tuple[str, tuple]:
        """A date literal: ``DATE '2014-09-27'``, keyword and quoted text.

        The date literal is the ``DATE`` keyword followed by a string
        literal in the canonical date format -- the quoted ISO text the
        base renders, prefixed with the keyword this grammar requires.
        """
        if not type(expr).inline_params:
            return self._bind_value(expr)
        return f"DATE {self.format_literal(expr.value)}", ()

    def format_time_value(self, expr: "TypedValue") -> Tuple[str, tuple]:
        """A time literal: ``TIME '12:30:00.45'``, keyword and quoted text.

        The ``TIME`` keyword precedes the canonical time format, which is
        a time of day and nothing else: the type is documented as
        "independent of a specific date and time zone".

        Raises:
            ValueError: An aware ``time`` carries an offset that the
                spelling would have to drop silently, which this dialect
                does not do -- the offset is the caller's to remove.
        """
        if not type(expr).inline_params:
            return self._bind_value(expr)
        if expr.value.tzinfo is not None:
            raise ValueError(
                f"{expr.value.isoformat()} is an aware time, but BigQuery's "
                "TIME is a time of day independent of a specific date and "
                "time zone; spelling it would have to drop the offset "
                "silently, which the dialect does not do"
            )
        return f"TIME {self.format_literal(expr.value)}", ()

    def format_timestamp_value(self, expr: "TypedValue") -> Tuple[str, tuple]:
        """A date-time literal: ``DATETIME '...'`` or ``TIMESTAMP '...'``.

        BigQuery's grammar has a zoneless date-time type and an absolute
        one, and the naive/aware distinction names them exactly: a naive
        ``datetime`` is wall time with no zone, spelled ``DATETIME '...'``
        -- the zoneless literal, with no offset invented -- and an aware
        one is an absolute point, spelled ``TIMESTAMP '...'`` with the
        offset the value carries. This mapping neither adds a zone to a
        naive value nor drops the one an aware value holds, which is the
        same line the core node draws between the two.
        """
        if not type(expr).inline_params:
            return self._bind_value(expr)
        if expr.value.tzinfo is None:
            return f"DATETIME {self.format_literal(expr.value)}", ()
        return f"TIMESTAMP {self.format_literal(expr.value)}", ()
