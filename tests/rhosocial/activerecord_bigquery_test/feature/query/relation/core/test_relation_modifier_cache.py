# tests/rhosocial/activerecord_bigquery_test/feature/query/relation/test_relation_modifier_cache.py
"""
Database-backed relation cache tests using real SQLite with SQL query counting.

Verifies that the instance-level cache (InstanceCache) correctly prevents
redundant SQL queries on repeated relation access, and that cache invalidation
(for delete, TTL expiry, disabled cache, etc.) re-queries the database.
"""

import pytest
import time
from typing import ClassVar, Dict, Any, Tuple

from pydantic import BaseModel

from rhosocial.activerecord.relation.base import RelationManagementMixin
from rhosocial.activerecord.relation.cache import CacheConfig
from rhosocial.activerecord.relation.descriptors import HasMany, BelongsTo


class QueryCounter:
    """Wraps backend fetch methods to count executed SQL queries."""

    def __init__(self, backends: Dict[str, Any]):
        self.count = 0
        self._originals: Dict[str, Tuple] = {}
        for name, backend in backends.items():
            self._originals[name] = (backend.fetch_all, backend.fetch_one)
            backend.fetch_all = self._wrap(backend.fetch_all)
            backend.fetch_one = self._wrap(backend.fetch_one)

    def _wrap(self, original):
        def wrapper(sql, params=None, column_adapters=None, **kwargs):
            self.count += 1
            return original(
                sql,
                params,
                column_adapters=column_adapters,
                **kwargs,
            )

        return wrapper

    def reset(self):
        self.count = 0


@pytest.fixture
def cache_test_env(user_post_comment_classes):
    """Set up test data and wrap backends with a query counter.

    Returns (user_class, post_class, comment_class, user, post, counter).
    """
    user_class, post_class, comment_class = user_post_comment_classes

    backends = {}
    for cls in (user_class, post_class, comment_class):
        try:
            backends[cls.__name__] = cls.backend()
        except Exception:
            pass
    counter = QueryCounter(backends)

    user = user_class(name="Cache User", email="cache@example.com")
    user.save()
    post = post_class(title="Cache Post", body="Content", user_id=user.id)
    post.save()

    counter.reset()
    yield user_class, post_class, comment_class, user, post, counter

    for name, backend in backends.items():
        orig_all, orig_one = counter._originals.get(name, (None, None))
        if orig_all is not None:
            backend.fetch_all = orig_all
        if orig_one is not None:
            backend.fetch_one = orig_one


class TestRelationCacheFirstAccess:
    """First relation access should query the database."""

    def test_first_access_queries_db(self, cache_test_env):
        """First access to a relation executes SQL."""
        _, _, _, user, _, counter = cache_test_env
        results = user.posts()
        assert len(results) == 1
        assert counter.count > 0

    def test_first_access_has_many_empty(self, cache_test_env):
        """HasMany with no related records still executes a query."""
        user_class, _, _, _, _, counter = cache_test_env
        user2 = user_class(name="Empty User", email="empty@example.com")
        user2.save()
        counter.reset()

        results = user2.posts()
        assert results == []
        assert counter.count > 0

    def test_first_access_belongs_to(self, cache_test_env):
        """BelongsTo first access executes SQL."""
        _, _, _, _, post, counter = cache_test_env
        result = post.user()
        assert result is not None
        assert counter.count > 0


class TestRelationCacheSecondAccess:
    """Second (and subsequent) accesses should hit the cache."""

    def test_second_access_has_many_uses_cache(self, cache_test_env):
        """Second HasMany access uses cache (no SQL)."""
        _, _, _, user, _, counter = cache_test_env
        r1 = user.posts()
        q1 = counter.count

        r2 = user.posts()
        assert counter.count == q1
        assert len(r1) == len(r2)

    def test_second_access_belongs_to_uses_cache(self, cache_test_env):
        """Second BelongsTo access uses cache (no SQL)."""
        _, _, _, _, post, counter = cache_test_env
        r1 = post.user()
        q1 = counter.count

        r2 = post.user()
        assert counter.count == q1
        assert r1.id == r2.id

    def test_multiple_accesses_no_extra_queries(self, cache_test_env):
        """Three accesses cause only one SQL query total."""
        _, _, _, user, _, counter = cache_test_env
        user.posts()
        q1 = counter.count

        for _ in range(5):
            user.posts()

        assert counter.count == q1


