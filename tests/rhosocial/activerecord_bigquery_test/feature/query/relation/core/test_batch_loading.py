# tests/rhosocial/activerecord_bigquery_test/feature/query/relation/test_batch_loading.py
"""
Tests for batch loading behavior in relations.

These tests cover the batch loading functionality which is critical for
avoiding N+1 query problems in python-activerecord.
"""

import pytest
from typing import ClassVar, Any, Optional, List, Dict

from pydantic import BaseModel

from rhosocial.activerecord.relation.cache import CacheConfig, InstanceCache
from rhosocial.activerecord.relation.base import RelationManagementMixin
from rhosocial.activerecord.relation.descriptors import (
    HasMany,
    BelongsTo,
    HasOne,
)
from rhosocial.activerecord.relation.interfaces import IRelationLoader


class AuthorForBatch(RelationManagementMixin, BaseModel):
    id: int
    name: str
    books: ClassVar[HasMany["BookForBatch"]] = HasMany(foreign_key="author_id", inverse_of="author")


class BookForBatch(RelationManagementMixin, BaseModel):
    id: int
    title: str
    author_id: int
    author: ClassVar[BelongsTo["AuthorForBatch"]] = BelongsTo(foreign_key="author_id", inverse_of="books")


class RecordingBatchLoader(IRelationLoader):
    """Loader that records what instances were loaded."""

    def __init__(self, return_value=None):
        self.loaded_instances: List[Any] = []
        self.batch_loaded_instances: List[List[Any]] = []
        self.return_value = return_value or [{"id": 1, "title": "Test Book"}]

    def load(self, instance: Any) -> Optional[List[Any]]:
        self.loaded_instances.append(instance)
        return self.return_value

    def batch_load(self, instances: List[Any], base_query: Any) -> Dict[int, Any]:
        self.batch_loaded_instances.append(instances)
        return {id(inst): self.return_value for inst in instances}


class TestBatchLoading:
    """Tests for relation batch loading functionality."""

    @pytest.fixture
    def loader(self):
        return RecordingBatchLoader()

    def test_batch_load_called_with_instances(self):
        """Test that batch_load receives the correct instances."""
        loader = RecordingBatchLoader()
        relation = AuthorForBatch.get_relation("books")
        relation._loader = loader

        author1 = AuthorForBatch(id=1, name="Author 1")
        author2 = AuthorForBatch(id=2, name="Author 2")

        relation.batch_load([author1, author2], None)

        assert len(loader.batch_loaded_instances) == 1
        assert len(loader.batch_loaded_instances[0]) == 2
        assert author1 in loader.batch_loaded_instances[0]
        assert author2 in loader.batch_loaded_instances[0]

    def test_batch_load_returns_dict(self):
        """Test that batch_load returns a dict mapping instance IDs."""
        loader = RecordingBatchLoader()
        relation = AuthorForBatch.get_relation("books")
        relation._loader = loader

        author = AuthorForBatch(id=1, name="Author 1")

        result = relation.batch_load([author], None)

        assert isinstance(result, dict)
        assert id(author) in result

    def test_cached_results_not_loaded_again(self):
        """Test that cached results are not loaded again in batch."""
        RecordingBatchLoader()
        relation = AuthorForBatch.get_relation("books")
        relation._cache_config = CacheConfig()

        author1 = AuthorForBatch(id=1, name="Author 1")
        author2 = AuthorForBatch(id=2, name="Author 2")

        InstanceCache.set(author1, "books", [{"id": 99, "title": "Cached"}], CacheConfig())

        result = relation.batch_load([author1, author2], None)

        assert id(author1) in result
        assert result[id(author1)][0]["id"] == 99

    def test_batch_load_with_empty_list(self):
        """Test batch_load with empty instances list."""
        loader = RecordingBatchLoader()
        relation = AuthorForBatch.get_relation("books")
        relation._loader = loader

        result = relation.batch_load([], None)

        assert result == {}
        assert len(loader.batch_loaded_instances) == 0

    def test_all_cached_no_batch_load(self):
        """Test that if all instances are cached, batch_load is not called."""
        loader = RecordingBatchLoader()
        relation = AuthorForBatch.get_relation("books")
        relation._cache_config = CacheConfig()

        author1 = AuthorForBatch(id=1, name="Author 1")
        author2 = AuthorForBatch(id=2, name="Author 2")

        InstanceCache.set(author1, "books", [{"id": 1, "title": "Book 1"}], CacheConfig())
        InstanceCache.set(author2, "books", [{"id": 2, "title": "Book 2"}], CacheConfig())

        relation.batch_load([author1, author2], None)

        assert len(loader.batch_loaded_instances) == 0

    def test_partial_cache_loads_remaining(self):
        """Test that only uncached instances are loaded."""
        relation = AuthorForBatch.get_relation("books")
        relation._loader = RecordingBatchLoader()
        relation._cache_config = CacheConfig()

        author1 = AuthorForBatch(id=1, name="Author 1")
        author2 = AuthorForBatch(id=2, name="Author 2")

        InstanceCache.set(author1, "books", [{"id": 1, "title": "Cached"}], CacheConfig())

        result = relation.batch_load([author1, author2], None)

        assert id(author1) in result
        assert result[id(author1)][0]["id"] == 1
        assert id(author2) in result


