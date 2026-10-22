# tests/rhosocial/activerecord_bigquery_test/feature/backend/dialect/test_bigquery_literal_values.py
"""BigQuery's inline literal spellings (rendering only, no server).

Every assertion is a rendering assertion against the documented GoogleSQL
literal grammar (lexical structure and syntax / data types, read 2026-10-17
-- **not server-verified**: no BigQuery instance is reachable from this
repository). Each claim is asserted at both positions the one value node
splits rendering into:

* the **data position** -- ``Literal(dialect, value)``, ``inline`` at its
  default ``False`` -- binds the host value behind ``?`` and converts
  nothing;
* the **DDL syntax position** -- ``Literal(dialect, value, inline=True)`` --
  writes the inline literal text through ``format_literal``.

The explicit refusals -- an INTERVAL step that cannot fit the ``INT64`` the
grammar takes, a ``Decimal`` outside both decimal types' documented range, a
non-finite ``Decimal``, an aware ``time`` -- are asserted with their
messages.
"""

import datetime
import decimal
import uuid

import pytest

from rhosocial.activerecord.backend.dialect.base import SQLDialectBase
from rhosocial.activerecord.backend.expression.core import Literal
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect
from rhosocial.activerecord.backend.impl.bigquery.mixins import (
    BigQueryLiteralValueMixin,
)


@pytest.fixture
def dialect():
    return BigQueryDialect()


def _inline(dialect, value):
    """The DDL-position rendering of *value* as ``(sql, params)``."""
    return Literal(dialect, value, inline=True).to_sql()


class TestWiring:
    """The dialect composes this backend's spelling ahead of the base's."""

    def test_backend_mixin_outranks_the_base(self):
        mro = BigQueryDialect.__mro__
        assert mro.index(BigQueryLiteralValueMixin) < mro.index(SQLDialectBase)

    def test_the_overridden_entry_point_is_this_mixin(self, dialect):
        assert (
            BigQueryDialect.format_literal.__qualname__
            == "BigQueryLiteralValueMixin.format_literal"
        )


class TestBindingDecision:
    """``inline`` decides bind-or-text; BigQuery's placeholder is ``?``."""

    def test_data_position_binds_the_host_value(self, dialect):
        assert Literal(dialect, 42).to_sql() == ("?", (42,))

    def test_inline_position_writes_text(self, dialect):
        assert _inline(dialect, 42) == ("42", ())


class TestBinary:
    def test_data_position_binds_the_bytes(self, dialect):
        assert Literal(dialect, b"\x01\x02").to_sql() == ("?", (b"\x01\x02",))

    def test_inline_position_spells_the_bytes_literal(self, dialect):
        assert _inline(dialect, b"\x01\x02") == ("b'\\x01\\x02'", ())

    def test_every_byte_becomes_one_hex_escape(self, dialect):
        assert _inline(dialect, b"\x00\x0a\xff\x7f") == ("b'\\x00\\x0a\\xff\\x7f'", ())

    def test_empty_bytes_are_the_empty_literal(self, dialect):
        assert _inline(dialect, b"") == ("b''", ())


class TestUUID:
    _VALUE = uuid.UUID("123e4567-e89b-12d3-a456-426614174000")

    def test_data_position_binds_the_uuid(self, dialect):
        assert Literal(dialect, self._VALUE).to_sql() == ("?", (self._VALUE,))

    def test_inline_position_is_the_bare_quoted_text(self, dialect):
        assert _inline(dialect, self._VALUE) == (
            "'123e4567-e89b-12d3-a456-426614174000'",
            (),
        )


class TestInterval:
    def test_data_position_binds_the_timedelta(self, dialect):
        value = datetime.timedelta(days=1)
        assert Literal(dialect, value).to_sql() == ("?", (value,))

    @pytest.mark.parametrize(
        "value, expected",
        [
            # The single-datetime-part literal: INTERVAL step_size step_unit,
            # unquoted, step an INT64 (lexical structure and syntax).
            (datetime.timedelta(days=1), "INTERVAL 1 DAY"),
            (datetime.timedelta(days=-5), "INTERVAL -5 DAY"),
            (datetime.timedelta(weeks=6), "INTERVAL 42 DAY"),
            (datetime.timedelta(hours=25), "INTERVAL 25 HOUR"),
            (datetime.timedelta(minutes=90), "INTERVAL 90 MINUTE"),
            (datetime.timedelta(seconds=1), "INTERVAL 1 SECOND"),
            (datetime.timedelta(milliseconds=500), "INTERVAL 500 MILLISECOND"),
            (datetime.timedelta(microseconds=3), "INTERVAL 3 MICROSECOND"),
            # A day plus two seconds is a whole number of seconds: SECOND is
            # the largest unit that divides the span exactly, so it is the
            # step (the documented examples spell whole-second spans that
            # way too: INTERVAL 90000 SECOND).
            (datetime.timedelta(days=1, seconds=2), "INTERVAL 86402 SECOND"),
            # An odd microsecond count: no unit above MICROSECOND divides
            # it, so it is spelled exactly, in microseconds.
            (
                datetime.timedelta(days=-1, seconds=-2, microseconds=-3),
                "INTERVAL -86402000003 MICROSECOND",
            ),
            # timedelta(seconds=-90) is -1.5 minutes: the step must be the
            # one unit that holds it exactly, not a rounded-up neighbour.
            (datetime.timedelta(seconds=-90), "INTERVAL -90 SECOND"),
            (datetime.timedelta(0), "INTERVAL 0 DAY"),
        ],
    )
    def test_inline_position_spells_the_single_part_form(self, dialect, value, expected):
        assert _inline(dialect, value) == (expected, ())

    def test_the_int64_step_boundary_is_spelled(self, dialect):
        value = datetime.timedelta(microseconds=2**63 - 1)
        assert _inline(dialect, value) == ("INTERVAL 9223372036854775807 MICROSECOND", ())

    def test_a_step_beyond_int64_is_refused(self, dialect):
        with pytest.raises(ValueError, match="INT64"):
            _inline(dialect, datetime.timedelta(microseconds=2**63))


