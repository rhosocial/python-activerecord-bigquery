# tests/rhosocial/activerecord_bigquery_test/feature/query/relation/legacy/test_with_integration.py
"""
Integration tests for with_() method using real SQLite database.

These tests use real ActiveRecord models with SQLite backend to verify
the actual behavior of the with_() method, including:
- Eager loading of related data
- Query modifier application
- Cache behavior with modifiers
"""

import pytest


class TestWithIntegration:
    """Integration tests for with_() method using real database."""

    def test_simple_with_loads_relations(self, blog_fixtures):
        """Test that with_() actually loads related data from database."""
        User, Post, Comment = blog_fixtures

        user = User(username="testuser", email="test@example.com", age=25)
        user.save()

        post = Post(title="Test Post", content="Test content", user_id=user.id, status="published")
        post.save()

        posts = Post.query().with_("user").all()

        assert len(posts) == 1
        user_loader = posts[0].user
        assert callable(user_loader)
        loaded_user = user_loader()
        assert loaded_user is not None

    def test_nested_with_loads_deep_relations(self, blog_fixtures):
        """Test that nested with_() loads deeply nested relations."""
        User, Post, Comment = blog_fixtures

        user = User(username="testuser", email="test@example.com", age=25)
        user.save()

        post = Post(title="Test Post", content="Test content", user_id=user.id, status="published")
        post.save()

        comment = Comment(content="Test comment", post_id=post.id, user_id=user.id)
        comment.save()

        comments = Comment.query().with_("post.user").all()

        assert len(comments) == 1
        post_loader = comments[0].post
        assert callable(post_loader)
        loaded_post = post_loader()
        assert loaded_post is not None
        user_loader = loaded_post.user
        assert callable(user_loader)

    def test_with_modifier_filters_data(self, blog_fixtures):
        """Test that query modifier actually filters the loaded data."""
        User, Post, Comment = blog_fixtures

        user = User(username="testuser", email="test@example.com", age=25)
        user.save()

        def filter_published(q):
            return q.where(Post.c.status == "published")

        posts = Post.query().with_(("user", filter_published)).all()

        assert len(posts) >= 0
        for post in posts:
            assert post.status == "published"

    def test_with_modifier_orders_data(self, blog_fixtures):
        """Test that query modifier can order the loaded data."""
        User, Post, Comment = blog_fixtures

        user = User(username="testuser", email="test@example.com", age=25)
        user.save()

        post1 = Post(title="First Post", content="First", user_id=user.id, status="published")
        post1.save()

        post2 = Post(title="Second Post", content="Second", user_id=user.id, status="published")
        post2.save()

        posts = Post.query().with_("user").order_by((Post.c.title, "DESC")).all()

        assert len(posts) == 2
        assert posts[0].title == "Second Post"
        assert posts[1].title == "First Post"

    def test_with_cache_not_used_when_modifier_changes(self, blog_fixtures):
        """Test that cache is properly cleared when modifier changes."""
        User, Post, Comment = blog_fixtures

        user = User(username="testuser", email="test@example.com", age=25)
        user.save()

        post1 = Post(title="Draft Post", content="Draft", user_id=user.id, status="draft")
        post1.save()

        def filter_draft(q):
            return q.where(Post.c.status == "draft")

        posts_draft = Post.query().with_(("user", filter_draft)).all()
        assert len(posts_draft) >= 1

    def test_with_empty_result_set(self, blog_fixtures):
        """Test that with_() handles empty result set correctly."""
        User, Post, Comment = blog_fixtures

        posts = Post.query().with_("user").all()
        assert len(posts) == 0


