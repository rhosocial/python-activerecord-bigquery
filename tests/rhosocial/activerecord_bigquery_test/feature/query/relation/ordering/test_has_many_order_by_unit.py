# tests/rhosocial/activerecord_bigquery_test/feature/query/relation/ordering/test_has_many_order_by_unit.py
"""
Unit tests for the optional ``order_by`` argument on HasMany / AsyncHasMany.

These tests do not execute SQL: the SQLite in-memory backend is only used to
build queries. They pin the descriptor API (normalization, validation, the
``None`` default, the apply_order hook) and the generated SQL text (field-name
mapping, tie-breakers, ordering).
"""

import asyncio
from typing import ClassVar, Optional

from typing_extensions import Annotated

import pytest
from pydantic import BaseModel

from rhosocial.activerecord.backend.expression.functions import length
from rhosocial.activerecord.backend.expression.query_parts import SortDirection
from rhosocial.activerecord.backend.impl.sqlite.backend import (
    AsyncSQLiteBackend,
    SQLiteBackend,
)
from rhosocial.activerecord.backend.impl.sqlite.config import SQLiteInMemoryConfig
from rhosocial.activerecord.base import DerivedField, FieldProxy
from rhosocial.activerecord.base.fields import UseColumn
from rhosocial.activerecord.field.composite_pk import CompositePKMixin
from rhosocial.activerecord.model import ActiveRecord, AsyncActiveRecord
from rhosocial.activerecord.relation import (
    AsyncBelongsTo,
    AsyncHasMany,
    BelongsTo,
    HasMany,
    HasOne,
    RelationManagementMixin,
)


# ==============================================================================
# Models used for SQL-text checks (sync)
# ==============================================================================


class OrderingAuthor(ActiveRecord):
    __primary_key__ = "id"
    """Author with an ordered HasMany whose sort field uses a custom column."""

    @classmethod
    def table_name(cls):
        return "ordering_authors"

    c: ClassVar[FieldProxy] = FieldProxy()

    id: Optional[int] = None
    name: str

    books: ClassVar[HasMany["OrderingBook"]] = HasMany(
        foreign_key="author_id",
        inverse_of="author",
        order_by=[("title", "DESC")],
    )


class OrderingBook(ActiveRecord):
    __primary_key__ = "id"
    """Book whose Python field ``title`` maps to the column ``book_title``."""

    @classmethod
    def table_name(cls):
        return "ordering_books"

    id: Optional[int] = None
    title: Annotated[str, UseColumn("book_title")]
    author_id: int

    author: ClassVar[BelongsTo["OrderingAuthor"]] = BelongsTo(
        foreign_key="author_id",
        inverse_of="books",
    )


class PlainOrderingAuthor(ActiveRecord):
    __primary_key__ = "id"
    """Author whose HasMany keeps the old un-ordered behaviour."""

    @classmethod
    def table_name(cls):
        return "ordering_authors"

    id: Optional[int] = None
    name: str

    books: ClassVar[HasMany["OrderingBook"]] = HasMany(
        foreign_key="author_id",
        inverse_of="author",
        order_by=None,
    )


class BadOrderAuthor(ActiveRecord):
    __primary_key__ = "id"
    """Author with a relation that names a field that does not exist."""

    @classmethod
    def table_name(cls):
        return "ordering_authors"

    id: Optional[int] = None
    name: str

    books: ClassVar[HasMany["OrderingBook"]] = HasMany(
        foreign_key="author_id",
        inverse_of="author",
        order_by="does_not_exist",
    )


class DerivedBook(ActiveRecord):
    __primary_key__ = "id"
    """Book with a derived field that must not be accepted as an order key."""

    @classmethod
    def table_name(cls):
        return "ordering_books"

    id: Optional[int] = None
    title: str
    author_id: int

    title_length: ClassVar[Annotated[int, DerivedField(
        lambda d: length(d, DerivedBook.c.title),
    )]]

    author: ClassVar[BelongsTo["DerivedAuthor"]] = BelongsTo(
        foreign_key="author_id",
        inverse_of="books",
    )


class DerivedAuthor(ActiveRecord):
    __primary_key__ = "id"
    """Author ordering by a derived field (rejected on first query build)."""

    @classmethod
    def table_name(cls):
        return "ordering_authors"

    id: Optional[int] = None
    name: str

    books: ClassVar[HasMany["DerivedBook"]] = HasMany(
        foreign_key="author_id",
        inverse_of="author",
        order_by="title_length",
    )