class TestDecimal:
    def test_data_position_binds_the_decimal(self, dialect):
        value = decimal.Decimal("3.14")
        assert Literal(dialect, value).to_sql() == ("?", (value,))

    @pytest.mark.parametrize(
        "value, expected",
        [
            # NUMERIC literal: the keyword followed by the quoted value
            # (lexical structure and syntax, NUMERIC literals).
            (decimal.Decimal("0"), "NUMERIC '0'"),
            (decimal.Decimal("-3.14"), "NUMERIC '-3.14'"),
            # 29 integer digits is NUMERIC's whole integer budget (38 - 9);
            # an int-constructed Decimal carries exponent 0, so str() spells
            # it as the plain digits.
            (decimal.Decimal(10**28), "NUMERIC '10000000000000000000000000000'"),
            # 1.23456e05 is exactly 123456: the coefficient folds into plain
            # digits at this exponent, and that is the literal rendered.
            (decimal.Decimal("1.23456e05"), "NUMERIC '123456'"),
            # A Decimal constructed from an E-form string keeps the exponent,
            # so str() gives '9E+28' -- and the marker is lowered to match the
            # documented literal examples ('1.23456e05', '-9.876e-3').
            (decimal.Decimal("9E+28"), "NUMERIC '9e+28'"),
            # Scale 10 is past NUMERIC's 9; BIGNUMERIC is the literal that
            # holds it.
            (decimal.Decimal("123.4567890123"), "BIGNUMERIC '123.4567890123'"),
            # 30 integer digits is past NUMERIC's 29 but inside
            # BIGNUMERIC's documented range.
            (decimal.Decimal(10**29), "BIGNUMERIC '100000000000000000000000000000'"),
            # 1e-38 is BIGNUMERIC's documented minimum magnitude -- scale
            # 38, the last scale the type takes.
            (decimal.Decimal("1e-38"), "BIGNUMERIC '1e-38'"),
        ],
    )
    def test_inline_position_spells_the_keyword_literal(self, dialect, value, expected):
        assert _inline(dialect, value) == (expected, ())

    def test_the_partial_39th_integer_digit_is_inside_the_range(self, dialect):
        # 1e38 has a 39-digit integer part -- the partial digit of the
        # "approximately 76.8 digits" precision -- and is inside
        # BIGNUMERIC's documented range, so it is spelled, not refused.
        assert _inline(dialect, decimal.Decimal("1e38")) == ("BIGNUMERIC '1e+38'", ())

    def test_the_documented_bignumeric_bounds_are_spelled(self, dialect):
        # The documented Min and Max, transcribed from the data-types
        # reference: the two bounds are one unit apart, because the
        # negative side of a scaled fixed point holds one step more than
        # the positive one. Both store exponent -38 (E+38 over 77
        # significant digits), so str() gives the plain form -- 39 integer
        # digits, point, 38 fractional digits -- which the quoted-value
        # grammar takes as it stands.
        assert _inline(
            dialect,
            decimal.Decimal(
                "5.7896044618658097711785492504343953926634992332820282019728792003956564819967E+38"
            ),
        ) == (
            "BIGNUMERIC '578960446186580977117854925043439539266.34992332820282019728792003956564819967'",
            (),
        )
        assert _inline(
            dialect,
            decimal.Decimal(
                "-5.7896044618658097711785492504343953926634992332820282019728792003956564819968E+38"
            ),
        ) == (
            "BIGNUMERIC '-578960446186580977117854925043439539266.34992332820282019728792003956564819968'",
            (),
        )

    def test_past_bignumerics_documented_range_is_refused(self, dialect):
        with pytest.raises(ValueError, match="BIGNUMERIC"):
            _inline(dialect, decimal.Decimal("6e38"))

    def test_a_scale_past_bignumerics_is_refused(self, dialect):
        with pytest.raises(ValueError, match="BIGNUMERIC"):
            _inline(dialect, decimal.Decimal("1e-39"))

    def test_non_finite_is_refused(self, dialect):
        with pytest.raises(ValueError, match="non-finite"):
            _inline(dialect, decimal.Decimal("NaN"))


