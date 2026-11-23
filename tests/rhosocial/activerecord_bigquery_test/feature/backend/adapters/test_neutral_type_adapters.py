# tests/rhosocial/activerecord_bigquery_test/feature/backend/adapters/test_neutral_type_adapters.py
"""DB-free contract tests for the BigQuery neutral-type adapters.

No BigQuery endpoint is contacted: the adapters are exercised through
``to_database`` / ``from_database`` only. The wire forms under test are the
ones documented in ``rhosocial.activerecord.backend.impl.bigquery.adapters``:

    Geometry   -> GEOGRAPHY (WKT text)
    Vector     -> ARRAY<FLOAT64> (Python list) / STRING (JSON text)
    BitString  -> BYTES (whole bytes only) / STRING (canonical bit text)
    Range      -> RANGE<...> ({"start", "end"} mapping / [start, end) literal)
    Multirange -> STRING (JSON text; BigQuery has no MULTIRANGE)
    MacAddress -> STRING (canonical colon text)
    IPAddress  -> STRING (canonical IPv4/IPv6 text)
"""

import datetime
import json

import pytest

from rhosocial.activerecord.backend.adapters import (
    BitString,
    Geometry,
    IPAddress,
    MacAddress,
    Multirange,
    Point,
    Range,
    Vector,
)
from rhosocial.activerecord.backend.errors import TypeConversionError
from rhosocial.activerecord.backend.impl.bigquery.adapters import (
    BigQueryBitStringAdapter,
    BigQueryGeometryAdapter,
    BigQueryIPAddressAdapter,
    BigQueryMacAddressAdapter,
    BigQueryRangeAdapter,
    BigQueryVectorAdapter,
)
from rhosocial.activerecord.backend.impl.bigquery.backend.backend import (
    BigQueryBackend,
)


NEUTRAL_ADAPTER_CLASSES = (
    BigQueryBitStringAdapter,
    BigQueryGeometryAdapter,
    BigQueryIPAddressAdapter,
    BigQueryMacAddressAdapter,
    BigQueryRangeAdapter,
    BigQueryVectorAdapter,
)


class TestGeometryAdapter:
    def test_wkt_round_trip(self):
        adapter = BigQueryGeometryAdapter()
        geometry = Point(1.5, -2)

        encoded = adapter.to_database(geometry, str)
        assert encoded == "POINT (1.5 -2.0)"

        assert adapter.from_database(encoded, Geometry) == geometry

    def test_compact_wkt_is_accepted(self):
        adapter = BigQueryGeometryAdapter()
        assert adapter.from_database("POINT(1 2)", Geometry) == Point(1, 2)

    def test_unparseable_wkt_is_wrapped(self):
        adapter = BigQueryGeometryAdapter()
        with pytest.raises(TypeConversionError):
            adapter.from_database("POINT(1 2 3)", Geometry)


class TestVectorAdapter:
    def test_list_round_trip(self):
        adapter = BigQueryVectorAdapter()
        vector = Vector([0.5, 2, -4])

        encoded = adapter.to_database(vector, list)
        assert encoded == [0.5, 2.0, -4.0]
        assert adapter.from_database(encoded, Vector) == vector

    def test_text_round_trip(self):
        """A STRING carrier binds the canonical JSON list."""
        adapter = BigQueryVectorAdapter()
        vector = Vector([1.0, 2.5, -3.0])

        encoded = adapter.to_database(vector, str)
        assert encoded == "[1.0, 2.5, -3.0]"
        assert json.loads(encoded) == [1.0, 2.5, -3.0]
        assert adapter.from_database(encoded, Vector) == vector

    def test_non_sequence_is_wrapped(self):
        adapter = BigQueryVectorAdapter()
        with pytest.raises(TypeConversionError):
            adapter.to_database(3, list)

    def test_scalar_decode_is_wrapped(self):
        adapter = BigQueryVectorAdapter()
        with pytest.raises(TypeConversionError):
            adapter.from_database(3.5, Vector)


class TestBitStringAdapter:
    def test_byte_aligned_round_trip(self):
        adapter = BigQueryBitStringAdapter()
        bits = BitString.from_bits("10110011")

        encoded = adapter.to_database(bits, bytes)
        assert encoded == b"\xb3"
        assert adapter.from_database(encoded, BitString) == bits

    def test_sub_byte_length_is_rejected(self):
        adapter = BigQueryBitStringAdapter()
        with pytest.raises(TypeConversionError) as excinfo:
            adapter.to_database(BitString.from_bits("1011"), bytes)
        assert "whole bytes" in str(excinfo.value)

    def test_text_keeps_the_bit_length(self):
        """A STRING carrier keeps leading zeros and sub-byte lengths."""
        adapter = BigQueryBitStringAdapter()
        bits = BitString(data=b"\x28", bit_length=5)

        encoded = adapter.to_database(bits, str)
        assert encoded == "00101"
        assert adapter.from_database(encoded, BitString) == bits
        assert adapter.from_database(encoded, BitString).bit_length == 5


