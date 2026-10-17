# tests/rhosocial/activerecord_bigquery_test/feature/backend/dialect/test_bigquery_typed_values.py
"""BigQuery's spellings for the typed value nodes (rendering only, no server).

Every assertion is a rendering assertion against the documented GoogleSQL
literal grammar (lexical structure and syntax / data types, read 2026-10-17
-- **not server-verified**: no BigQuery instance is reachable from this
repository). Each kind asserts both positions the class-level
``inline_params`` strategy splits rendering into:

* the **data position** (the shipped classes: ``inline_params = False``)
  binds the host value behind ``?`` and converts nothing;
* the **DDL syntax position** (``inline_params = True``, declared by the
  test-local ``Ddl*`` classes the way the core lifts ``Literal`` to
  ``DdlLiteral``) spells the inline literal exactly.

The explicit refusals -- an INTERVAL step that cannot fit the ``INT64`` the
grammar takes, a ``Decimal`` outside both decimal types' documented range,
a non-finite ``Decimal``, an aware ``time`` -- are asserted with their
messages.
"""

import datetime
import decimal
import uuid

import pytest

from rhosocial.activerecord.backend.expression.values import (
    BinaryValue,
    BooleanValue,
    DateValue,
    DecimalValue,
    FloatValue,
    IntegerValue,
    IntervalValue,
    NullValue,
    StringValue,
    TimeValue,
    TimestampValue,
    UUIDValue,
)
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect


@pytest.fixture
def dialect():
    return BigQueryDialect()


def _ddl(cls):
    """*cls* with the DDL-position strategy, declared as a class of its own.

    Whether a value inlines is the **class's** decision (spec 4.4), never a
    per-instance flag -- so the test says it the only way the contract
    allows, a subclass declaring ``inline_params = True``, which is the
    same move the core makes when it lifts ``Literal`` to ``DdlLiteral``
    for a DDL condition it owns.
    """
    return type(f"Ddl{cls.__name__}", (cls,), {"inline_params": True})


class TestWiring:
    """The dialect composes this backend's spellings ahead of the base's."""

    def test_backend_mixin_wins_the_overridden_kinds(self, dialect):
        for name in (
            "format_binary_value",
            "format_uuid_value",
            "format_interval_value",
            "format_decimal_value",
            "format_date_value",
            "format_time_value",
            "format_timestamp_value",
        ):
            assert getattr(dialect, name).__qualname__.startswith(
                "BigQueryTypedValueMixin."
            )

    def test_base_mixin_answers_the_untouched_kinds(self, dialect):
        for name in (
            "format_null_value",
            "format_boolean_value",
            "format_integer_value",
            "format_float_value",
            "format_string_value",
        ):
            assert getattr(dialect, name).__qualname__.startswith(
                "TypedValueMixin."
            )


class TestBinaryValue:
    def test_data_position_binds_the_bytes(self, dialect):
        assert BinaryValue(dialect, b"\x01\x02").to_sql() == ("?", (b"\x01\x02",))

    def test_ddl_position_spells_the_bytes_literal(self, dialect):
        assert _ddl(BinaryValue)(dialect, b"\x01\x02").to_sql() == (
            "b'\\x01\\x02'",
            (),
        )

    def test_every_byte_becomes_one_hex_escape(self, dialect):
        assert _ddl(BinaryValue)(dialect, b"\x00\x0a\xff\x7f").to_sql() == (
            "b'\\x00\\x0a\\xff\\x7f'",
            (),
        )

    def test_empty_bytes_are_the_empty_literal(self, dialect):
        assert _ddl(BinaryValue)(dialect, b"").to_sql() == ("b''", ())


class TestUUIDValue:
    def test_data_position_binds_the_uuid(self, dialect):
        value = uuid.UUID("123e4567-e89b-12d3-a456-426614174000")
        assert UUIDValue(dialect, value).to_sql() == ("?", (value,))

    def test_ddl_position_is_the_bare_quoted_text(self, dialect):
        assert _ddl(UUIDValue)(
            dialect, uuid.UUID("123e4567-e89b-12d3-a456-426614174000")
        ).to_sql() == (
            "'123e4567-e89b-12d3-a456-426614174000'",
            (),
        )