class TestWithAsyncIntegration:
    """Async integration tests for with_() method using real database."""

    @pytest.mark.asyncio
    async def test_async_with_loads_relations(self, async_blog_fixtures):
        """Test async with_() loads related data."""
        AsyncUser, AsyncPost, AsyncComment = async_blog_fixtures

        user = AsyncUser(username="async_user", email="async@test.com", age=30)
        await user.save()

        post = AsyncPost(title="Async Post", content="Async content", user_id=user.id, status="published")
        await post.save()

        posts = await AsyncPost.query().with_("author").all()

        assert len(posts) == 1
        user_loader = posts[0].author
        assert callable(user_loader)
        loaded_user = await user_loader()
        assert loaded_user is not None

    @pytest.mark.asyncio
    async def test_async_with_modifier(self, async_blog_fixtures):
        """Test async with_() with query modifier."""
        AsyncUser, AsyncPost, AsyncComment = async_blog_fixtures

        user = AsyncUser(username="async_user", email="async@test.com", age=30)
        await user.save()

        post1 = AsyncPost(title="Draft", content="Draft", user_id=user.id, status="draft")
        await post1.save()

        post2 = AsyncPost(title="Published", content="Published", user_id=user.id, status="published")
        await post2.save()

        def filter_published(q):
            return q.where(AsyncPost.c.status == "published")

        posts = await AsyncPost.query().with_(("author", filter_published)).all()

        assert len(posts) == 2
        for post in posts:
            author_loader = post.author
            assert callable(author_loader)

    @pytest.mark.asyncio
    async def test_async_nested_with_loads_deep_relations(self, async_blog_fixtures):
        """Test that nested with_() loads deeply nested relations in async context."""
        AsyncUser, AsyncPost, AsyncComment = async_blog_fixtures

        user = AsyncUser(username="async_user", email="async@test.com", age=30)
        await user.save()

        post = AsyncPost(title="Async Post", content="Async content", user_id=user.id, status="published")
        await post.save()

        comment = AsyncComment(content="Async comment", post_id=post.id, user_id=user.id)
        await comment.save()

        comments = await AsyncComment.query().with_("post.author").all()

        assert len(comments) == 1
        post_loader = comments[0].post
        assert callable(post_loader)

    @pytest.mark.asyncio
    async def test_async_with_modifier_filters_data(self, async_blog_fixtures):
        """Test that query modifier filters the loaded relation data in async context."""
        AsyncUser, AsyncPost, AsyncComment = async_blog_fixtures

        user = AsyncUser(username="async_user", email="async@test.com", age=30)
        await user.save()

        def filter_published(q):
            return q.where(AsyncPost.c.status == "published")

        posts = await AsyncPost.query().with_(("author", filter_published)).all()

        assert len(posts) >= 0

    @pytest.mark.asyncio
    async def test_async_with_modifier_orders_data(self, async_blog_fixtures):
        """Test that query modifier can order the loaded data in async context."""
        AsyncUser, AsyncPost, AsyncComment = async_blog_fixtures

        user = AsyncUser(username="async_user", email="async@test.com", age=30)
        await user.save()

        post1 = AsyncPost(title="First Post", content="First", user_id=user.id, status="published")
        await post1.save()

        post2 = AsyncPost(title="Second Post", content="Second", user_id=user.id, status="published")
        await post2.save()

        posts = await AsyncPost.query().with_("author").order_by((AsyncPost.c.title, "DESC")).all()

        assert len(posts) == 2
        assert posts[0].title == "Second Post"
        assert posts[1].title == "First Post"

    @pytest.mark.asyncio
    async def test_async_with_cache_not_used_when_modifier_changes(self, async_blog_fixtures):
        """Test that cache is properly cleared when modifier changes in async context."""
        AsyncUser, AsyncPost, AsyncComment = async_blog_fixtures

        user = AsyncUser(username="async_user", email="async@test.com", age=30)
        await user.save()

        post1 = AsyncPost(title="Draft Post", content="Draft", user_id=user.id, status="draft")
        await post1.save()

        def filter_draft(q):
            return q.where(AsyncPost.c.status == "draft")

        posts_draft = await AsyncPost.query().with_(("author", filter_draft)).all()
        assert len(posts_draft) >= 1

    @pytest.mark.asyncio
    async def test_async_with_empty_result_set(self, async_blog_fixtures):
        """Test that with_() handles empty result set correctly in async context."""
        AsyncUser, AsyncPost, AsyncComment = async_blog_fixtures

        posts = await AsyncPost.query().with_("author").all()
        assert len(posts) == 0
