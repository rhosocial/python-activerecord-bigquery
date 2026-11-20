# tests/rhosocial/activerecord_bigquery_test/feature/query/relation/test_with_modifier.py
"""
Tests for with_() method modifier behavior.

These tests specifically cover:
1. Parameter expansion rule - modifier only applies to target relation
2. Later parameters overwrite earlier ones
3. Warning is issued when modifier is overwritten
"""

import logging
from typing import List, Optional, Any, Union, Tuple, Dict, Set
from unittest.mock import MagicMock

import pytest

from rhosocial.activerecord.interface import IQuery
from rhosocial.activerecord.query.relational import RelationalQueryMixin


class MockQueryBase(IQuery):
    """Mock base class that implements IQuery interface."""

    def __init__(self):
        self.model_class = MagicMock()
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

    def all(self) -> List[Any]:
        return []

    def one(self) -> Optional[Any]:
        return None

    def one_or_fail(self) -> Any:
        return None

    def where(self, condition: str, params: Optional[Union[tuple, List[Any]]] = None) -> "IQuery":
        return self

    def or_where(self, condition: str, params: Optional[Union[tuple, List[Any]]] = None) -> "IQuery":
        return self

    def order_by(self, *clauses: str) -> "IQuery":
        return self

    def join(self, join_clause: str) -> "IQuery":
        return self

    def limit(self, count: int) -> "IQuery":
        return self

    def offset(self, count: int) -> "IQuery":
        return self

    def select(self, *columns: str, append: bool = False) -> "IQuery":
        return self

    def count(self) -> int:
        return 0

    def exists(self) -> bool:
        return False

    def build(self) -> Tuple[str, tuple]:
        return "", ()

    def to_sql(self) -> Tuple[str, tuple]:
        return "", ()

    def explain(self, *args, **kwargs) -> "IQuery":
        return self

    def between(self, column: str, start: Any, end: Any) -> "IQuery[ModelT]":  # noqa: F821
        return self

    def not_between(self, column: str, start: Any, end: Any) -> "IQuery[ModelT]":  # noqa: F821
        return self

    def start_or_group(self) -> "IQuery[ModelT]":  # noqa: F821
        return self

    def end_or_group(self) -> "IQuery[ModelT]":  # noqa: F821
        return self

    def in_list(
        self, column: str, values: Union[List[Any], Tuple[Any, ...]], empty_result: bool = True
    ) -> "IQuery[ModelT]":  # noqa: F821
        return self

    def is_not_null(self, column: str) -> "IQuery[ModelT]":  # noqa: F821
        return self

    def is_null(self, column: str) -> "IQuery[ModelT]":  # noqa: F821
        return self

    def like(self, column: str, pattern: str) -> "IQuery[ModelT]":  # noqa: F821
        return self

    def not_like(self, column: str, pattern: str) -> "IQuery[ModelT]":  # noqa: F821
        return self

    def not_in(
        self, column: str, values: Union[List[Any], Tuple[Any, ...]], empty_result: bool = False
    ) -> "IQuery[ModelT]":  # noqa: F821
        return self

    def query(self, conditions: Optional[Dict[str, Any]] = None) -> "IQuery[ModelT]":  # noqa: F821
        return self

    def to_dict(self, include: Optional[Set[str]] = None, exclude: Optional[Set[str]] = None) -> "IDictQuery[ModelT]":  # noqa: F821
        return self


class MockQuery(RelationalQueryMixin, MockQueryBase):
    """Mock query class for testing."""

    def __init__(self):
        super().__init__()
        self._log = MagicMock()