class TestIntervalValue:
    def test_data_position_binds_the_timedelta(self, dialect):
        assert IntervalValue(dialect, datetime.timedelta(days=1)).to_sql() == (
            "?",
            (datetime.timedelta(days=1),),
        )

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
    def test_ddl_position_spells_the_single_part_form(self, dialect, value, expected):
        assert _ddl(IntervalValue)(dialect, value).to_sql() == (expected, ())

    def test_the_int64_step_boundary_is_spelled(self, dialect):
        value = datetime.timedelta(microseconds=2**63 - 1)
        assert _ddl(IntervalValue)(dialect, value).to_sql() == (
            "INTERVAL 9223372036854775807 MICROSECOND",
            (),
        )

    def test_a_step_beyond_int64_is_refused(self, dialect):
        with pytest.raises(ValueError, match="INT64"):
            _ddl(IntervalValue)(dialect, datetime.timedelta(microseconds=2**63)).to_sql()


class TestDecimalValue:
    def test_data_position_binds_the_decimal(self, dialect):
        assert DecimalValue(dialect, decimal.Decimal("3.14")).to_sql() == (
            "?",
            (decimal.Decimal("3.14"),),
        )

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
    def test_ddl_position_spells_the_keyword_literal(self, dialect, value, expected):
        assert _ddl(DecimalValue)(dialect, value).to_sql() == (expected, ())

    def test_the_partial_39th_integer_digit_is_inside_the_range(self, dialect):
        # 1e38 has a 39-digit integer part -- the partial digit of the
        # "approximately 76.8 digits" precision -- and is inside
        # BIGNUMERIC's documented range, so it is spelled, not refused.
        assert _ddl(DecimalValue)(dialect, decimal.Decimal("1e38")).to_sql() == (
            "BIGNUMERIC '1e+38'",
            (),
        )

    def test_the_documented_bignumeric_bounds_are_spelled(self, dialect):
        # The documented Min and Max, transcribed from the data-types
        # reference: the two bounds are one unit apart, because the
        # negative side of a scaled fixed point holds one step more than
        # the positive one. Both store exponent -38 (E+38 over 77
        # significant digits), so str() gives the plain form -- 39 integer
        # digits, point, 38 fractional digits -- which the quoted-value
        # grammar takes as it stands.
        assert _ddl(DecimalValue)(dialect, decimal.Decimal(
            "5.7896044618658097711785492504343953926634992332820282019728792003956564819967E+38"
        )).to_sql() == (
            "BIGNUMERIC '578960446186580977117854925043439539266.34992332820282019728792003956564819967'",
            (),
        )
        assert _ddl(DecimalValue)(dialect, decimal.Decimal(
            "-5.7896044618658097711785492504343953926634992332820282019728792003956564819968E+38"
        )).to_sql() == (
            "BIGNUMERIC '-578960446186580977117854925043439539266.34992332820282019728792003956564819968'",
            (),
        )

    def test_past_bignumerics_documented_range_is_refused(self, dialect):
        with pytest.raises(ValueError, match="BIGNUMERIC"):
            _ddl(DecimalValue)(dialect, decimal.Decimal("6e38")).to_sql()

    def test_a_scale_past_bignumerics_is_refused(self, dialect):
        with pytest.raises(ValueError, match="BIGNUMERIC"):
            _ddl(DecimalValue)(dialect, decimal.Decimal("1e-39")).to_sql()

    def test_non_finite_is_refused(self, dialect):
        with pytest.raises(ValueError, match="non-finite"):
            _ddl(DecimalValue)(dialect, decimal.Decimal("NaN")).to_sql()


class TestDateValue:
    def test_data_position_binds_the_date(self, dialect):
        assert DateValue(dialect, datetime.date(2014, 9, 27)).to_sql() == (
            "?",
            (datetime.date(2014, 9, 27),),
        )

    def test_ddl_position_spells_the_typed_literal(self, dialect):
        assert _ddl(DateValue)(dialect, datetime.date(2014, 9, 27)).to_sql() == (
            "DATE '2014-09-27'",
            (),
        )


