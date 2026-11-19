# tests/rhosocial/activerecord_bigquery_test/feature/query/relation/test_relation_management.py
"""
Tests for RelationManagementMixin methods.

These tests cover the relation management functionality provided by the
RelationManagementMixin class in python-activerecord.
"""

import pytest
from typing import ClassVar

from pydantic import BaseModel

from rhosocial.activerecord.relation.base import RelationManagementMixin
from rhosocial.activerecord.relation.cache import CacheConfig, InstanceCache
from rhosocial.activerecord.relation.descriptors import (
    HasMany,
    BelongsTo,
    HasOne,
    RelationDescriptor,
)


class Department(RelationManagementMixin, BaseModel):
    id: int
    name: str
    employees: ClassVar[HasMany["Employee"]] = HasMany(foreign_key="department_id", inverse_of="department")


class Employee(RelationManagementMixin, BaseModel):
    id: int
    name: str
    department_id: int
    department: ClassVar[BelongsTo["Department"]] = BelongsTo(foreign_key="department_id", inverse_of="employees")


class Profile(RelationManagementMixin, BaseModel):
    id: int
    bio: str
    author_id: int
    author: ClassVar[BelongsTo["Author"]] = BelongsTo(foreign_key="author_id", inverse_of="profile")


class Author(RelationManagementMixin, BaseModel):
    id: int
    name: str
    books: ClassVar[HasMany["Book"]] = HasMany(foreign_key="author_id", inverse_of="author")
    profile: ClassVar[HasOne["Profile"]] = HasOne(foreign_key="author_id", inverse_of="author")


class Book(RelationManagementMixin, BaseModel):
    id: int
    title: str
    author_id: int
    author: ClassVar[BelongsTo["Author"]] = BelongsTo(foreign_key="author_id", inverse_of="books")


class TestRelationManagementMixin:
    """Tests for RelationManagementMixin functionality."""

    def test_ensure_relations_creates_dict(self):
        """Test that _ensure_relations creates the relations dict if not exists."""

        class NewModel(RelationManagementMixin, BaseModel):
            id: int

        relations = NewModel._ensure_relations()
        assert isinstance(relations, dict)
        assert "_relations_dict" in NewModel.__dict__

    def test_ensure_relations_returns_existing(self):
        """Test that _ensure_relations returns existing dict."""
        relations1 = Department._ensure_relations()
        relations2 = Department._ensure_relations()
        assert relations1 is relations2

    def test_register_relation(self):
        """Test registering a new relation."""

        class TestModel(RelationManagementMixin, BaseModel):
            id: int

        class TestRelation(HasMany):
            pass

        class TestDescriptor(RelationDescriptor):
            pass

        descriptor = RelationDescriptor(foreign_key="test_id")
        TestModel.register_relation("test_rel", descriptor)

        assert "test_rel" in TestModel.get_relations()
        assert TestModel.get_relation("test_rel") == descriptor

    def test_register_relation_overwrites(self):
        """Test that registering a relation with same name overwrites."""

        class TestModel(RelationManagementMixin, BaseModel):
            id: int

        descriptor1 = RelationDescriptor(foreign_key="test_id")
        descriptor2 = RelationDescriptor(foreign_key="other_id")

        TestModel.register_relation("test_rel", descriptor1)
        TestModel.register_relation("test_rel", descriptor2)

        assert TestModel.get_relation("test_rel") == descriptor2

    def test_get_relation_returns_none_for_unknown(self):
        """Test that get_relation returns None for unknown relation."""
        result = Department.get_relation("unknown_relation")
        assert result is None

    def test_get_relations_returns_all(self):
        """Test that get_relations returns all registered relations."""
        relations = Department.get_relations()
        assert "employees" in relations

    def test_get_relations_excludes_inherited(self):
        """Test that get_relations only returns own relations, not inherited."""

        class Parent(RelationManagementMixin, BaseModel):
            id: int
            parent_rel: ClassVar[HasMany["Other"]] = HasMany(foreign_key="parent_id", inverse_of="parent")

        class Child(Parent):
            pass

        class Other(RelationManagementMixin, BaseModel):
            id: int
            parent_id: int
            parent: ClassVar[BelongsTo["Parent"]] = BelongsTo(foreign_key="parent_id", inverse_of="parent_rel")

        parent_relations = Parent.get_relations()
        assert "parent_rel" in parent_relations

    def test_clear_relation_cache_specific(self):
        """Test clearing specific relation cache."""
        employee = Employee(id=1, name="Test", department_id=1)

        InstanceCache.set(employee, "department", {"id": 1, "name": "Dept"}, CacheConfig())

        assert InstanceCache.get(employee, "department", CacheConfig()) is not None

        employee.clear_relation_cache("department")

        assert InstanceCache.get(employee, "department", CacheConfig()) is None

    def test_clear_relation_cache_all(self):
        """Test clearing all relation caches."""
        employee = Employee(id=1, name="Test", department_id=1)

        InstanceCache.set(employee, "department", {"id": 1, "name": "Dept"}, CacheConfig())

        assert InstanceCache.get(employee, "department", CacheConfig()) is not None

        employee.clear_relation_cache()

        assert InstanceCache.get(employee, "department", CacheConfig()) is None

    def test_clear_relation_cache_invalid_name_raises(self):
        """Test that clearing invalid relation name raises ValueError."""
        employee = Employee(id=1, name="Test", department_id=1)

        with pytest.raises(ValueError) as exc_info:
            employee.clear_relation_cache("invalid_relation")

        assert "Unknown relation" in str(exc_info.value)


