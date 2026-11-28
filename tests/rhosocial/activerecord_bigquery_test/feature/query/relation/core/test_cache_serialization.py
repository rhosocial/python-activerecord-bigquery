# tests/rhosocial/activerecord_bigquery_test/feature/query/relation/test_cache_serialization.py
"""
Comprehensive round-trip tests for cache serialization.

Covers JSON (default), msgpack (when available), and pickle (UNSAFE)
serializers with simple values, complex Python objects, edge cases,
and large content from the testsuite sample files.
"""

import json
import math
import os
from functools import lru_cache
from datetime import date, datetime, time, timedelta
from enum import Enum, auto
from typing import Any, Dict, List, Optional

import pytest

from rhosocial.activerecord.relation.cache_backends._protocol import CacheSerializer  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _find_samples() -> Optional[str]:
    """Locate the testsuite sample directory."""
    try:
        import rhosocial.activerecord.testsuite as _ts

        base = os.path.dirname(_ts.__file__)
        for attempt in [
            os.path.join(base, "feature", "query", "samples"),
            os.path.join(base, "..", "..", "..", "..", "testsuite", "feature", "query", "samples"),
        ]:
            path = os.path.abspath(attempt)
            if os.path.isdir(path):
                return path
    except Exception:
        pass
    return None