class TestModifierExpansionRule:
    """Tests for parameter expansion rule - modifier only applies to target relation."""

    @pytest.fixture
    def query(self):
        return MockQuery()

    def test_modifier_only_on_target_not_intermediate(self, query):
        """Test that modifier is only applied to target relation, not intermediate ones.

        When processing ('posts.comments', modifier), the expansion should be:
        - 'posts' -> None (intermediate, no modifier)
        - 'posts.comments' -> modifier (target, has modifier)
        """

        def my_modifier(q):
            return q.where("status = 'published'")

        query.with_(("posts.comments", my_modifier))

        configs = query.get_relation_configs()

        assert "posts" in configs
        assert "posts.comments" in configs

        assert configs["posts"].query_modifier is None
        assert configs["posts.comments"].query_modifier == my_modifier

    def test_deep_nested_modifier_only_on_leaf(self, query):
        """Test deeply nested path - modifier only on the leaf."""

        def deep_modifier(q):
            return q.where("id > 0")

        query.with_(("user.posts.comments.author", deep_modifier))

        configs = query.get_relation_configs()

        assert configs["user"].query_modifier is None
        assert configs["user.posts"].query_modifier is None
        assert configs["user.posts.comments"].query_modifier is None
        assert configs["user.posts.comments.author"].query_modifier == deep_modifier

    def test_multiple_relations_each_with_own_modifier(self, query):
        """Test multiple relations each with their own modifier."""

        def modifier_a(q):
            q.name = "a"
            return q

        def modifier_b(q):
            q.name = "b"
            return q

        query.with_(
            ("posts", modifier_a),
            ("comments", modifier_b),
        )

        configs = query.get_relation_configs()

        assert configs["posts"].query_modifier == modifier_a
        assert configs["comments"].query_modifier == modifier_b

    def test_simple_path_with_modifier(self, query):
        """Test simple path - modifier applies to the only relation."""

        def filter_modifier(q):
            return q.where("active = true")

        query.with_(("posts", filter_modifier))

        configs = query.get_relation_configs()

        assert "posts" in configs
        assert configs["posts"].query_modifier == filter_modifier


class TestLaterParameterOverwritesEarlier:
    """Tests for later parameters overwriting earlier ones."""

    @pytest.fixture
    def query(self):
        return MockQuery()

    def test_later_modifier_overwrites_same_path(self, query):
        """Test that later modifier overwrites earlier one for the same path."""

        def modifier_v1(q):
            q.version = 1
            return q

        def modifier_v2(q):
            q.version = 2
            return q

        query.with_(
            ("posts", modifier_v1),
            ("posts", modifier_v2),
        )

        configs = query.get_relation_configs()

        assert configs["posts"].query_modifier == modifier_v2

    def test_longer_path_overwrites_shorter_path(self, query):
        """Test that ('posts.comments', m1) + ('posts.comments.user', m2) overwrites correctly.

        After expansion:
        - First param: 'posts' -> None, 'posts.comments' -> m1
        - Second param: 'posts' -> None, 'posts.comments' -> m2, 'posts.comments.user' -> m2

        Final result:
        - 'posts' -> None
        - 'posts.comments' -> m2 (overwritten!)
        - 'posts.comments.user' -> m2
        """

        def modifier_1(q):
            q.filter = "draft"
            return q

        def modifier_2(q):
            q.filter = "published"
            return q

        query.with_(
            ("posts.comments", modifier_1),
            ("posts.comments.user", modifier_2),
        )

        configs = query.get_relation_configs()

        assert configs["posts"].query_modifier is None
        assert configs["posts.comments"].query_modifier == modifier_2
        assert configs["posts.comments.user"].query_modifier == modifier_2

    def test_correct_order_preserves_modifiers(self, query):
        """Test that correct order preserves both modifiers.

        To keep 'posts.comments' modifier, put it AFTER 'posts.comments.user':
        - First: ('posts.comments.user', m2)
        - Second: ('posts.comments', m1)

        Result:
        - 'posts' -> None
        - 'posts.comments' -> m1 (not overwritten because shorter path comes later)
        - 'posts.comments.user' -> m2
        """

        def modifier_1(q):
            q.filter = "draft"
            return q

        def modifier_2(q):
            q.filter = "published"
            return q

        query.with_(
            ("posts.comments.user", modifier_2),
            ("posts.comments", modifier_1),
        )

        configs = query.get_relation_configs()

        assert configs["posts"].query_modifier is None
        assert configs["posts.comments"].query_modifier == modifier_1
        assert configs["posts.comments.user"].query_modifier == modifier_2