class TestRelationCacheInvalidation:
    """Cache invalidation scenarios (delete, clear, TTL, disabled)."""

    def test_cache_cleared_on_delete(self, cache_test_env):
        """__delete__ clears cache; next access re-queries."""
        user_class, _, _, user, _, counter = cache_test_env
        user.posts()
        counter.reset()

        desc = user_class.get_relation("posts")
        desc.__delete__(user)

        results = user.posts()
        assert len(results) == 1
        assert counter.count > 0

    def test_clear_relation_cache_method(self, cache_test_env):
        """clear_relation_cache(name) forces a new query."""
        _, _, _, user, _, counter = cache_test_env
        user.posts()
        counter.reset()

        user.clear_relation_cache("posts")

        results = user.posts()
        assert len(results) == 1
        assert counter.count > 0

    def test_clear_all_relations_cache(self, cache_test_env):
        """clear_relation_cache() without args clears all caches."""
        _, _, _, user, _, counter = cache_test_env
        user.posts()
        counter.reset()

        user.clear_relation_cache()

        results = user.posts()
        assert len(results) == 1
        assert counter.count > 0

    def test_cache_with_disabled_config(self, cache_test_env):
        """disabled cache executes a query on every access."""
        user_class, _, _, user, _, counter = cache_test_env

        desc = user_class.get_relation("posts")
        orig_config = desc._cache_config
        desc._cache_config = CacheConfig(enabled=False)

        try:
            user.posts()
            counter.reset()

            user.posts()
            q1 = counter.count

            user.posts()
            assert counter.count > q1
        finally:
            desc._cache_config = orig_config

    def test_cache_with_expired_ttl(self, cache_test_env):
        """Expired TTL causes a new query."""
        user_class, _, _, user, _, counter = cache_test_env

        desc = user_class.get_relation("posts")
        orig_config = desc._cache_config
        desc._cache_config = CacheConfig(ttl=1)

        try:
            user.posts()
            counter.reset()

            time.sleep(1.1)

            results = user.posts()
            assert len(results) == 1
            assert counter.count > 0
        finally:
            desc._cache_config = orig_config


class TestRelationCacheIsolation:
    """Cache isolation between instances and relations."""

    def test_cache_isolation_between_instances(self, cache_test_env):
        """Different instances have independent caches."""
        user_class, post_class, _, user, _, counter = cache_test_env

        user2 = user_class(name="Second User", email="u2@example.com")
        user2.save()
        post2 = post_class(title="Second Post", body="Content", user_id=user2.id)
        post2.save()

        user.posts()
        user2.posts()
        counter.reset()

        r1 = user.posts()
        r2 = user2.posts()
        assert counter.count == 0
        assert len(r1) == 1
        assert len(r2) == 1

    def test_different_relations_independent_cache(self, cache_test_env):
        """Different relation types on the same instance cache independently."""
        _, _, _, user, post, counter = cache_test_env

        _ = post.user()
        counter.reset()

        post.user()
        assert counter.count == 0  # BelongsTo cached

        _ = user.posts()
        assert counter.count > 0  # HasMany not cached on post instance


class TestRelationCacheBulk:
    """Bulk / edge-case scenarios."""

    def test_reload_same_data_idempotent(self, cache_test_env):
        """Adding more related data after caching is not visible until cache cleared."""
        user_class, post_class, _, user, _, counter = cache_test_env

        user.posts()
        counter.reset()

        extra = post_class(title="Extra Post", body="Extra", user_id=user.id)
        extra.save()

        results = user.posts()
        assert len(results) == 1
        assert counter.count == 0  # Cache returns stale data

        user.clear_relation_cache("posts")
        counter.reset()

        results = user.posts()
        assert len(results) == 2
        assert counter.count > 0


# ── Non-DB protocol tests (kept from original mock-based file) ─────


class TestRelationDescriptorProtocol:
    """Tests for relation descriptor protocol methods."""

    def test_get_descriptor_from_class(self):
        """Test accessing descriptor from class returns descriptor itself."""

        class _Author(RelationManagementMixin, BaseModel):
            id: int
            books: ClassVar[HasMany["_Book"]] = HasMany(foreign_key="author_id")

        class _Book(RelationManagementMixin, BaseModel):
            id: int
            author_id: int
            author: ClassVar[BelongsTo["_Author"]] = BelongsTo(foreign_key="author_id")

        relation = _Author.get_relation("books")
        assert isinstance(relation, HasMany)
        assert relation.foreign_key == "author_id"

    def test_get_descriptor_from_instance_returns_method(self):
        """Test accessing descriptor from instance returns bound method."""

        class _Author(RelationManagementMixin, BaseModel):
            id: int
            books: ClassVar[HasMany["_Book"]] = HasMany(foreign_key="author_id")

        class _Book(RelationManagementMixin, BaseModel):
            id: int
            author_id: int

        author = _Author(id=1)
        books_relation = author.books
        assert callable(books_relation)

    def test_set_name_callback(self):
        """Test that __set_name__ is called on descriptor assignment."""

        class _OtherItem(RelationManagementMixin, BaseModel):
            id: int
            test_id: int

        class _TestModel(RelationManagementMixin, BaseModel):
            id: int
            items: ClassVar[HasMany["_OtherItem"]] = HasMany(foreign_key="test_id", inverse_of="test")

        relation = _TestModel.get_relation("items")
        assert relation.name == "items"
        assert relation._owner == _TestModel

    def test_query_method_created(self):
        """Test that query method is created for relation."""

        class _Author(RelationManagementMixin, BaseModel):
            id: int
            books: ClassVar[HasMany["_Book"]] = HasMany(foreign_key="author_id")

        class _Book(RelationManagementMixin, BaseModel):
            id: int
            author_id: int

        assert hasattr(_Author, "books_query")
        assert callable(_Author.books_query)