def _load_sample(name: str) -> str:
    d = _find_samples()
    if d is None:
        pytest.skip("testsuite sample directory not found")
    path = os.path.join(d, name)
    if not os.path.exists(path):
        pytest.skip(f"sample file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------


class Color(Enum):
    RED = auto()
    GREEN = auto()
    BLUE = auto()


SIMPLE_VALUES: List[Any] = [
    "hello",
    "",
    0,
    1,
    -1,
    3.14,
    True,
    False,
    None,
    [],
    {},
    [1, 2, 3],
    {"a": 1, "b": 2},
]

COMPLEX_VALUES: List[Any] = [
    {"nested": {"deeply": [1, [2, [3]]], "key": "val"}},
    [{"id": i, "name": f"Item {i}"} for i in range(100)],
    {"mixed": [1, "two", 3.0, True, None, [1, 2], {"k": "v"}]},
    {"empty_nested": {"a": {}, "b": [], "c": {"d": {}}}},
]

EXTENDED_VALUES: List[Any] = [
    datetime(2026, 6, 2, 14, 30, 0, 123456),
    date(2026, 6, 2),
    time(14, 30, 0, 123456),
    timedelta(days=7, hours=3, minutes=15),
    Color.RED,
    bytes([0x00, 0xFF, 0xAB, 0xCD]),
    {1, 2, 3, 4, 5},
    complex(3, 4),
    range(0, 10, 2),
    {"dt": datetime.now(), "color": Color.BLUE, "data": bytes([1, 2, 3])},
    [datetime(2026, 1, 1), timedelta(hours=1), Color.GREEN],
]

FLOAT_EPS = 1e-9


# ---------------------------------------------------------------------------
# Serializer fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(params=["json", "msgpack", "pickle"])
def serializer(request) -> CacheSerializer:
    fmt = request.param
    if fmt == "msgpack":
        try:
            import msgpack  # noqa: F401
        except ImportError:
            pytest.skip("msgpack not installed")
            return None
    return CacheSerializer(format=fmt)


@pytest.fixture
def json_serializer() -> CacheSerializer:
    return CacheSerializer(format="json")


@pytest.fixture
def pickle_serializer() -> CacheSerializer:
    return CacheSerializer(format="pickle")


# ---------------------------------------------------------------------------
# Round-trip tests
# ---------------------------------------------------------------------------


class TestCacheSerializerBasic:
    """Basic values round-trip through all serializer formats."""

    @pytest.mark.parametrize("value", SIMPLE_VALUES)
    def test_simple(self, serializer, value):
        data = serializer.serialize(value)
        restored = serializer.deserialize(data)
        assert restored == value
        assert type(restored) is type(value)

    def test_list_of_strings(self, serializer):
        value = ["a" * 100] * 1000
        data = serializer.serialize(value)
        restored = serializer.deserialize(data)
        assert restored == value
        assert len(restored) == 1000


class TestCacheSerializerComplex:
    """Complex nested values round-trip."""

    @pytest.mark.parametrize("value", COMPLEX_VALUES)
    def test_complex(self, serializer, value):
        data = serializer.serialize(value)
        restored = serializer.deserialize(data)
        assert restored == value

    def test_large_dict(self, serializer):
        value = {f"key_{i}": f"value_{i}" for i in range(5000)}
        data = serializer.serialize(value)
        restored = serializer.deserialize(data)
        assert restored == value
        assert len(restored) == 5000


class TestCacheSerializerExtended:
    """Extended types (datetime, Enum, bytes, etc.) through JSON (and msgpack)."""

    def _roundtrip_json(self, value):
        ser = CacheSerializer(format="json")
        data = ser.serialize(value)
        return ser.deserialize(data)

    def test_datetime(self):
        v = datetime(2026, 6, 2, 14, 30, 0, 123456)
        restored = self._roundtrip_json(v)
        assert isinstance(restored, dict)
        assert restored["__type__"] == "datetime"
        assert restored["value"] == v.isoformat()

    def test_date(self):
        v = date(2026, 6, 2)
        restored = self._roundtrip_json(v)
        assert isinstance(restored, dict)
        assert restored["__type__"] == "datetime"
        assert restored["value"] == v.isoformat()

    def test_time(self):
        v = time(14, 30, 0, 123456)
        restored = self._roundtrip_json(v)
        assert isinstance(restored, dict)
        assert restored["__type__"] == "time"
        assert restored["value"] == v.isoformat()

    def test_timedelta(self):
        v = timedelta(days=7, hours=3, minutes=15)
        restored = self._roundtrip_json(v)
        assert isinstance(restored, dict)
        assert restored["__type__"] == "timedelta"
        assert isinstance(restored["value"], float)
        assert abs(restored["value"] - v.total_seconds()) < FLOAT_EPS

    def test_enum(self):
        v = Color.RED
        restored = self._roundtrip_json(v)
        assert isinstance(restored, dict)
        assert restored["__type__"] == "enum"
        assert restored["value"] == "RED"

    def test_bytes(self):
        v = bytes([0x00, 0xFF, 0xAB, 0xCD])
        restored = self._roundtrip_json(v)
        assert isinstance(restored, dict)
        assert restored["__type__"] == "bytes"
        assert bytes.fromhex(restored["value"]) == v

    def test_set(self):
        v = {1, 2, 3, 4, 5}
        restored = self._roundtrip_json(v)
        assert isinstance(restored, dict)
        assert restored["__type__"] == "set"
        assert set(restored["value"]) == v

    def test_complex_number(self):
        v = complex(3, 4)
        restored = self._roundtrip_json(v)
        assert isinstance(restored, dict)
        assert restored["__type__"] == "complex"
        assert restored["value"] == [3.0, 4.0]

    def test_range(self):
        v = range(0, 10, 2)
        restored = self._roundtrip_json(v)
        assert isinstance(restored, dict)
        assert restored["__type__"] == "range"
        assert restored["value"] == [0, 10, 2]


class TestCacheSerializerMsgpackExtended:
    """Extended types through msgpack (native support for bytes, etc.)."""

    @pytest.fixture
    def msgpack_ser(self):
        try:
            import msgpack  # noqa: F401
        except ImportError:
            pytest.skip("msgpack not installed")
        return CacheSerializer(format="msgpack")

    def test_bytes(self, msgpack_ser):
        v = bytes([0x00, 0xFF, 0xAB])
        restored = msgpack_ser.deserialize(msgpack_ser.serialize(v))
        assert restored == v

    def test_datetime(self, msgpack_ser):
        v = datetime(2026, 6, 2, 14, 30, 0)
        restored = msgpack_ser.deserialize(msgpack_ser.serialize(v))
        # msgpack does not preserve datetime natively — it's treated as string
        assert isinstance(restored, str)

    def test_set(self, msgpack_ser):
        v = {1, 2, 3}
        data = msgpack_ser.serialize(v)
        with pytest.raises(TypeError):
            msgpack_ser.deserialize(data)

    def test_enum(self, msgpack_ser):
        v = Color.GREEN
        data = msgpack_ser.serialize(v)
        with pytest.raises(TypeError):
            msgpack_ser.deserialize(data)


class TestCacheSerializerLargeContent:
    """Large content round-trip using testsuite sample files."""

    SAMPLE_FILES = [
        "jsonplaceholder_posts.json",
        "python_home.html",
        "plant_catalog.xml",
        "unicode_multilingual.html",
        "unicode_multilingual.json",
        "unicode_multilingual.xml",
    ]

    @pytest.mark.parametrize("filename", SAMPLE_FILES)
    def test_large_content_json(self, json_serializer, filename):
        content = _load_sample(filename)
        data = json_serializer.serialize(content)
        restored = json_serializer.deserialize(data)
        assert restored == content
        assert isinstance(restored, str)
        assert len(restored) == len(content)

    @pytest.mark.parametrize("filename", SAMPLE_FILES)
    def test_large_content_pickle(self, pickle_serializer, filename):
        content = _load_sample(filename)
        data = pickle_serializer.serialize(content)
        restored = pickle_serializer.deserialize(data)
        assert restored == content

    def test_json_placeholder_structure(self, json_serializer):
        """Load a JSON file as dict, serialize and restore via JSON serializer."""
        content = _load_sample("jsonplaceholder_posts.json")
        parsed = json.loads(content)
        data = json_serializer.serialize(parsed)
        restored = json_serializer.deserialize(data)
        assert restored == parsed
        assert len(restored) == len(parsed)
        assert isinstance(restored, list)

    def test_multilingual_json_structure(self, json_serializer):
        """Multilingual JSON with Unicode content."""
        content = _load_sample("unicode_multilingual.json")
        parsed = json.loads(content)
        data = json_serializer.serialize(parsed)
        restored = json_serializer.deserialize(data)
        assert restored == parsed


class TestCacheSerializerEdgeCases:
    """Edge cases and error handling."""

    def test_empty_string(self, serializer):
        v = ""
        data = serializer.serialize(v)
        assert serializer.deserialize(data) == v

    def test_very_long_string(self, serializer):
        v = "x" * 100_000
        data = serializer.serialize(v)
        restored = serializer.deserialize(data)
        assert restored == v
        assert len(restored) == 100_000

    def test_none_value(self, serializer):
        data = serializer.serialize(None)
        assert serializer.deserialize(data) is None

    def test_boolean_values(self, serializer):
        for v in [True, False]:
            data = serializer.serialize(v)
            restored = serializer.deserialize(data)
            assert restored is v or restored == v
            assert isinstance(restored, bool)

    def test_integer_edge_cases(self, serializer):
        for v in [0, 1, -1, 2**31 - 1, -(2**31), 2**63 - 1, -(2**63)]:
            data = serializer.serialize(v)
            restored = serializer.deserialize(data)
            assert restored == v
            assert type(restored) is type(v)

    def test_float_edge_cases(self, serializer):
        for v in [0.0, -0.0, 3.141592653589793, float("inf"), float("-inf"), 1.7976931348623157e308, 5e-324]:
            if math.isnan(v):
                continue  # NaN comparison is tricky
            data = serializer.serialize(v)
            restored = serializer.deserialize(data)
            if isinstance(restored, float) and math.isnan(v):
                assert math.isnan(restored)
            else:
                assert restored == v

    def test_deeply_nested_structure(self, serializer):
        v = {"level1": {"level2": {"level3": {"level4": {"level5": "deep"}}}}}
        data = serializer.serialize(v)
        restored = serializer.deserialize(data)
        assert restored == v

    def test_large_list_of_small_dicts(self, serializer):
        v = [{"id": i, "val": str(i)} for i in range(10000)]
        data = serializer.serialize(v)
        restored = serializer.deserialize(data)
        assert restored == v
        assert len(restored) == 10000


class TestCacheSerializerInvalidInput:
    """Error handling for invalid/unsupported inputs."""

    def test_unknown_format(self):
        with pytest.raises(ValueError, match="Unknown serializer format"):
            CacheSerializer(format="xml")

    def test_msgpack_not_installed(self):

        # Simulate missing msgpack by checking if we can bypass it
        try:
            import msgpack  # noqa: F401

            pytest.skip("msgpack is installed, can't test missing case")
        except ImportError:
            with pytest.raises(ImportError, match="msgpack"):
                CacheSerializer(format="msgpack")

    def test_unserializable_object_json(self):
        """JSON serializer can't handle arbitrary objects."""
        ser = CacheSerializer(format="json")

        class Unserializable:
            pass

        with pytest.raises(TypeError):
            ser.serialize(Unserializable())

    def test_circular_reference_json(self):
        """JSON serializer should raise on circular refs."""
        ser = CacheSerializer(format="json")
        v: Dict[str, Any] = {"key": None}
        v["key"] = v
        with pytest.raises((ValueError, TypeError)):
            ser.serialize(v)

    def test_pickle_serializer_warning(self):
        with pytest.warns(UserWarning, match="unsafe"):
            CacheSerializer(format="pickle")


class TestCacheSerializerCrossFormat:
    """Data serialized in one format should not be expected to
    deserialize correctly in another (negative testing)."""

    def test_json_data_cannot_be_read_by_pickle(self):
        ser_json = CacheSerializer(format="json")
        data = ser_json.serialize("hello")
        ser_pickle = CacheSerializer(format="pickle")
        with pytest.raises(Exception):  # noqa: B017
            ser_pickle.deserialize(data)

    def test_pickle_data_cannot_be_read_by_json(self):
        ser_pickle = CacheSerializer(format="pickle")
        data = ser_pickle.serialize("hello")
        ser_json = CacheSerializer(format="json")
        with pytest.raises(Exception):  # noqa: B017
            ser_json.deserialize(data)


class TestCacheSerializerFormatProperty:
    """Serializer exposes its format."""

    def test_format_property(self):
        assert CacheSerializer(format="json").format == "json"
        assert CacheSerializer(format="pickle").format == "pickle"
        assert CacheSerializer().format == "json"

    def test_case_insensitive(self):
        assert CacheSerializer(format="JSON").format == "json"
        assert CacheSerializer(format="Pickle").format == "pickle"