class TestModifierOverwriteWarning:
    """Tests for warning when modifier is overwritten."""

    @pytest.fixture
    def query(self):
        return MockQuery()

    def test_warning_when_modifier_overwritten(self, query):
        """Test that warning is issued when modifier is overwritten."""

        def modifier_v1(q):
            return q.where("status = 'draft'")

        def modifier_v2(q):
            return q.where("status = 'published'")

        query.with_(
            ("posts", modifier_v1),
            ("posts", modifier_v2),
        )

        # Check that _log was called with warning about overwritten modifier
        log_calls = [str(call) for call in query._log.call_args_list]
        assert any("modifier is being overwritten" in call for call in log_calls)

    def test_warning_shows_function_names(self, query):
        """Test that warning shows function names for named functions."""

        def filter_draft(q):
            return q.where("status = 'draft'")

        def filter_published(q):
            return q.where("status = 'published'")

        query.with_(
            ("posts", filter_draft),
            ("posts", filter_published),
        )

        log_calls = [str(call) for call in query._log.call_args_list]
        log_messages = " ".join(log_calls)
        assert "filter_draft" in log_messages
        assert "filter_published" in log_messages

    def test_no_warning_when_same_modifier(self, query):
        """Test that no warning is issued when same modifier is used."""

        def same_modifier(q):
            return q.where("status = 'published'")

        query.with_(
            ("posts", same_modifier),
            ("posts", same_modifier),
        )

        log_calls = [str(call) for call in query._log.call_args_list]
        assert not any("modifier is being overwritten" in call for call in log_calls)

    def test_no_warning_when_overwriting_with_none(self, query):
        """Test that no warning when overwriting with None (explicit clear)."""

        def some_modifier(q):
            return q.where("status = 'published'")

        query.with_(
            ("posts", some_modifier),
            ("posts", None),
        )

        log_calls = [str(call) for call in query._log.call_args_list]
        assert not any("modifier is being overwritten" in call for call in log_calls)

    def test_warning_for_nested_path_overwrite(self, query):
        """Test warning when nested path overwrites parent path modifier."""

        def parent_modifier(q):
            return q.where("parent = true")

        def child_modifier(q):
            return q.where("child = true")

        query.with_(
            ("posts.comments", parent_modifier),
            ("posts.comments.user", child_modifier),
        )

        log_calls = [str(call) for call in query._log.call_args_list]
        assert any("modifier is being overwritten" in call for call in log_calls)

    def test_no_warning_for_different_paths(self, query, caplog):
        """Test that no warning for different relation paths."""
        with caplog.at_level(logging.WARNING):

            def modifier_a(q):
                return q.where("a = 1")

            def modifier_b(q):
                return q.where("b = 2")

            query.with_(
                ("posts", modifier_a),
                ("comments", modifier_b),
            )

        assert not any("modifier is being overwritten" in record.message for record in caplog.records)


class TestDocumentationExamples:
    """Test cases that match the documentation examples."""

    @pytest.fixture
    def query(self):
        return MockQuery()

    def test_documentation_example_expansion(self, query):
        """Test the documentation example: ('posts.comments', modifier1) expands correctly."""

        def modifier1(q):
            return q.where("published = true")

        query.with_(("posts.comments", modifier1))

        configs = query.get_relation_configs()

        assert configs["posts"].query_modifier is None
        assert configs["posts.comments"].query_modifier == modifier1

    def test_documentation_example_overwrite(self, query):
        """Test the documentation example: m2 overwrites m1 for posts.comments."""

        def m1(q):
            q.filter = "draft"
            return q

        def m2(q):
            q.filter = "published"
            return q

        query.with_(
            ("posts.comments", m1),
            ("posts.comments.user", m2),
        )

        configs = query.get_relation_configs()

        assert configs["posts"].query_modifier is None
        assert configs["posts.comments"].query_modifier == m2
        assert configs["posts.comments.user"].query_modifier == m2

    def test_documentation_correct_order(self, query):
        """Test the documentation correct order example."""

        def m1(q):
            q.filter = "draft"
            return q

        def m2(q):
            q.filter = "published"
            return q

        query.with_(
            ("posts.comments.user", m2),
            ("posts.comments", m1),
        )

        configs = query.get_relation_configs()

        assert configs["posts"].query_modifier is None
        assert configs["posts.comments"].query_modifier == m1
        assert configs["posts.comments.user"].query_modifier == m2