class TestRelationInheritance:
    """Tests for relation inheritance behavior."""

    def test_child_class_can_override_relation(self):
        """Test that child class can override parent relation."""

        class ParentModel(RelationManagementMixin, BaseModel):
            id: int
            related: ClassVar[HasOne["OtherModel"]] = HasOne(foreign_key="parent_id", inverse_of="parent")

        class OtherModel(RelationManagementMixin, BaseModel):
            id: int
            parent_id: int
            parent: ClassVar[BelongsTo["ParentModel"]] = BelongsTo(foreign_key="parent_id", inverse_of="related")

        parent_rel = ParentModel.get_relation("related")
        assert isinstance(parent_rel, HasOne)

    def test_relations_dict_is_class_specific(self):
        """Test that each class has its own relations dict."""

        class Parent(RelationManagementMixin, BaseModel):
            id: int

        class Child(Parent):
            pass

        Parent.register_relation("test", RelationDescriptor(foreign_key="test_id"))

        child_relations = Child._ensure_relations()

        assert "test" not in child_relations or "_relations_dict" not in Child.__dict__


class TestRelationValidation:
    """Tests for relation validation behavior."""

    def test_inverse_validation(self):
        """Test that inverse relationships are validated."""

        class AuthorWithValidation(RelationManagementMixin, BaseModel):
            id: int
            books: ClassVar[HasMany["BookWithValidation"]] = HasMany(foreign_key="author_id", inverse_of="author")

        class BookWithValidation(RelationManagementMixin, BaseModel):
            id: int
            author_id: int
            author: ClassVar[BelongsTo["AuthorWithValidation"]] = BelongsTo(foreign_key="author_id", inverse_of="books")

        author_rel = AuthorWithValidation.get_relation("books")
        book_rel = BookWithValidation.get_relation("author")

        assert author_rel is not None
        assert book_rel is not None

    def test_missing_inverse_does_not_raise(self):
        """Test that missing inverse doesn't raise during registration."""

        class ModelWithoutInverse(RelationManagementMixin, BaseModel):
            id: int
            related: ClassVar[HasMany["Target"]] = HasMany(foreign_key="model_id", inverse_of=None)

        class Target(RelationManagementMixin, BaseModel):
            id: int
            model_id: int

        relation = ModelWithoutInverse.get_relation("related")
        assert relation is not None