class TestDate:
    def test_data_position_binds_the_date(self, dialect):
        value = datetime.date(2014, 9, 27)
        assert Literal(dialect, value).to_sql() == ("?", (value,))

    def test_inline_position_spells_the_typed_literal(self, dialect):
        assert _inline(dialect, datetime.date(2014, 9, 27)) == ("DATE '2014-09-27'", ())


class TestTime:
    def test_data_position_binds_the_time(self, dialect):
        value = datetime.time(12, 30)
        assert Literal(dialect, value).to_sql() == ("?", (value,))

    def test_inline_position_spells_the_typed_literal(self, dialect):
        assert _inline(dialect, datetime.time(12, 30, 0, 450000)) == (
            "TIME '12:30:00.450000'",
            (),
        )

    def test_an_aware_time_is_refused_not_silently_zone_stripped(self, dialect):
        value = datetime.time(
            12, 30, tzinfo=datetime.timezone(datetime.timedelta(hours=5))
        )
        with pytest.raises(ValueError, match="aware time"):
            _inline(dialect, value)


class TestTimestamp:
    def test_data_position_binds_the_datetime(self, dialect):
        value = datetime.datetime(2014, 9, 27, 12, 30)
        assert Literal(dialect, value).to_sql() == ("?", (value,))

    def test_a_naive_datetime_is_the_zoneless_datetime_literal(self, dialect):
        assert _inline(dialect, datetime.datetime(2014, 9, 27, 12, 30, 0, 450000)) == (
            "DATETIME '2014-09-27 12:30:00.450000'",
            (),
        )

    def test_an_aware_datetime_is_the_timestamp_literal_with_its_offset(self, dialect):
        value = datetime.datetime(
            2014, 9, 27, 12, 30, tzinfo=datetime.timezone(datetime.timedelta(hours=5))
        )
        assert _inline(dialect, value) == ("TIMESTAMP '2014-09-27 12:30:00+05:00'", ())


class TestTheKindsBigQueryAgreesWith:
    """Tier 1 audited against the grammar: the base's spellings apply.

    ``NULL`` is the keyword, ``BOOL`` takes ``TRUE``/``FALSE``, ``INT64``
    and ``FLOAT64`` literals are numeric text, and a ``STRING`` literal is
    quoted -- all of them the base's own answers, kept by position.
    """

    def test_null_binds_and_spells_the_keyword(self, dialect):
        assert Literal(dialect, None).to_sql() == ("?", (None,))
        assert _inline(dialect, None) == ("NULL", ())

    @pytest.mark.parametrize("value, expected", [(True, "TRUE"), (False, "FALSE")])
    def test_boolean_spells_true_false(self, dialect, value, expected):
        assert _inline(dialect, value) == (expected, ())

    def test_integer_spells_numeric_text(self, dialect):
        assert _inline(dialect, 123) == ("123", ())

    def test_float_spells_numeric_text(self, dialect):
        assert _inline(dialect, 1.5) == ("1.5", ())

    def test_string_spells_quoted(self, dialect):
        assert _inline(dialect, "abc") == ("'abc'", ())

    def test_string_escapes_the_quote_with_a_backslash(self, dialect):
        assert _inline(dialect, "it's") == ("'it\\'s'", ())

    def test_string_escapes_the_backslash_itself(self, dialect):
        assert _inline(dialect, "a\\b") == ("'a\\\\b'", ())


class TestTheNonFiniteFloats:
    """NaN and the infinities never reach SQL text (core kinds of their own).

    The base refuses them at the literal entry point, and BigQuery adds no
    spelling: a ``float`` position carrying one has no SQL text, and the
    kinds that carry them travel as text in the artifact rather than as SQL.
    """

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
    def test_refused_at_the_literal_entry_point(self, dialect, value):
        with pytest.raises(ValueError):
            _inline(dialect, value)


class TestTheDialectWideEscapePolicy:
    """``escape_sql_string`` is the one place GoogleSQL's escaping lives.

    The escape table documents ``\\'`` for a single quote and makes
    backslashes escape-sequence introducers, so a literal backslash is
    doubled first; quote doubling is not in the table at all. Every inline
    string the dialect renders -- literals, OPTIONS entries, comments --
    goes through this policy.
    """

    def test_a_single_quote(self, dialect):
        assert dialect.format_literal("it's") == "'it\\'s'"

    def test_a_backslash_before_the_quote(self, dialect):
        assert dialect.format_literal("a\\b'c") == "'a\\\\b\\'c'"

    def test_the_public_helper_agrees(self, dialect):
        assert dialect.escape_sql_string("it's") == "it\\'s"
