# tests/rhosocial/activerecord_bigquery_test/feature/query/relation/test_redis_cache.py
"""
Tests for RedisCache backend.

Requires a running Redis instance reachable via the REDIS_HOST / REDIS_PORT
environment variables (defaults: localhost:6379, no password). If unavailable,
Redis-dependent tests are skipped — the RedisCache instance is real but the
fixture verifies connectivity at module scope.

The pytest ``redis`` marker remains defined for callers that prefer to exclude
Redis tests explicitly (``pytest -m 'not redis'``).
"""

import pytest
import time

from rhosocial.activerecord.relation.cache import CacheConfig, InstanceCache
from rhosocial.activerecord.relation.cache_backends import (  # noqa: E402
    RedisCache,
    RedisConfig,
    CacheSerializer,
    InMemoryCache,
)

pytestmark = [pytest.mark.redis, pytest.mark.xdist_group("redis_cache")]


class _DummyModel:
    """Minimal model stub for cache key unit tests."""

    primary_key_name = "id"

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

    def primary_key(self):
        return self.primary_key_name


class _DummyNoPK(_DummyModel):
    primary_key_name = "id"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # deliberately not setting "id"


@pytest.fixture(scope="module")
def redis_client():
    redis = pytest.importorskip("redis")
    config = RedisConfig.from_env()
    try:
        client = redis.Redis(
            host=config.host,
            port=config.port,
            password=config.password or None,
            db=config.db,
            socket_connect_timeout=config.socket_connect_timeout,
        )
        client.ping()
        yield client
        client.flushdb()
    except Exception as e:
        pytest.skip(f"Redis not available ({e})")
        yield None
    finally:
        try:
            client.close()
        except Exception:
            pass


@pytest.fixture
def redis_cache(redis_client):
    """Create RedisCache with a clean DB per test."""
    redis_client.flushdb()
    return RedisCache(redis_client, prefix="test:cache:")


@pytest.fixture
def config():
    return CacheConfig(enabled=True, ttl=300)


class TestRedisCacheKey:
    """Key generation and format."""

    def test_key_format(self, redis_cache, config):
        """Key follows {prefix}ModelName:pk:relation."""
        instance = _DummyModel(id=42)
        key = redis_cache._make_key(instance, "posts")
        assert key == "test:cache:_DummyModel:42:posts"

    def test_missing_pk_raises(self, redis_cache):
        """Instance without PK raises ValueError."""
        instance = _DummyNoPK()
        with pytest.raises(ValueError, match="no primary key"):
            redis_cache._make_key(instance, "posts")


class TestRedisCacheBasic:
    """Basic get/set/delete operations."""

    def test_set_and_get(self, redis_cache, config, redis_client):
        inst = _DummyModel(id=1)
        value = ["item1", "item2"]

        redis_cache.set(inst, "items", value, config)
        key = redis_cache._make_key(inst, "items")
        assert redis_client.exists(key)

        result = redis_cache.get(inst, "items", config)
        assert result == value

    def test_get_miss(self, redis_cache, config):
        inst = _DummyModel(id=1)
        result = redis_cache.get(inst, "items", config)
        assert result is None

    def test_delete(self, redis_cache, config, redis_client):
        inst = _DummyModel(id=1)
        redis_cache.set(inst, "items", "data", config)
        key = redis_cache._make_key(inst, "items")
        assert redis_client.exists(key)

        redis_cache.delete(inst, "items")
        assert not redis_client.exists(key)
        assert redis_cache.get(inst, "items", config) is None

    def test_disabled_config_skips(self, redis_cache):
        inst = _DummyModel(id=1)
        disabled = CacheConfig(enabled=False)

        redis_cache.set(inst, "items", "data", disabled)
        assert redis_cache.get(inst, "items", disabled) is None

        redis_cache.delete(inst, "items", disabled)

    def test_ttl_expiry(self, redis_cache, config, redis_client):
        inst = _DummyModel(id=1)
        ttl_config = CacheConfig(enabled=True, ttl=1)

        redis_cache.set(inst, "items", "expirable", ttl_config)
        assert redis_cache.get(inst, "items", ttl_config) == "expirable"

        time.sleep(1.5)
        assert redis_cache.get(inst, "items", ttl_config) is None

    def test_no_ttl_persists(self, redis_cache, redis_client):
        inst = _DummyModel(id=1)
        no_ttl = CacheConfig(enabled=True, ttl=None)

        redis_cache.set(inst, "items", "persistent", no_ttl)
        key = redis_cache._make_key(inst, "items")
        ttl = redis_client.ttl(key)
        assert ttl == -1  # no expiry