class OrderingPart(CompositePKMixin, ActiveRecord):
    """Composite-primary-key child used for tie-breaker checks."""

    @classmethod
    def table_name(cls):
        return "ordering_parts"

    @classmethod
    def primary_key(cls):
        return ("order_id", "line_no")

    order_id: int
    line_no: int
    label: str
    owner_id: int


class OrderingOwner(ActiveRecord):
    __primary_key__ = "id"
    """Owner of composite-key parts ordered by ``label``."""

    @classmethod
    def table_name(cls):
        return "ordering_owners"

    id: Optional[int] = None
    name: str

    parts: ClassVar[HasMany["OrderingPart"]] = HasMany(
        foreign_key="owner_id",
        order_by="label",
    )


# ==============================================================================
# Async models used for SQL-text checks
# ==============================================================================


class AsyncOrderingAuthor(AsyncActiveRecord):
    __primary_key__ = "id"
    """Async mirror of OrderingAuthor."""

    @classmethod
    def table_name(cls):
        return "ordering_authors"

    id: Optional[int] = None
    name: str

    books: ClassVar[AsyncHasMany["AsyncOrderingBook"]] = AsyncHasMany(
        foreign_key="author_id",
        inverse_of="author",
        order_by=[("title", "DESC")],
    )


class AsyncOrderingBook(AsyncActiveRecord):
    __primary_key__ = "id"
    """Async mirror of OrderingBook."""

    @classmethod
    def table_name(cls):
        return "ordering_books"

    id: Optional[int] = None
    title: str
    author_id: int

    author: ClassVar[AsyncBelongsTo["AsyncOrderingAuthor"]] = AsyncBelongsTo(
        foreign_key="author_id",
        inverse_of="books",
    )


# ==============================================================================
# Descriptor-only (memory-based) models
# ==============================================================================


class MemoryEmp(RelationManagementMixin, BaseModel):
    """Memory-based child for inverse-pair validation (no database access)."""

    id: int
    name: str
    dept_id: int

    department: ClassVar[BelongsTo["MemoryDept"]] = BelongsTo(
        foreign_key="dept_id",
        inverse_of="ordered_emps",
    )


class MemoryDept(RelationManagementMixin, BaseModel):
    """Memory-based parent declaring a HasMany with order_by."""

    id: int
    name: str

    ordered_emps: ClassVar[HasMany["MemoryEmp"]] = HasMany(
        foreign_key="dept_id",
        inverse_of="department",
        order_by="name",
    )


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture(scope="module", autouse=True)
def configured_backends():
    """Bind the in-memory backend so queries can be built (no tables needed)."""
    models = (
        OrderingAuthor,
        OrderingBook,
        PlainOrderingAuthor,
        BadOrderAuthor,
        DerivedAuthor,
        DerivedBook,
        OrderingOwner,
        OrderingPart,
    )
    for model in models:
        model.configure(SQLiteInMemoryConfig(), SQLiteBackend)

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(AsyncOrderingAuthor.configure(SQLiteInMemoryConfig(), AsyncSQLiteBackend))
        loop.run_until_complete(AsyncOrderingBook.configure(SQLiteInMemoryConfig(), AsyncSQLiteBackend))
    finally:
        loop.close()
    yield

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(AsyncOrderingAuthor.backend().disconnect())
        loop.run_until_complete(AsyncOrderingBook.backend().disconnect())
    finally:
        loop.close()
    for model in models:
        model.backend().disconnect()


# ==============================================================================
# Constructor / normalization
# ==============================================================================


class TestHasManyOrderByConstructor:
    """Pin the accepted ``order_by`` forms and their normalization."""

    def test_none_is_the_default_plain_behavior(self):
        relation = HasMany(foreign_key="author_id")
        assert relation._order_by is None

    def test_explicit_none_is_plain_behavior(self):
        relation = HasMany(foreign_key="author_id", order_by=None)
        assert relation._order_by is None

    def test_single_field_string_defaults_to_no_direction(self):
        relation = HasMany(foreign_key="author_id", order_by="created_at")
        assert relation._order_by == (("created_at", None),)

    def test_single_field_tuple_with_direction(self):
        relation = HasMany(foreign_key="author_id", order_by=("created_at", "DESC"))
        assert relation._order_by == (("created_at", SortDirection.DESC),)

    def test_sequence_mixes_directions(self):
        relation = HasMany(
            foreign_key="author_id",
            order_by=["name", ("created_at", "DESC")],
        )
        assert relation._order_by == (("name", None), ("created_at", SortDirection.DESC))

    def test_empty_sequence_is_rejected(self):
        with pytest.raises(ValueError, match="non-empty"):
            HasMany(foreign_key="author_id", order_by=[])

    def test_invalid_direction_is_rejected(self):
        with pytest.raises(ValueError, match="Invalid ORDER BY direction"):
            HasMany(foreign_key="author_id", order_by=("name", "UP"))

    def test_non_string_entry_is_rejected(self):
        with pytest.raises(TypeError, match="field name"):
            HasMany(foreign_key="author_id", order_by=[123])

    def test_async_relation_normalizes_the_same_way(self):
        relation = AsyncHasMany(foreign_key="author_id", order_by=["name", ("id", "DESC")])
        assert relation._order_by == (("name", None), ("id", SortDirection.DESC))

    def test_async_none_is_plain_behavior(self):
        relation = AsyncHasMany(foreign_key="author_id", order_by=None)
        assert relation._order_by is None


