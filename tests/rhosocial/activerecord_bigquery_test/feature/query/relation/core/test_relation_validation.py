# tests/rhosocial/activerecord_bigquery_test/feature/query/relation/test_relational_validation.py
"""
Tests for relational query validation and error handling.

These tests cover:
1. Invalid relation path format validation
2. Relation not found error handling
3. Edge cases and boundary conditions
"""

import pytest
from unittest.mock import MagicMock

from rhosocial.activerecord.interface import IQuery
from rhosocial.activerecord.query.relational import (
    RelationalQueryMixin,
    InvalidRelationPathError,
    RelationNotFoundError,
)


class MockQueryBase(IQuery):
    """Mock base class for testing."""

    def __init__(self):
        self.model_class = MagicMock()
        self.model_class.__name__ = "MockModel"
        self.condition_groups = [[]]
        self.current_group = 0
        self.order_clauses = []
        self.join_clauses = []
        self.limit_count = None
        self.offset_count = None
        from rhosocial.activerecord.backend.expression import AllColumnsWildcard
        from rhosocial.activerecord.backend.impl.sqlite.dialect import SQLiteDialect

        self.select_columns = [AllColumnsWildcard(SQLiteDialect())]
        self._explain_enabled = False
        self._explain_options = None

    def all(self):
        return []

    def one(self):
        return None

    def one_or_fail(self):
        return None

    def where(self, condition, params=None):
        return self

    def or_where(self, condition, params=None):
        return self

    def order_by(self, *clauses):
        return self

    def join(self, join_clause):
        return self

    def limit(self, count):
        return self

    def offset(self, count):
        return self

    def select(self, *columns, append=False):
        return self

    def count(self):
        return 0

    def exists(self):
        return False

    def build(self):
        return "", ()

    def to_sql(self):
        return "", ()

    def explain(self, *args, **kwargs):
        return self

    def between(self, column, start, end):
        return self

    def not_between(self, column, start, end):
        return self

    def start_or_group(self):
        return self

    def end_or_group(self):
        return self

    def in_list(self, column, values, empty_result=True):
        return self

    def is_not_null(self, column):
        return self

    def is_null(self, column):
        return self

    def like(self, column, pattern):
        return self

    def not_like(self, column, pattern):
        return self

    def not_in(self, column, values, empty_result=False):
        return self

    def query(self, conditions=None):
        return self

    def to_dict(self, include=None, exclude=None):
        return self


class MockQuery(RelationalQueryMixin, MockQueryBase):
    """Mock query class for testing."""

    def __init__(self):
        super().__init__()
        self._log = MagicMock()


class TestInvalidRelationPath:
    """Tests for invalid relation path validation."""

    @pytest.fixture
    def query(self):
        return MockQuery()

    def test_empty_relation_path(self, query):
        """Test that empty relation path raises InvalidRelationPathError."""
        with pytest.raises(InvalidRelationPathError) as exc_info:
            query.with_("")
        assert "cannot be empty" in str(exc_info.value)

    def test_leading_dot(self, query):
        """Test that path with leading dot raises InvalidRelationPathError."""
        with pytest.raises(InvalidRelationPathError) as exc_info:
            query.with_(".posts")
        assert "cannot start with a dot" in str(exc_info.value)

    def test_trailing_dot(self, query):
        """Test that path with trailing dot raises InvalidRelationPathError."""
        with pytest.raises(InvalidRelationPathError) as exc_info:
            query.with_("posts.")
        assert "cannot end with a dot" in str(exc_info.value)

    def test_consecutive_dots(self, query):
        """Test that path with consecutive dots raises InvalidRelationPathError."""
        with pytest.raises(InvalidRelationPathError) as exc_info:
            query.with_("posts..comments")
        assert "cannot contain consecutive dots" in str(exc_info.value)

    def test_multiple_invalid_paths(self, query):
        """Test that multiple invalid paths are validated in order."""
        # The first invalid path should raise
        with pytest.raises(InvalidRelationPathError):
            query.with_("posts", "")

    def test_analyze_relation_path_valid(self, query):
        """Test analyze_relation_path with valid path."""
        parts, configs = query.analyze_relation_path("posts.comments")
        assert parts == ["posts", "comments"]
        assert configs == ["posts", "posts.comments"]

    def test_analyze_relation_path_single(self, query):
        """Test analyze_relation_path with single relation."""
        parts, configs = query.analyze_relation_path("posts")
        assert parts == ["posts"]
        assert configs == ["posts"]

    def test_analyze_relation_path_invalid(self, query):
        """Test analyze_relation_path with invalid path raises error."""
        with pytest.raises(InvalidRelationPathError):
            query.analyze_relation_path("")


