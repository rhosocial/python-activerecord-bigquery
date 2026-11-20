# tests/rhosocial/activerecord_bigquery_test/feature/query/relation/test_instance_cache.py
"""
Granular tests for InstanceCache functionality.

These tests cover the instance-level caching mechanism specific to python-activerecord,
which is distinct from the RelationCache (class-level cache).
"""

import time

from pydantic import BaseModel

from rhosocial.activerecord.relation.cache import (
    CacheConfig,
    InstanceCache,
    CacheEntry,
)


class TestInstanceCache:
    """Tests for the InstanceCache functionality."""

    def test_get_cache_attr_name(self):
        """Test cache attribute name generation."""
        attr_name = InstanceCache.get_cache_attr_name("posts")
        assert attr_name == "_relation_cache_posts"

        attr_name = InstanceCache.get_cache_attr_name("user")
        assert attr_name == "_relation_cache_user"

    def test_get_instance_cache_creates_cache(self):
        """Test that get_instance_cache creates cache dict if not exists."""

        class TestModel(BaseModel):
            id: int

        instance = TestModel(id=1)

        cache = InstanceCache.get_instance_cache(instance, "test_relation")
        assert isinstance(cache, dict)
        assert "entry" not in cache

    def test_get_instance_cache_returns_existing(self):
        """Test that get_instance_cache returns existing cache."""

        class TestModel(BaseModel):
            id: int

        instance = TestModel(id=1)

        cache1 = InstanceCache.get_instance_cache(instance, "test_relation")
        cache1["custom_key"] = "custom_value"

        cache2 = InstanceCache.get_instance_cache(instance, "test_relation")
        assert cache2["custom_key"] == "custom_value"

    def test_instance_cache_isolation_between_relations(self):
        """Test that different relations have isolated caches."""

        class TestModel(BaseModel):
            id: int

        instance = TestModel(id=1)

        cache1 = InstanceCache.get_instance_cache(instance, "relation_a")
        cache1["entry"] = CacheEntry("value_a")

        cache2 = InstanceCache.get_instance_cache(instance, "relation_b")
        cache2["entry"] = CacheEntry("value_b")

        result_a = InstanceCache.get(instance, "relation_a", CacheConfig())
        result_b = InstanceCache.get(instance, "relation_b", CacheConfig())

        assert result_a == "value_a"
        assert result_b == "value_b"

    def test_instance_cache_isolation_between_instances(self):
        """Test that different instances have isolated caches."""

        class TestModel(BaseModel):
            id: int

        instance1 = TestModel(id=1)
        instance2 = TestModel(id=2)

        InstanceCache.set(instance1, "test_relation", "value1", CacheConfig())
        InstanceCache.set(instance2, "test_relation", "value2", CacheConfig())

        result1 = InstanceCache.get(instance1, "test_relation", CacheConfig())
        result2 = InstanceCache.get(instance2, "test_relation", CacheConfig())

        assert result1 == "value1"
        assert result2 == "value2"

    def test_instance_cache_set_and_get(self):
        """Test basic set and get operations."""

        class TestModel(BaseModel):
            id: int

        instance = TestModel(id=1)
        config = CacheConfig(enabled=True)

        InstanceCache.set(instance, "test_relation", "test_value", config)

        result = InstanceCache.get(instance, "test_relation", config)
        assert result == "test_value"

    def test_instance_cache_disabled(self):
        """Test that caching is disabled when config.enabled is False."""

        class TestModel(BaseModel):
            id: int

        instance = TestModel(id=1)
        config = CacheConfig(enabled=False)

        InstanceCache.set(instance, "test_relation", "test_value", config)

        result = InstanceCache.get(instance, "test_relation", config)
        assert result is None

    def test_instance_cache_get_no_entry(self):
        """Test get returns None when no entry exists."""

        class TestModel(BaseModel):
            id: int

        instance = TestModel(id=1)
        config = CacheConfig()

        result = InstanceCache.get(instance, "nonexistent", config)
        assert result is None

    def test_instance_cache_expiration(self):
        """Test cache entry expiration."""

        class TestModel(BaseModel):
            id: int

        instance = TestModel(id=1)
        config = CacheConfig(ttl=1)

        InstanceCache.set(instance, "test_relation", "test_value", config)

        result = InstanceCache.get(instance, "test_relation", config)
        assert result == "test_value"

        time.sleep(1.1)

        result = InstanceCache.get(instance, "test_relation", config)
        assert result is None

    def test_instance_cache_expiration_disabled(self):
        """Test that entries with no TTL never expire."""

        class TestModel(BaseModel):
            id: int

        instance = TestModel(id=1)
        config = CacheConfig(ttl=None)

        InstanceCache.set(instance, "test_relation", "test_value", config)

        time.sleep(0.5)

        result = InstanceCache.get(instance, "test_relation", config)
        assert result == "test_value"

    def test_instance_cache_delete(self):
        """Test cache entry deletion."""

        class TestModel(BaseModel):
            id: int

        instance = TestModel(id=1)
        config = CacheConfig()

        InstanceCache.set(instance, "test_relation", "test_value", config)
        assert InstanceCache.get(instance, "test_relation", config) == "test_value"

        InstanceCache.delete(instance, "test_relation")

        result = InstanceCache.get(instance, "test_relation", config)
        assert result is None

    def test_instance_cache_delete_nonexistent(self):
        """Test delete on nonexistent entry doesn't raise."""

        class TestModel(BaseModel):
            id: int

        instance = TestModel(id=1)

        InstanceCache.delete(instance, "nonexistent")

    def test_instance_cache_clear(self):
        """Test clearing cache for a specific relation."""

        class TestModel(BaseModel):
            id: int

        instance = TestModel(id=1)
        config = CacheConfig()

        InstanceCache.set(instance, "relation_a", "value_a", config)
        InstanceCache.set(instance, "relation_b", "value_b", config)

        InstanceCache.delete(instance, "relation_a", config)

        result_a = InstanceCache.get(instance, "relation_a", config)
        result_b = InstanceCache.get(instance, "relation_b", config)

        assert result_a is None
        assert result_b == "value_b"

    def test_instance_cache_clear_disabled(self):
        """Test that clear does nothing when caching is disabled."""

        class TestModel(BaseModel):
            id: int

        instance = TestModel(id=1)
        config = CacheConfig(enabled=False)

        InstanceCache.set(instance, "test_relation", "test_value", config)
        InstanceCache.delete(instance, "test_relation", config)

    def test_instance_cache_with_complex_values(self):
        """Test caching complex objects like lists and dicts."""

        class TestModel(BaseModel):
            id: int

        instance = TestModel(id=1)
        config = CacheConfig()

        complex_value = [
            {"id": 1, "name": "Item 1"},
            {"id": 2, "name": "Item 2"},
        ]
        InstanceCache.set(instance, "items", complex_value, config)

        result = InstanceCache.get(instance, "items", config)
        assert result == complex_value

    def test_instance_cache_with_none_value(self):
        """Test caching None values."""

        class TestModel(BaseModel):
            id: int

        instance = TestModel(id=1)
        config = CacheConfig()

        InstanceCache.set(instance, "optional", None, config)

        result = InstanceCache.get(instance, "optional", config)
        assert result is None

    def test_multiple_relations_on_same_instance(self):
        """Test multiple relations with different configs."""

        class TestModel(BaseModel):
            id: int

        instance = TestModel(id=1)

        config_a = CacheConfig(ttl=1)
        config_b = CacheConfig(ttl=None)

        InstanceCache.set(instance, "short_ttl", "value_a", config_a)
        InstanceCache.set(instance, "no_ttl", "value_b", config_b)

        assert InstanceCache.get(instance, "short_ttl", config_a) == "value_a"
        assert InstanceCache.get(instance, "no_ttl", config_b) == "value_b"

        time.sleep(1.1)

        assert InstanceCache.get(instance, "short_ttl", config_a) is None
        assert InstanceCache.get(instance, "no_ttl", config_b) == "value_b"