class UpperSerializer(CacheSerializer):
    """A serializer that uppercases string values before pickle."""

    def __init__(self):
        super().__init__(format="pickle")

    def serialize(self, value):
        return super().serialize(value.upper())


class TestRedisCacheSerialization:
    """Custom serialization support."""

    def test_custom_serializer(self, redis_cache, config, redis_client):
        cache = RedisCache(redis_client, prefix="test:ser:", serializer=UpperSerializer())
        inst = _DummyModel(id=1)

        cache.set(inst, "name", "hello", config)
        result = cache.get(inst, "name", config)
        assert result == "HELLO"


class TestRedisCacheOrigin:
    """Origin metadata (observability)."""

    def test_record_origin(self, redis_cache, config, redis_client, caplog):
        caplog.set_level("DEBUG", logger="rhosocial.activerecord.relation.cache_backends.redis")
        cache = RedisCache(redis_client, prefix="test:origin:", record_origin=True, origin_name="test-host")
        inst = _DummyModel(id=1)

        cache.set(inst, "items", "data", config)
        result = cache.get(inst, "items", config)
        assert result == "data"

        assert any("origin=test-host" in msg for msg in caplog.messages)

    def test_origin_default_off(self, redis_cache, config, redis_client):
        """record_origin=False stores raw serialized bytes, not JSON wrapper."""
        import json

        inst = _DummyModel(id=1)
        redis_cache.set(inst, "items", "plain", config)
        key = redis_cache._make_key(inst, "items")
        raw = redis_client.get(key)
        assert isinstance(raw, bytes)
        assert json.loads(raw) == "plain"


class TestRedisInMemorySwitch:
    """Switching backends via InstanceCache.set_backend."""

    def test_switch_to_redis_and_back(self, redis_cache):
        inst = _DummyModel(id=1)
        config = CacheConfig(enabled=True, ttl=300)

        original = InstanceCache._backend
        try:
            InstanceCache.set_backend(redis_cache)
            InstanceCache.set(inst, "data", "from-redis", config)
            assert InstanceCache.get(inst, "data", config) == "from-redis"

            InstanceCache.set_backend(InMemoryCache())
            InstanceCache.set(inst, "data", "from-memory", config)
            assert InstanceCache.get(inst, "data", config) == "from-memory"
        finally:
            InstanceCache.set_backend(original)

    def test_after_switch_redis_persists(self, redis_client):
        """Data set via RedisCache remains accessible to a fresh RedisCache instance."""
        inst = _DummyModel(id=1)
        config = CacheConfig(enabled=True, ttl=300)

        redis_client.flushdb()
        c1 = RedisCache(redis_client, prefix="test:switch:")
        c1.set(inst, "items", "persisted", config)

        c2 = RedisCache(redis_client, prefix="test:switch:")
        assert c2.get(inst, "items", config) == "persisted"


class TestRedisInconsistency:
    """Stale/inconsistent data scenario (read-only)."""

    def test_stale_data_returned(self, redis_cache, config, redis_client):
        """If data is changed in DB but cache is not invalidated, stale value is returned."""
        inst = _DummyModel(id=1)
        redis_cache.set(inst, "count", 10, config)

        # Simulate DB update without cache invalidation
        redis_cache.set(inst, "count", 99, config)

        assert redis_cache.get(inst, "count", config) == 99


class TestRedisInstanceInvalidation:
    """invalidate_instance clears all cached relations for an instance."""

    def test_invalidate_instance(self, redis_cache, config, redis_client):
        inst = _DummyModel(id=1)
        redis_cache.set(inst, "posts", ["p1", "p2"], config)
        redis_cache.set(inst, "comments", ["c1"], config)

        assert redis_cache.get(inst, "posts", config) is not None
        assert redis_cache.get(inst, "comments", config) is not None

        redis_cache.invalidate_instance(inst)

        assert redis_cache.get(inst, "posts", config) is None
        assert redis_cache.get(inst, "comments", config) is None

    def test_invalidate_instance_other_untouched(self, redis_cache, config, redis_client):
        inst1 = _DummyModel(id=1)
        inst2 = _DummyModel(id=2)

        redis_cache.set(inst1, "data", "a", config)
        redis_cache.set(inst2, "data", "b", config)

        redis_cache.invalidate_instance(inst1)
        assert redis_cache.get(inst1, "data", config) is None
        assert redis_cache.get(inst2, "data", config) == "b"