class TestRelationNotFound:
    """Tests for relation not found error handling."""

    @pytest.fixture
    def query(self):
        return MockQuery()

    def test_relation_not_found_on_model(self, query):
        """Test that RelationNotFoundError is raised when relation doesn't exist."""
        # Setup mock to return None for get_relation
        query.model_class.get_relation = MagicMock(return_value=None)
        query.model_class.hasattr = lambda x: True
        query.model_class.__name__ = "User"

        with pytest.raises(RelationNotFoundError) as exc_info:
            query.with_("nonexistent_relation")
        assert "not found" in str(exc_info.value)

    def test_nested_relation_not_found(self, query):
        """Test that RelationNotFoundError is raised for nested relation."""
        # Setup mock: posts exists, comments doesn't exist on Post model
        mock_post_model = MagicMock()
        mock_post_model.__name__ = "Post"
        mock_post_model.get_relation = MagicMock(return_value=None)
        mock_post_model.hasattr = lambda x: True

        mock_posts_rel = MagicMock()
        mock_posts_rel.get_related_model = MagicMock(return_value=mock_post_model)

        def get_relation_side_effect(name):
            if name == "posts":
                return mock_posts_rel
            return None

        query.model_class.get_relation = MagicMock(side_effect=get_relation_side_effect)
        query.model_class.hasattr = lambda x: True

        with pytest.raises(RelationNotFoundError) as exc_info:
            query.with_("posts.comments")
        assert "comments" in str(exc_info.value)

    def test_model_class_not_has_get_relation(self, query):
        """Test error when model doesn't have get_relation method."""
        query.model_class = MagicMock()
        # Remove get_relation from mock
        if hasattr(query.model_class, "get_relation"):
            del query.model_class.get_relation

        with pytest.raises((RelationNotFoundError, AttributeError)):
            query.with_("posts")

    def test_partial_path_valid_full_invalid(self, query):
        """Test that valid partial path with invalid full path raises error."""
        # Setup: first part exists, second doesn't
        mock_post_model = MagicMock()
        mock_post_model.__name__ = "Post"
        mock_post_model.get_relation = MagicMock(return_value=None)
        mock_post_model.hasattr = lambda x: True

        mock_posts_rel = MagicMock()
        mock_posts_rel.get_related_model = MagicMock(return_value=mock_post_model)

        def get_relation_side_effect(name):
            if name == "posts":
                return mock_posts_rel
            if name == "nonexistent":
                return None
            return None

        query.model_class.get_relation = MagicMock(side_effect=get_relation_side_effect)
        query.model_class.hasattr = lambda x: True

        with pytest.raises(RelationNotFoundError):
            query.with_("posts.nonexistent")