class TestTimeValue:
    def test_data_position_binds_the_time(self, dialect):
        assert TimeValue(dialect, datetime.time(12, 30)).to_sql() == (
            "?",
            (datetime.time(12, 30),),
        )

    def test_ddl_position_spells_the_typed_literal(self, dialect):
        value = datetime.time(12, 30, 0, 450000)
        assert _ddl(TimeValue)(dialect, value).to_sql() == (
            "TIME '12:30:00.450000'",
            (),
        )

    def test_an_aware_time_is_refused_not_silently_zone_stripped(self, dialect):
        value = datetime.time(
            12, 30, tzinfo=datetime.timezone(datetime.timedelta(hours=5))
        )
        with pytest.raises(ValueError, match="aware time"):
            _ddl(TimeValue)(dialect, value).to_sql()


class TestTimestampValue:
    def test_data_position_binds_the_datetime(self, dialect):
        assert TimestampValue(dialect, datetime.datetime(2014, 9, 27, 12, 30)).to_sql() == (
            "?",
            (datetime.datetime(2014, 9, 27, 12, 30),),
        )

    def test_a_naive_datetime_is_the_zoneless_datetime_literal(self, dialect):
        value = datetime.datetime(2014, 9, 27, 12, 30, 0, 450000)
        assert _ddl(TimestampValue)(dialect, value).to_sql() == (
            "DATETIME '2014-09-27 12:30:00.450000'",
            (),
        )

    def test_an_aware_datetime_is_the_timestamp_literal_with_its_offset(self, dialect):
        value = datetime.datetime(
            2014, 9, 27, 12, 30, tzinfo=datetime.timezone(datetime.timedelta(hours=5))
        )
        assert _ddl(TimestampValue)(dialect, value).to_sql() == (
            "TIMESTAMP '2014-09-27 12:30:00+05:00'",
            (),
        )


class TestTheKindsBigQueryAgreesWith:
    """Tier 1 audited against the grammar: the base's spellings apply.

    ``NULL`` is the keyword, ``BOOL`` takes ``TRUE``/``FALSE``, ``INT64``
    and ``FLOAT64`` literals are numeric text, and a ``STRING`` literal is
    quoted -- all of them the core mixin's own answers, kept by position.
    """

    def test_null_binds_and_spells_the_keyword(self, dialect):
        assert NullValue(dialect).to_sql() == ("?", (None,))
        assert _ddl(NullValue)(dialect).to_sql() == ("NULL", ())

    @pytest.mark.parametrize("value, expected", [(True, "TRUE"), (False, "FALSE")])
    def test_boolean_spells_true_false(self, dialect, value, expected):
        assert _ddl(BooleanValue)(dialect, value).to_sql() == (expected, ())

    def test_integer_spells_numeric_text(self, dialect):
        assert _ddl(IntegerValue)(dialect, 123).to_sql() == ("123", ())

    def test_float_spells_numeric_text(self, dialect):
        assert _ddl(FloatValue)(dialect, 1.5).to_sql() == ("1.5", ())

    def test_string_spells_quoted(self, dialect):
        assert _ddl(StringValue)(dialect, "abc").to_sql() == ("'abc'", ())

    def test_string_escapes_the_quote_with_a_backslash(self, dialect):
        assert _ddl(StringValue)(dialect, "it's").to_sql() == ("'it\\'s'", ())

    def test_string_escapes_the_backslash_itself(self, dialect):
        assert _ddl(StringValue)(dialect, "a\\b").to_sql() == ("'a\\\\b'", ())


class TestTheDialectWideEscapePolicy:
    """``_escape_sql_string`` is the one place GoogleSQL's escaping lives.

    The escape table documents ``\\'`` for a single quote and makes
    backslashes escape-sequence introducers, so a literal backslash is
    doubled first; quote doubling is not in the table at all. Every inline
    string the dialect renders -- value nodes, OPTIONS entries, comments --
    goes through this policy.
    """

    def test_a_single_quote(self, dialect):
        assert dialect.format_literal("it's") == "'it\\'s'"

    def test_a_backslash_before_the_quote(self, dialect):
        assert dialect.format_literal("a\\b'c") == "'a\\\\b\\'c'"

    def test_the_public_helper_agrees(self, dialect):
        assert dialect.escape_sql_string("it's") == "it\\'s"
