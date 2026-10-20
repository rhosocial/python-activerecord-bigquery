# src/rhosocial/activerecord/backend/impl/bigquery/mixins/literal.py
"""BigQuery's inline literal spellings.

``SQLDialectBase.format_literal`` is the single entry point for writing a
value as SQL text, and it resolves in three tiers: the portable scalars it
knows, the types a backend spells for itself, and the literal-construction
protocol. This module is BigQuery's second tier.

Evidence level: 文档（not server-verified）
------------------------------------------
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

Every other host type falls through to the base implementation, which is
where the portable forms and the literal-construction protocol live. A type
neither tier names -- ``timedelta`` is *not* one of them here, it has its own
branch above -- reaches the base's explicit ``TypeError``, and that refusal
is the answer rather than a gap.
"""

import datetime
import decimal
import uuid
from typing import Any

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


class BigQueryLiteralValueMixin:
    """BigQuery's branches of :meth:`format_literal`.

    Stands alone rather than inheriting the base, and the dialect composes it
    **ahead of** ``SQLDialectBase`` -- the one base that defines
    ``format_literal`` -- because a mixin placed after the class it overrides
    never wins the lookup. Everything this class does not claim falls through
    to that base, which is where the portable forms and the
    literal-construction protocol live.
    """

    def format_literal(self, value: Any) -> str:
        """Render *value* as inline SQL text, BigQuery's spelling where it has one.

        Args:
            value: The host value to write into the statement.

        Returns:
            The escaped literal text, without a bind parameter.

        Raises:
            ValueError: A ``Decimal`` is non-finite, its scale is past
                ``BIGNUMERIC``'s 38, or its magnitude is outside both decimal
                types' documented range; an aware ``time`` would have to drop
                its offset; an interval step does not fit a signed ``INT64``.
            TypeError: The base implementation refuses a type BigQuery has no
                literal form for, and this is the same refusal.
        """
        # ``datetime`` is a ``date`` subclass, so the narrower type has to be
        # tested first: the order of these branches is host-type order, the way
        # ``LiteralKind``'s member order is.
        if isinstance(value, (bytes, bytearray)):
            return "b'" + "".join(f"\\x{b:02x}" for b in bytes(value)) + "'"
        if isinstance(value, uuid.UUID):
            return super().format_literal(str(value))
        if isinstance(value, datetime.datetime):
            return self._datetime_literal(value)
        if isinstance(value, datetime.date):
            return f"DATE {super().format_literal(value)}"
        if isinstance(value, datetime.time):
            return self._time_literal(value)
        if isinstance(value, datetime.timedelta):
            return self._interval_literal(value)
        if isinstance(value, decimal.Decimal):
            return self._decimal_literal(value)
        return super().format_literal(value)

    # -- the typed literals ---------------------------------------------------

    def _decimal_literal(self, value: decimal.Decimal) -> str:
        """``NUMERIC '...'`` or ``BIGNUMERIC '...'``, by which range holds it.

        The keyword followed by a quoted value is the documented literal, and
        the only exact one -- bare numeric text is a ``FLOAT64`` literal,
        which is the approximation the value exists to avoid. The keyword is
        chosen by which type's documented range holds the value (data types,
        read 2026-10-17, not server-verified):

        * ``NUMERIC`` -- precision 38, scale 9, documented range
          ``+/-9.9999999999999999999999999999999999999E+28``. That bound is
          exactly 29 integer digits with scale 9, which is the form checked
          here.
        * ``BIGNUMERIC`` -- scale 38, documented range
          ``-5.789604...9968E+38`` to ``5.789604...9967E+38``. The integer
          part at the bound is 39 digits -- the partial digit of the
          "approximately 76.8 digits" precision -- so the magnitude is
          compared against the documented bounds themselves
          (:data:`_BIGNUMERIC_MIN` / :data:`_BIGNUMERIC_MAX`), which are one
          unit apart: the negative side holds one step more than the positive
          one.

        A value beyond both is refused here rather than written into SQL the
        server must reject.
        """
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
        return f"{keyword} {super().format_literal(text)}"

    def _time_literal(self, value: datetime.time) -> str:
        """``TIME '12:30:00.45'``, keyword and quoted text.

        The ``TIME`` keyword precedes the canonical time format, which is a
        time of day and nothing else: the type is documented as "independent
        of a specific date and time zone".
        """
        if value.tzinfo is not None:
            raise ValueError(
                f"{value.isoformat()} is an aware time, but BigQuery's TIME is "
                "a time of day independent of a specific date and time zone; "
                "spelling it would have to drop the offset silently, which the "
                "dialect does not do"
            )
        return f"TIME {super().format_literal(value)}"

    def _datetime_literal(self, value: datetime.datetime) -> str:
        """``DATETIME '...'`` or ``TIMESTAMP '...'``, by whether a zone is held.

        BigQuery's grammar has a zoneless date-time type and an absolute one,
        and the naive/aware distinction names them exactly: a naive
        ``datetime`` is wall time with no zone, spelled ``DATETIME '...'`` --
        the zoneless literal, with no offset invented -- and an aware one is
        an absolute point, spelled ``TIMESTAMP '...'`` with the offset the
        value carries. This mapping neither adds a zone to a naive value nor
        drops the one an aware value holds, which is the same line the core
        node draws between the two.
        """
        keyword = "DATETIME" if value.tzinfo is None else "TIMESTAMP"
        return f"{keyword} {super().format_literal(value)}"

    def _interval_literal(self, value: datetime.timedelta) -> str:
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
        """
        total_micros = (
            value.days * 86_400 + value.seconds
        ) * 1_000_000 + value.microseconds
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
        return f"INTERVAL {step} {unit}"


__all__ = ["BigQueryLiteralValueMixin"]