class TestWithEdgeCases:
    """Tests for edge cases in with_() method."""

    @pytest.fixture
    def query(self):
        return MockQuery()

    def test_with_no_relations(self, query):
        """Test that with_() works with no arguments."""
        result = query.with_()
        assert result is query

    def test_with_single_string_relation(self, query):
        """Test with_() with single string relation."""
        # Setup mock to allow validation to pass
        mock_rel = MagicMock()
        mock_rel.get_related_model = MagicMock(
            return_value=MagicMock(
                __name__="RelatedModel", get_relation=MagicMock(return_value=None), hasattr=lambda x: True
            )
        )

        query.model_class.get_relation = MagicMock(return_value=mock_rel)
        query.model_class.hasattr = lambda x: True

        query.with_("posts")
        configs = query.get_relation_configs()
        assert "posts" in configs

    def test_with_single_tuple_relation(self, query):
        """Test with_() with single tuple (path, modifier)."""
        mock_rel = MagicMock()
        mock_rel.get_related_model = MagicMock(
            return_value=MagicMock(
                __name__="RelatedModel", get_relation=MagicMock(return_value=None), hasattr=lambda x: True
            )
        )

        query.model_class.get_relation = MagicMock(return_value=mock_rel)
        query.model_class.hasattr = lambda x: True

        def modifier(q):
            return q

        query.with_(("posts", modifier))
        configs = query.get_relation_configs()
        assert "posts" in configs
        assert configs["posts"].query_modifier == modifier

    def test_with_none_modifier(self, query):
        """Test with_() with explicit None modifier."""
        mock_rel = MagicMock()
        mock_rel.get_related_model = MagicMock(
            return_value=MagicMock(
                __name__="RelatedModel", get_relation=MagicMock(return_value=None), hasattr=lambda x: True
            )
        )

        query.model_class.get_relation = MagicMock(return_value=mock_rel)
        query.model_class.hasattr = lambda x: True

        query.with_(("posts", None))
        configs = query.get_relation_configs()
        assert "posts" in configs
        assert configs["posts"].query_modifier is None

    def test_multiple_relations_with_validation(self, query):
        """Test with_() with multiple relations that pass validation."""
        mock_rel = MagicMock()
        mock_rel.get_related_model = MagicMock(
            return_value=MagicMock(
                __name__="RelatedModel", get_relation=MagicMock(return_value=None), hasattr=lambda x: True
            )
        )

        query.model_class.get_relation = MagicMock(return_value=mock_rel)
        query.model_class.hasattr = lambda x: True

        query.with_("posts", "comments", "profile")
        configs = query.get_relation_configs()
        assert "posts" in configs
        assert "comments" in configs
        assert "profile" in configs


class TestRelationConfig:
    """Tests for RelationConfig behavior."""

    def test_relation_config_defaults(self):
        """Test RelationConfig with default values."""
        from rhosocial.activerecord.query.relational import RelationConfig

        config = RelationConfig(name="posts", nested=[])
        assert config.name == "posts"
        assert config.nested == []
        assert config.query_modifier is None

    def test_relation_config_with_modifier(self):
        """Test RelationConfig with query modifier."""
        from rhosocial.activerecord.query.relational import RelationConfig

        def modifier(q):
            return q

        config = RelationConfig(name="posts", nested=["comments"], query_modifier=modifier)
        assert config.name == "posts"
        assert config.nested == ["comments"]
        assert config.query_modifier == modifier


class TestGetRelationConfigs:
    """Tests for get_relation_configs method."""

    @pytest.fixture
    def query(self):
        return MockQuery()

    def test_get_relation_configs_empty(self, query):
        """Test get_relation_configs returns empty dict initially."""
        configs = query.get_relation_configs()
        assert configs == {}

    def test_get_relation_configs_returns_copy(self, query):
        """Test that get_relation_configs returns a copy, not original."""
        mock_rel = MagicMock()
        mock_rel.get_related_model = MagicMock(
            return_value=MagicMock(
                __name__="RelatedModel", get_relation=MagicMock(return_value=None), hasattr=lambda x: True
            )
        )

        query.model_class.get_relation = MagicMock(return_value=mock_rel)
        query.model_class.hasattr = lambda x: True

        query.with_("posts")
        configs = query.get_relation_configs()
        configs["new_key"] = "new_value"

        # Original should not be modified
        original_configs = query.get_relation_configs()
        assert "new_key" not in original_configs