# ==============================================================================
# Inverse validation / metaclass compatibility
# ==============================================================================


class TestHasManyOrderByCompatibility:
    """HasMany(order_by=...) must pass every check plain HasMany passes."""

    def test_valid_inverse_with_belongs_to(self):
        descriptor = MemoryDept.__dict__["ordered_emps"]
        assert descriptor.get_related_model(MemoryDept) is MemoryEmp

    def test_has_one_inverse_is_rejected(self):
        class Dept(RelationManagementMixin, BaseModel):
            id: int
            items: ClassVar[HasMany["Item"]] = HasMany(
                foreign_key="dept_id",
                inverse_of="department",
                order_by="name",
            )

        class Item(RelationManagementMixin, BaseModel):
            id: int
            dept_id: int
            department: ClassVar[HasOne["Dept"]] = HasOne(
                foreign_key="dept_id",
                inverse_of="items",
            )

        with pytest.raises(ValueError, match="Invalid relationship pair"):
            Dept.__dict__["items"].get_related_model(Dept)

    def test_sync_model_rejects_async_has_many_with_order_by(self):
        with pytest.raises(TypeError, match="Async relation descriptor"):
            class BadSyncModel(ActiveRecord):
                id: int
                items: ClassVar[AsyncHasMany] = AsyncHasMany(
                    foreign_key="owner_id",
                    order_by="id",
                )

    def test_async_model_rejects_sync_has_many_with_order_by(self):
        with pytest.raises(TypeError, match="Sync relation descriptor"):
            class BadAsyncModel(AsyncActiveRecord):
                id: int
                items: ClassVar[HasMany] = HasMany(
                    foreign_key="owner_id",
                    order_by="id",
                )


# ==============================================================================
# SQL text
# ==============================================================================


class TestHasManyOrderBySql:
    """Pin the generated ORDER BY clause."""

    def test_relation_query_maps_field_to_column_and_appends_pk(self):
        author = OrderingAuthor(id=1, name="Ada")
        sql, _params = author.books_query().to_sql()
        assert 'ORDER BY "book_title" DESC, "id" ASC' in sql

    def test_none_keeps_plain_has_many_sql(self):
        author = PlainOrderingAuthor(id=1, name="Plain")
        sql, _params = author.books_query().to_sql()
        assert "ORDER BY" not in sql
        assert 'WHERE "ordering_books"."author_id" = ?' in sql

    def test_explicit_primary_key_is_not_duplicated(self):
        relation = HasMany(
            foreign_key="author_id",
            order_by=[("id", "DESC")],
        )
        relation.name = "pk_books"
        query = relation.apply_order(OrderingBook.query(), OrderingBook)
        sql, _params = query.to_sql()
        assert 'ORDER BY "id" DESC' in sql
        assert sql.count('"id"') == 1

    def test_composite_primary_key_appends_every_key_column(self):
        owner = OrderingOwner(id=1, name="Owner")
        sql, _params = owner.parts_query().to_sql()
        assert 'ORDER BY "label" ASC, "order_id" ASC, "line_no" ASC' in sql

    def test_unknown_field_fails_when_query_is_built(self):
        author = BadOrderAuthor(id=1, name="Bad")
        with pytest.raises(ValueError, match="does_not_exist"):
            author.books_query()

    def test_derived_field_fails_when_query_is_built(self):
        author = DerivedAuthor(id=1, name="Derived")
        with pytest.raises(ValueError, match="title_length"):
            author.books_query()

    def test_async_relation_query_matches_sync_sql(self):
        author = AsyncOrderingAuthor(id=1, name="Async Ada")
        sql, _params = author.books_query().to_sql()
        assert 'ORDER BY "title" DESC, "id" ASC' in sql

    def test_chain_order_by_appends_after_default(self):
        author = OrderingAuthor(id=1, name="Ada")
        sql, _params = author.books_query().order_by("author_id").to_sql()
        assert 'ORDER BY "book_title" DESC, "id" ASC, "author_id" ASC' in sql