class TestRangeAdapter:
    def test_mapping_round_trip(self):
        adapter = BigQueryRangeAdapter()
        value = Range(datetime.date(2024, 1, 1), datetime.date(2024, 2, 1))

        encoded = adapter.to_database(value, dict)
        assert encoded == {
            "start": datetime.date(2024, 1, 1),
            "end": datetime.date(2024, 2, 1),
        }

        assert adapter.from_database(encoded, Range) == value

    def test_literal_round_trip(self):
        adapter = BigQueryRangeAdapter()
        value = Range(datetime.date(2024, 1, 1), datetime.date(2024, 2, 1))

        encoded = adapter.to_database(value, str)
        assert encoded == "[2024-01-01, 2024-02-01)"
        assert adapter.from_database(encoded, Range) == value

    def test_unbounded_endpoints_use_unbounded_keyword(self):
        adapter = BigQueryRangeAdapter()
        value = Range(None, datetime.date(2025, 1, 1))

        encoded = adapter.to_database(value, str)
        assert encoded == "[UNBOUNDED, 2025-01-01)"
        assert adapter.from_database(encoded, Range) == value

    def test_datetime_range_round_trip(self):
        adapter = BigQueryRangeAdapter()
        value = Range(
            datetime.datetime(2024, 1, 1, 8, 0),
            datetime.datetime(2024, 1, 2, 8, 0),
        )
        assert adapter.from_database(adapter.to_database(value, dict), Range) == value

    def test_closed_bounds_are_rejected(self):
        adapter = BigQueryRangeAdapter()
        with pytest.raises(TypeConversionError) as excinfo:
            adapter.to_database(Range(1, 5, "[]"), dict)
        assert "cannot be represented" in str(excinfo.value)

    def test_exclusive_lower_bound_is_rejected(self):
        adapter = BigQueryRangeAdapter()
        with pytest.raises(TypeConversionError) as excinfo:
            adapter.to_database(Range(1, 5, "(]"), dict)
        assert "inclusive lower bound" in str(excinfo.value)

    def test_empty_range_is_rejected(self):
        adapter = BigQueryRangeAdapter()
        with pytest.raises(TypeConversionError):
            adapter.to_database(Range(None, None, "[)", True), dict)

    def test_multirange_is_json_text(self):
        adapter = BigQueryRangeAdapter()
        value = Multirange((Range(1, 5), Range(7, 9)))

        encoded = adapter.to_database(value, str)
        assert json.loads(encoded) == value.to_json_value()

        assert adapter.from_database(encoded, Multirange) == value

    def test_multirange_rejects_mapping_target(self):
        adapter = BigQueryRangeAdapter()
        with pytest.raises(TypeConversionError):
            adapter.to_database(Multirange((Range(1, 5),)), dict)

    def test_malformed_mapping_is_wrapped(self):
        adapter = BigQueryRangeAdapter()
        with pytest.raises(TypeConversionError):
            adapter.from_database({"start": datetime.date(2024, 1, 1)}, Range)


class TestMacAddressAdapter:
    def test_canonical_text_round_trip(self):
        adapter = BigQueryMacAddressAdapter()
        mac = MacAddress.parse("08:00:2B:01:02:03")

        encoded = adapter.to_database(mac, str)
        assert encoded == "08:00:2b:01:02:03"
        assert adapter.from_database(encoded, MacAddress) == mac

    def test_bad_text_is_wrapped(self):
        adapter = BigQueryMacAddressAdapter()
        with pytest.raises(TypeConversionError):
            adapter.from_database("nope", MacAddress)


class TestIPAddressAdapter:
    @pytest.mark.parametrize("text", ["192.0.2.1", "2001:db8::1"])
    def test_canonical_text_round_trip(self, text):
        adapter = BigQueryIPAddressAdapter()
        ip = IPAddress.parse(text)

        encoded = adapter.to_database(ip, str)
        assert encoded == text
        assert adapter.from_database(encoded, IPAddress) == ip

    def test_bad_text_is_wrapped(self):
        adapter = BigQueryIPAddressAdapter()
        with pytest.raises(TypeConversionError):
            adapter.from_database("not-an-ip", IPAddress)


def test_inventory_contains_neutral_adapters():
    backend = BigQueryBackend(project="demo", dataset="demo")
    inventory = backend.get_type_adapters()

    for adapter_cls in NEUTRAL_ADAPTER_CLASSES:
        assert any(isinstance(adapter, adapter_cls) for adapter in inventory), (
            f"{adapter_cls.__name__} missing from get_type_adapters()"
        )
