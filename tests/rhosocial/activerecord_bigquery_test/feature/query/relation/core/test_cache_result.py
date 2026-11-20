# tests/rhosocial/activerecord_bigquery_test/feature/query/relation/test_cache_result.py
"""
Tests for CacheResult dataclass and InstanceCache.get_with_meta().

Cache stampede protection and proactive refresh are intentionally
excluded from the framework.  These tests verify the metadata-building
blocks that application code uses to implement its own strategy.
"""


from pydantic import BaseModel

from rhosocial.activerecord.relation.cache import (  # noqa: E402
    CacheConfig,
    CacheResult,
    InstanceCache,
)


class TestCacheResult:
    """CacheResult dataclass construction and defaults."""

    def test_basic(self):
        r = CacheResult(value="hello", age=10.0, origin="box-a", ttl=300)
        assert r.value == "hello"
        assert r.age == 10.0
        assert r.origin == "box-a"
        assert r.ttl == 300

    def test_defaults(self):
        r = CacheResult(value=42)
        assert r.age == 0.0
        assert r.origin is None
        assert r.ttl is None

    def test_various_types(self):
        r = CacheResult(value=[1, 2, 3])
        assert r.value == [1, 2, 3]

        r = CacheResult(value={"key": "val"})
        assert r.value == {"key": "val"}

        r = CacheResult(value=None)
        assert r.value is None


class TestGetWithMeta:
    """InstanceCache.get_with_meta() returns CacheResult with metadata."""

    class _Model(BaseModel):
        id: int

    def test_hit(self):
        inst = self._Model(id=1)
        cfg = CacheConfig(ttl=300)
        InstanceCache.set(inst, "posts", ["p1", "p2"], cfg)
        r = InstanceCache.get_with_meta(inst, "posts", cfg)
        assert r is not None
        assert r.value == ["p1", "p2"]
        assert r.ttl == 300
        assert r.origin is None  # InMemoryCache has no origin
        assert r.age == 0.0

    def test_miss(self):
        inst = self._Model(id=2)
        cfg = CacheConfig(ttl=300)
        r = InstanceCache.get_with_meta(inst, "nonexistent", cfg)
        assert r is None

    def test_disabled(self):
        inst = self._Model(id=3)
        cfg = CacheConfig(enabled=False)
        InstanceCache.set(inst, "posts", ["p1"], CacheConfig())
        r = InstanceCache.get_with_meta(inst, "posts", cfg)
        assert r is None

    def test_ttl_none(self):
        inst = self._Model(id=4)
        cfg = CacheConfig(ttl=None)
        InstanceCache.set(inst, "data", "xyz", cfg)
        r = InstanceCache.get_with_meta(inst, "data", cfg)
        assert r is not None
        assert r.value == "xyz"
        assert r.ttl is None

    def test_origin_reflects_backend(self):
        """get_with_meta origin matches the active backend origin."""
        orig_backend = InstanceCache._backend
        try:
            from rhosocial.activerecord.relation.cache_backends import InMemoryCache

            class CustomOrigin(InMemoryCache):
                @property
                def origin(self):
                    return "custom-node"

            InstanceCache.set_backend(CustomOrigin())

            inst = self._Model(id=5)
            cfg = CacheConfig(ttl=60)
            InstanceCache.set(inst, "rel", "val", cfg)
            r = InstanceCache.get_with_meta(inst, "rel", cfg)
            assert r is not None
            assert r.origin == "custom-node"
        finally:
            InstanceCache.set_backend(orig_backend)
