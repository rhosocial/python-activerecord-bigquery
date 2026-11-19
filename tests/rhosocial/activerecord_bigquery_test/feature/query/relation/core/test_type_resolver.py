# tests/rhosocial/activerecord_bigquery_test/feature/query/relation/test_type_resolver.py
"""Tests for the centralized type_resolver module."""

from typing import ClassVar, ForwardRef, Optional

import pytest
from pydantic import BaseModel

from rhosocial.activerecord.relation.base import RelationManagementMixin
from rhosocial.activerecord.relation.descriptors import BelongsTo, HasMany
from rhosocial.activerecord.relation.async_descriptors import AsyncBelongsTo
from rhosocial.activerecord.relation.type_resolver import (
    resolve_model_fqn,
    evaluate_annotation,
    resolve_relation_type,
    _build_owner_namespace,
    _unwrap_generic_type,
)


class TestResolveModelFqn:
    def test_module_level_class(self):
        fqn = resolve_model_fqn(BaseModel)
        assert fqn == "pydantic.main.BaseModel"

    def test_nested_class_qname(self):
        class Outer:
            class Inner:
                pass

        fqn = resolve_model_fqn(Outer.Inner)
        assert "Outer.Inner" in fqn


class TestEvaluateAnnotation:
    def test_evaluate_string_ref(self):
        class MyModel(RelationManagementMixin, BaseModel):
            id: int

        result = evaluate_annotation("MyModel", MyModel)
        assert result is MyModel

    def test_evaluate_with_extra_ns(self):
        class Owner(RelationManagementMixin, BaseModel):
            id: int

        class Dynamic:
            pass

        result = evaluate_annotation("Dynamic", Owner, extra_ns={"Dynamic": Dynamic})
        assert result is Dynamic

    def test_evaluate_unresolvable_name(self):
        class Owner(RelationManagementMixin, BaseModel):
            id: int

        with pytest.raises(NameError, match="name 'NoSuchModel' is not defined"):
            evaluate_annotation("NoSuchModel", Owner)

    def test_evaluate_forward_ref_direct(self):
        class MyModel(RelationManagementMixin, BaseModel):
            id: int

        ref = ForwardRef("MyModel")
        result = evaluate_annotation(ref, MyModel)
        assert result is MyModel

    def test_evaluate_via_frame_fallback(self):
        class MyModel(RelationManagementMixin, BaseModel):
            id: int

        class Owner(RelationManagementMixin, BaseModel):
            id: int
            rel: ClassVar[BelongsTo["MyModel"]] = BelongsTo(foreign_key="my_id")

        result = evaluate_annotation("MyModel", Owner)
        assert result is MyModel


class TestBuildOwnerNamespace:
    def test_includes_owner_types(self):
        class Inner:
            pass

        class Outer(RelationManagementMixin, BaseModel):
            id: int

        Outer.Inner = Inner
        ns = _build_owner_namespace(Outer)
        assert "Outer" in ns
        assert "Inner" in ns
        assert ns["Inner"] is Inner


class TestUnwrapGenericType:
    def test_simple_generic(self):
        result = _unwrap_generic_type(HasMany[str], __import__("typing"))
        assert result is str

    def test_classvar_wrapped(self):
        from typing import ClassVar as CV

        cv = CV[BelongsTo[str]]
        result = _unwrap_generic_type(cv, __import__("typing"))
        assert result is str


class TestResolveRelationType:
    def test_resolve_missing_field(self):
        class Owner(RelationManagementMixin, BaseModel):
            id: int

        assert resolve_relation_type(Owner, "no_such_field") is None

    def test_resolve_type_direct(self):
        class Owner(RelationManagementMixin, BaseModel):
            id: int
            ref: int = 0

        assert resolve_relation_type(Owner, "id") is int

    def test_resolve_string_annotation(self):
        Owner = type("Owner", (dict,), {"__annotations__": {"ref": "int"}})
        result = resolve_relation_type(Owner, "ref")
        assert result is int


class TestDescriptorCompat:
    """Sync/async descriptor mixing is rejected at class creation time.
    These tests are covered comprehensively in test_descriptor_compat.py.
    This file focuses on the type_resolver utilities.
    """


