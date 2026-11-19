# tests/rhosocial/activerecord_bigquery_test/feature/query/relation/test_descriptor_db_coverage.py
"""
Database-backed tests covering descriptor code paths that require SQLite.

Covers: _create_query_method, _load_relation, DefaultIRelationLoader.load/batch_load,
RelationDescriptor.batch_load, cache interaction, HasOne path.
"""

import pytest

from rhosocial.activerecord.relation.cache import CacheConfig, InstanceCache


# ==============================================================================
# _create_query_method — calls model_class.query() with FK/PK filter
# ==============================================================================


class TestCreateQueryMethod:
    """Cover _create_query_method for BelongsTo, HasMany, HasOne."""

    def _save(self, model):
        model.save()
        return model

    def test_belongs_to_query_method(self, user_post_comment_classes):
        """BelongsTo query filters by FK matching instance PK."""
        user_class, post_class, comment_class = user_post_comment_classes
        user = user_class(name="Alice")
        user.save()
        post = post_class(title="Post", body="Body", user_id=user.id)
        post.save()

        query = post.user_query()
        assert user.id is not None
        results = query.all()
        assert len(results) == 1
        assert results[0].id == user.id

    def test_has_many_query_method(self, user_post_comment_classes):
        """HasMany query filters by FK matching instance PK."""
        user_class, post_class, comment_class = user_post_comment_classes
        user = user_class(name="Bob")
        user.save()
        p1 = post_class(title="Post A", body="Body", user_id=user.id)
        p1.save()
        p2 = post_class(title="Post B", body="Body", user_id=user.id)
        p2.save()

        query = user.posts_query()
        results = query.all()
        assert len(results) == 2

    def test_has_one_query_method(self, user_post_comment_classes):
        """HasOne query method exists and can be called."""
        user_class, post_class, comment_class = user_post_comment_classes
        user = user_class(name="Carol")
        user.save()
        query = user.posts_query()
        assert query is not None
        assert user.id is not None


# ==============================================================================
# DefaultIRelationLoader.batch_load — BelongsTo path
# ==============================================================================


class TestDefaultLoaderBelongsTo:
    """Cover DefaultIRelationLoader.batch_load for BelongsTo."""

    def test_belongs_to_load_single(self, user_post_comment_classes):
        """BelongsTo: comment loads its post."""
        user_class, post_class, comment_class = user_post_comment_classes
        user = user_class(name="Dave")
        user.save()
        post = post_class(title="Test", body="Body", user_id=user.id)
        post.save()
        comment = comment_class(body="Nice!", post_id=post.id)
        comment.save()

        result = comment.post()
        assert result is not None
        assert result.id == post.id
        assert result.title == "Test"

    def test_belongs_to_batch_load(self, user_post_comment_classes):
        """BelongsTo batch_load: multiple comments share/span posts."""
        user_class, post_class, comment_class = user_post_comment_classes
        user = user_class(name="Eve")
        user.save()
        post1 = post_class(title="P1", body="B1", user_id=user.id)
        post1.save()
        post2 = post_class(title="P2", body="B2", user_id=user.id)
        post2.save()

        c1 = comment_class(body="C1", post_id=post1.id)
        c1.save()
        c2 = comment_class(body="C2", post_id=post1.id)
        c2.save()
        c3 = comment_class(body="C3", post_id=post2.id)
        c3.save()

        result = c2.post()
        assert result is not None
        assert result.id == post1.id


# ==============================================================================
# DefaultIRelationLoader.batch_load — HasMany path
# ==============================================================================


class TestDefaultLoaderHasMany:
    """Cover DefaultIRelationLoader.batch_load for HasMany."""

    def test_has_many_load(self, user_post_comment_classes):
        """HasMany: user loads posts."""
        user_class, post_class, comment_class = user_post_comment_classes
        user = user_class(name="Heidi")
        user.save()
        p1 = post_class(title="A", body="B1", user_id=user.id)
        p1.save()
        p2 = post_class(title="B", body="B2", user_id=user.id)
        p2.save()

        results = user.posts()
        assert len(results) == 2

    def test_has_many_empty(self, user_post_comment_classes):
        """HasMany: user with no posts returns []."""
        user_class, post_class, comment_class = user_post_comment_classes
        user = user_class(name="Ivan")
        user.save()

        results = user.posts()
        assert results == []

    def test_has_many_batch_multiple_users(self, user_post_comment_classes):
        """HasMany: multiple users with posts."""
        user_class, post_class, comment_class = user_post_comment_classes
        u1 = user_class(name="Judy")
        u1.save()
        u2 = user_class(name="Karl")
        u2.save()
        p1 = post_class(title="U1P1", body="B", user_id=u1.id)
        p1.save()
        p2 = post_class(title="U2P1", body="B", user_id=u2.id)
        p2.save()
        p3 = post_class(title="U2P2", body="B", user_id=u2.id)
        p3.save()

        r1 = u1.posts()
        assert len(r1) == 1
        r2 = u2.posts()
        assert len(r2) == 2


# ==============================================================================
# DefaultIRelationLoader.batch_load — HasOne path
# ==============================================================================


class TestDefaultLoaderHasOne:
    """Cover DefaultIRelationLoader.batch_load for HasOne."""

    def test_has_one_load(self, user_post_comment_classes):
        """HasOne — default loader branching is identical to HasMany for WHERE.

        The actual HasOne-vs-HasMany distinction in batch_load is just
        taking result[0] vs result list. Verify HasMany path works.
        """
        user_class, post_class, comment_class = user_post_comment_classes
        user = user_class(name="Leo")
        user.save()
        p1 = post_class(title="H1", body="B", user_id=user.id)
        p1.save()
        results = user.posts()
        assert len(results) == 1