class TestBelongsToBatchLoading:
    """Tests for BelongsTo batch loading."""

    def test_belongs_to_batch_load(self):
        """Test BelongsTo relation batch loading."""

        class BatchLoader(IRelationLoader):
            def load(self, instance: Any) -> Optional[Any]:
                return {"id": instance.author_id, "name": f"Author {instance.author_id}"}

            def batch_load(self, instances: List[Any], base_query: Any) -> Dict[int, Any]:
                {inst.author_id for inst in instances}
                return {id(inst): {"id": inst.author_id, "name": f"Author {inst.author_id}"} for inst in instances}

        loader = BatchLoader()
        relation = BookForBatch.get_relation("author")
        relation._loader = loader

        book1 = BookForBatch(id=1, title="Book 1", author_id=1)
        book2 = BookForBatch(id=2, title="Book 2", author_id=2)

        result = relation.batch_load([book1, book2], None)

        assert isinstance(result, dict)
        assert id(book1) in result
        assert id(book2) in result


class TestHasOneBatchLoading:
    """Tests for HasOne batch loading."""

    def test_has_one_batch_load(self):
        """Test HasOne relation batch loading."""

        class ProfileForHasOne(RelationManagementMixin, BaseModel):
            id: int
            bio: str
            author_id: int
            author: ClassVar[BelongsTo["AuthorForHasOne"]] = BelongsTo(foreign_key="author_id", inverse_of="profile")

        class AuthorForHasOne(RelationManagementMixin, BaseModel):
            id: int
            name: str
            profile: ClassVar[HasOne["ProfileForHasOne"]] = HasOne(foreign_key="author_id", inverse_of="author")

        class HasOneBatchLoader(IRelationLoader):
            def load(self, instance: Any) -> Optional[Any]:
                return {"id": 1, "bio": "Bio", "author_id": instance.id}

            def batch_load(self, instances: List[Any], base_query: Any) -> Dict[int, Any]:
                return {
                    id(inst): {"id": inst.id, "bio": f"Bio for {inst.name}", "author_id": inst.id} for inst in instances
                }

        loader = HasOneBatchLoader()
        relation = AuthorForHasOne.get_relation("profile")
        relation._loader = loader

        author1 = AuthorForHasOne(id=1, name="Author 1")
        author2 = AuthorForHasOne(id=2, name="Author 2")

        result = relation.batch_load([author1, author2], None)

        assert isinstance(result, dict)
        assert id(author1) in result
        assert id(author2) in result
        assert result[id(author1)]["author_id"] == 1
        assert result[id(author2)]["author_id"] == 2