class TestRelatedModelTypeValidation:
    """Ensure relation target models are validated at resolution time."""

    def test_sync_descriptor_target_must_be_sync_model(self):
        from rhosocial.activerecord.model import ActiveRecord, AsyncActiveRecord

        class AsyncTarget(AsyncActiveRecord):
            @classmethod
            def table_name(cls):
                return "async_target_check"

            id: Optional[int] = None

        class Owner(ActiveRecord):
            @classmethod
            def table_name(cls):
                return "owner_check"

            id: Optional[int] = None
            ref_id: int
            bad: ClassVar[BelongsTo["AsyncTarget"]] = BelongsTo(foreign_key="ref_id", inverse_of=None)

        # cross sync/async is caught at load time, not resolution time
        desc = Owner.get_relation("bad")
        model = desc.get_related_model(Owner)
        assert model is AsyncTarget
        with pytest.raises(TypeError, match="must be a subclass of IActiveRecord"):
            desc._ensure_model_capability()

    def test_async_descriptor_target_must_be_async_model(self):
        from rhosocial.activerecord.model import ActiveRecord, AsyncActiveRecord

        class SyncTarget(ActiveRecord):
            @classmethod
            def table_name(cls):
                return "sync_target_check"

            id: Optional[int] = None

        class Owner(AsyncActiveRecord):
            @classmethod
            def table_name(cls):
                return "owner_check2"

            id: Optional[int] = None
            ref_id: int
            bad: ClassVar[AsyncBelongsTo["SyncTarget"]] = AsyncBelongsTo(foreign_key="ref_id", inverse_of=None)

        desc = Owner.get_relation("bad")
        model = desc.get_related_model(Owner)
        assert model is SyncTarget
        with pytest.raises(TypeError, match="must be a subclass of IAsyncActiveRecord"):
            desc._ensure_model_capability()

    def test_sync_descriptor_target_not_activerecord_raises(self):
        class PlainClass:
            pass

        class Owner(RelationManagementMixin, BaseModel):
            id: int
            ref_id: int
            rel: ClassVar[BelongsTo["PlainClass"]] = BelongsTo(foreign_key="ref_id", inverse_of=None)

        desc = Owner.get_relation("rel")
        with pytest.raises(TypeError, match="must support relation management"):
            desc.get_related_model(Owner)

    def test_async_descriptor_target_not_activerecord_raises(self):
        class PlainClass:
            pass

        from rhosocial.activerecord.model import AsyncActiveRecord

        class Owner(AsyncActiveRecord):
            @classmethod
            def table_name(cls):
                return "owner_check3"

            id: Optional[int] = None
            ref_id: int
            rel: ClassVar[AsyncBelongsTo["PlainClass"]] = AsyncBelongsTo(foreign_key="ref_id", inverse_of=None)

        desc = Owner.get_relation("rel")
        with pytest.raises(TypeError, match="must support relation management"):
            desc.get_related_model(Owner)

    def test_sync_descriptor_target_is_sync_model_passes(self):
        from rhosocial.activerecord.model import ActiveRecord

        class SyncTarget(ActiveRecord):
            @classmethod
            def table_name(cls):
                return "sync_target3"

            id: Optional[int] = None

        class Owner(ActiveRecord):
            @classmethod
            def table_name(cls):
                return "owner_check4"

            id: Optional[int] = None
            ref_id: int
            good: ClassVar[BelongsTo["SyncTarget"]] = BelongsTo(foreign_key="ref_id", inverse_of=None)

        desc = Owner.get_relation("good")
        result = desc.get_related_model(Owner)
        assert result is SyncTarget
        # load-level check also passes
        desc._ensure_model_capability()

    def test_async_descriptor_target_is_async_model_passes(self):
        from rhosocial.activerecord.model import AsyncActiveRecord

        class AsyncTarget(AsyncActiveRecord):
            @classmethod
            def table_name(cls):
                return "async_target3"

            id: Optional[int] = None

        class Owner(AsyncActiveRecord):
            @classmethod
            def table_name(cls):
                return "owner_check5"

            id: Optional[int] = None
            ref_id: int
            good: ClassVar[AsyncBelongsTo["AsyncTarget"]] = AsyncBelongsTo(foreign_key="ref_id", inverse_of=None)

        desc = Owner.get_relation("good")
        result = desc.get_related_model(Owner)
        assert result is AsyncTarget
        # load-level check also passes
        desc._ensure_model_capability()