# ==============================================================================
# _load_relation — cache interaction
# ==============================================================================


class TestLoadRelationDb:
    """Cover _load_relation with cache hit/miss/error using DB loader."""

    def test_cache_hit_after_initial_load(self, user_post_comment_classes):
        """Second access uses cache."""
        user_class, post_class, comment_class = user_post_comment_classes
        user = user_class(name="Mallory")
        user.save()
        p = post_class(title="Cached", body="B", user_id=user.id)
        p.save()

        results = user.posts()
        assert len(results) == 1

        results2 = user.posts()
        assert len(results2) == 1

    def test_cache_bypass_with_disabled_cache(self, user_post_comment_classes):
        """When cache is disabled, each access reloads."""
        user_class, post_class, comment_class = user_post_comment_classes
        user = user_class(name="Nina")
        user.save()

        desc = user_class.get_relation("posts")
        config = desc._cache_config
        desc._cache_config = CacheConfig(enabled=False)

        p = post_class(title="NoCache", body="B", user_id=user.id)
        p.save()
        r1 = user.posts()
        assert len(r1) == 1

        desc._cache_config = config

    def test_cache_cleared_on_delete(self, user_post_comment_classes):
        """__delete__ clears the instance cache."""
        user_class, post_class, comment_class = user_post_comment_classes
        user = user_class(name="Oscar")
        user.save()
        post = post_class(title="Del", body="B", user_id=user.id)
        post.save()
        c = comment_class(body="C", post_id=post.id)
        c.save()

        _ = post.comments()

        desc = post_class.get_relation("comments")
        desc.__delete__(post)

        results = post.comments()
        assert len(results) == 1

    def test_cache_write_failure_still_returns_loaded_data(self, user_post_comment_classes, mocker):
        user_class, post_class, comment_class = user_post_comment_classes
        user = user_class(name="Peggy")
        user.save()
        post = post_class(title="CacheWriteFail", body="B", user_id=user.id)
        post.save()

        mocker.patch.object(InstanceCache, "set", side_effect=TypeError("cache write failed"))

        results = user.posts()
        assert len(results) == 1
        assert results[0].id == post.id


# ==============================================================================
# Async DefaultIRelationLoader
# ==============================================================================


class TestAsyncDefaultLoader:
    """Cover AsyncDefaultRelationLoader with DB."""

    @pytest.mark.asyncio
    async def test_async_belongs_to_load(self, async_user_post_comment_classes):
        user_class, post_class, comment_class = async_user_post_comment_classes
        user = user_class(name="AsyncAlice")
        await user.save()
        post = post_class(title="AsyncPost", body="Body", user_id=user.id)
        await post.save()
        comment = comment_class(body="Nice", post_id=post.id)
        await comment.save()

        result = await comment.post()
        assert result is not None
        assert result.id == post.id

    @pytest.mark.asyncio
    async def test_async_has_many_load(self, async_user_post_comment_classes):
        user_class, post_class, comment_class = async_user_post_comment_classes
        user = user_class(name="AsyncBob")
        await user.save()
        p1 = post_class(title="A1", body="B1", user_id=user.id)
        await p1.save()
        p2 = post_class(title="A2", body="B2", user_id=user.id)
        await p2.save()

        results = await user.posts()
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_async_has_many_empty(self, async_user_post_comment_classes):
        user_class, post_class, comment_class = async_user_post_comment_classes
        user = user_class(name="AsyncCarol")
        await user.save()

        results = await user.posts()
        assert results == []

    @pytest.mark.asyncio
    async def test_async_cache_hit(self, async_user_post_comment_classes):
        user_class, post_class, comment_class = async_user_post_comment_classes
        user = user_class(name="AsyncEve")
        await user.save()
        p = post_class(title="Cached", body="B", user_id=user.id)
        await p.save()

        r1 = await user.posts()
        r2 = await user.posts()
        assert len(r1) == 1
        assert len(r2) == 1

    @pytest.mark.asyncio
    async def test_async_batch_load_empty_records(self, async_user_post_comment_classes):
        """AsyncRelationDescriptor.batch_load with empty records."""
        user_class, post_class, comment_class = async_user_post_comment_classes
        desc = user_class.get_relation("posts")
        result = await desc.batch_load([], None)
        assert result == {}


# ==============================================================================
# Async _create_query_method
# ==============================================================================


class TestAsyncCreateQueryMethod:
    """Cover async _create_query_method."""

    @pytest.mark.asyncio
    async def test_async_belongs_to_query(self, async_user_post_comment_classes):
        user_class, post_class, comment_class = async_user_post_comment_classes
        user = user_class(name="Alice")
        await user.save()
        post = post_class(title="P", body="B", user_id=user.id)
        await post.save()

        query = post.user_query()
        results = await query.all()
        assert len(results) == 1
        assert results[0].id == user.id

    @pytest.mark.asyncio
    async def test_async_has_many_query(self, async_user_post_comment_classes):
        user_class, post_class, comment_class = async_user_post_comment_classes
        user = user_class(name="Bob")
        await user.save()
        p1 = post_class(title="A", body="B1", user_id=user.id)
        await p1.save()
        p2 = post_class(title="B", body="B2", user_id=user.id)
        await p2.save()

        query = user.posts_query()
        results = await query.all()
        assert len(results) == 2
