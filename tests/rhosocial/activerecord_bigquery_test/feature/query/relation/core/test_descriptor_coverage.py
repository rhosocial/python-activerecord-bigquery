# tests/rhosocial/activerecord_bigquery_test/feature/query/relation/test_descriptor_coverage.py
"""
Targeted tests to cover uncovered code paths in descriptors.py and async_descriptors.py.
Also identifies dead code.
"""

from typing import ClassVar, ForwardRef

import pytest
from pydantic import BaseModel

from rhosocial.activerecord.relation.base import RelationManagementMixin
from rhosocial.activerecord.relation.descriptors import (
    BelongsTo,
    HasOne,
    HasMany,
    DefaultIRelationLoader,
)
from rhosocial.activerecord.relation.type_resolver import evaluate_annotation
from rhosocial.activerecord.relation.async_descriptors import (
    AsyncBelongsTo,
    AsyncHasMany,
    AsyncDefaultRelationLoader,
)
from rhosocial.activerecord.relation.cache import CacheConfig, InstanceCache
from rhosocial.activerecord.relation.interfaces import IRelationLoader


# ==============================================================================
# 1. __init__ validation paths
# ==============================================================================


class TestDescriptorInit:
    """Cover __init__ validation branches."""

    def test_sync_invalid_foreign_key_type(self):
        with pytest.raises(TypeError, match="foreign_key must be a string"):
            BelongsTo(foreign_key=123)

    def test_sync_invalid_cache_config_type(self):
        with pytest.raises(TypeError, match="cache_config must be instance of CacheConfig"):
            BelongsTo(foreign_key="x_id", cache_config="not_a_cache_config")  # type: ignore

    def test_async_invalid_foreign_key_type(self):
        with pytest.raises(TypeError, match="foreign_key must be a string"):
            AsyncBelongsTo(foreign_key=123)

    def test_async_invalid_cache_config_type(self):
        with pytest.raises(TypeError, match="cache_config must be instance of CacheConfig"):
            AsyncBelongsTo(foreign_key="x_id", cache_config="not_a_cache_config")  # type: ignore


# ==============================================================================
# 2. __get__ class-level access
# ==============================================================================


class TestDescriptorGetClassLevel:
    """Cover __get__ with instance=None path."""

    def test_sync_get_on_class_returns_self(self):
        class Dept(RelationManagementMixin, BaseModel):
            id: int
            name: str
            employees: ClassVar[HasMany["Emp"]] = HasMany(foreign_key="dept_id", inverse_of="department")

        class Emp(RelationManagementMixin, BaseModel):
            id: int
            dept_id: int
            department: ClassVar[BelongsTo["Dept"]] = BelongsTo(foreign_key="dept_id", inverse_of="employees")

        descriptor = Dept.__dict__["employees"]
        result = descriptor.__get__(None, Dept)
        assert result is descriptor

    def test_async_get_on_class_returns_self(self):
        class Dept(RelationManagementMixin, BaseModel):
            id: int
            name: str
            employees: ClassVar[AsyncHasMany["Emp"]] = AsyncHasMany(foreign_key="dept_id", inverse_of="department")

        class Emp(RelationManagementMixin, BaseModel):
            id: int
            dept_id: int
            department: ClassVar[AsyncBelongsTo["Dept"]] = AsyncBelongsTo(foreign_key="dept_id", inverse_of="employees")

        descriptor = Dept.__dict__["employees"]
        result = descriptor.__get__(None, Dept)
        assert result is descriptor


# ==============================================================================
# 3. __delete__
# ==============================================================================


class TestDescriptorDelete:
    """Cover __delete__ path."""

    def test_sync_delete_clears_cache(self):
        class Owner(RelationManagementMixin, BaseModel):
            id: int
            items: ClassVar[HasMany["Item"]] = HasMany(foreign_key="owner_id", inverse_of="owner")

        class Item(RelationManagementMixin, BaseModel):
            id: int
            owner_id: int
            owner: ClassVar[BelongsTo["Owner"]] = BelongsTo(foreign_key="owner_id", inverse_of="items")

        instance = Owner(id=1)
        InstanceCache.set(instance, "items", [Item(id=1, owner_id=1)], CacheConfig())
        assert InstanceCache.get(instance, "items", CacheConfig()) is not None

        descriptor = Owner.__dict__["items"]
        descriptor.__delete__(instance)
        assert InstanceCache.get(instance, "items", CacheConfig()) is None

    def test_async_delete_clears_cache(self):
        class Owner(RelationManagementMixin, BaseModel):
            id: int
            items: ClassVar[AsyncHasMany["Item"]] = AsyncHasMany(foreign_key="owner_id", inverse_of="owner")

        class Item(RelationManagementMixin, BaseModel):
            id: int
            owner_id: int
            owner: ClassVar[AsyncBelongsTo["Owner"]] = AsyncBelongsTo(foreign_key="owner_id", inverse_of="items")

        instance = Owner(id=1)
        InstanceCache.set(instance, "items", [Item(id=1, owner_id=1)], CacheConfig())
        assert InstanceCache.get(instance, "items", CacheConfig()) is not None

        descriptor = Owner.__dict__["items"]
        descriptor.__delete__(instance)
        assert InstanceCache.get(instance, "items", CacheConfig()) is None


# ==============================================================================
# 4. _load_relation paths (cache hit, loader error)
# ==============================================================================


class FakeSyncLoader(IRelationLoader):
    def __init__(self, return_value=None, raise_error=False):
        self.return_value = return_value
        self.raise_error = raise_error
        self.load_called = False

    def load(self, instance):
        self.load_called = True
        if self.raise_error:
            raise RuntimeError("loader failed")
        return self.return_value

    def batch_load(self, instances, base_query):
        return {id(instances[0]): self.return_value}


class TestLoadRelation:
    """Cover _load_relation cache hit, miss, and error paths."""

    def test_sync_load_cache_hit(self):
        data = {"id": 1}
        loader = FakeSyncLoader(return_value=data)

        class Target(RelationManagementMixin, BaseModel):
            id: int

        class Source(RelationManagementMixin, BaseModel):
            id: int
            target_id: int
            target: ClassVar[BelongsTo["Target"]] = BelongsTo(foreign_key="target_id", loader=loader)

        instance = Source(id=1, target_id=1)
        # Pre-set cache
        InstanceCache.set(instance, "target", data, CacheConfig())
        # Access via descriptor
        result = instance.target()
        assert result == data
        assert not loader.load_called

    def test_sync_load_cache_miss(self):
        class Target(RelationManagementMixin, BaseModel):
            id: int
            name: str

        data = Target(id=1, name="test")
        loader = FakeSyncLoader(return_value=data)

        class Source(RelationManagementMixin, BaseModel):
            id: int
            target_id: int
            target: ClassVar[BelongsTo["Target"]] = BelongsTo(foreign_key="target_id", loader=loader)

        instance = Source(id=1, target_id=1)
        result = instance.target()
        assert result == data
        assert loader.load_called

    def test_sync_load_loader_error_returns_none(self):
        loader = FakeSyncLoader(raise_error=True)

        class Target(RelationManagementMixin, BaseModel):
            id: int

        class Source(RelationManagementMixin, BaseModel):
            id: int
            target_id: int
            target: ClassVar[BelongsTo["Target"]] = BelongsTo(foreign_key="target_id", loader=loader)

        instance = Source(id=1, target_id=1)
        result = instance.target()
        assert result is None

    @pytest.mark.asyncio
    async def test_async_load_cache_hit(self):
        class Target(RelationManagementMixin, BaseModel):
            id: int

        data = {"id": 1}
        loader = FakeSyncLoader(return_value=data)

        class Source(RelationManagementMixin, BaseModel):
            id: int
            target_id: int
            target: ClassVar[AsyncBelongsTo["Target"]] = AsyncBelongsTo(foreign_key="target_id", loader=loader)

        instance = Source(id=1, target_id=1)
        InstanceCache.set(instance, "target", data, CacheConfig())
        result = await instance.target()
        assert result == data


# ==============================================================================
# 5. _create_relation_method with args — exercises dead self._query path
# ==============================================================================


class TestCreateRelationMethodNoArgs:
    """_create_relation_method no longer accepts args (dead code removed)."""

    def test_sync_relation_method_rejects_args(self):
        class Target(RelationManagementMixin, BaseModel):
            id: int

        class Source(RelationManagementMixin, BaseModel):
            id: int
            target_id: int
            target: ClassVar[BelongsTo["Target"]] = BelongsTo(foreign_key="target_id")

        instance = Source(id=1, target_id=1)
        method = Source.target.__get__(instance, Source)
        with pytest.raises(TypeError):
            method(some_arg="value")

    @pytest.mark.asyncio
    async def test_async_relation_method_rejects_args(self):
        class Target(RelationManagementMixin, BaseModel):
            id: int

        class Source(RelationManagementMixin, BaseModel):
            id: int
            target_id: int
            target: ClassVar[AsyncBelongsTo["Target"]] = AsyncBelongsTo(foreign_key="target_id")

        instance = Source(id=1, target_id=1)
        method = Source.target.__get__(instance, Source)
        with pytest.raises(TypeError):
            await method(some_arg="value")


# ==============================================================================
# 6. _evaluate_forward_ref
# ==============================================================================


class TestEvaluateForwardRef:
    """Cover evaluate_annotation function from type_resolver."""

    def test_evaluate_string_ref(self):
        class DummyModel(RelationManagementMixin, BaseModel):
            id: int

        result = evaluate_annotation("DummyModel", DummyModel)
        assert result is DummyModel

    def test_evaluate_forward_ref_direct(self):
        class DummyModel(RelationManagementMixin, BaseModel):
            id: int

        ref = ForwardRef("DummyModel")
        result = evaluate_annotation(ref, DummyModel)
        assert result is DummyModel

    def test_evaluate_forward_ref_with_module_scope(self):
        """Test that forward ref resolves using module globals."""

        class DummyModel(RelationManagementMixin, BaseModel):
            id: int

        ref = ForwardRef("BaseModel")
        result = evaluate_annotation(ref, DummyModel)
        assert result is BaseModel


# ==============================================================================
# 7. RelationshipValidator / AsyncRelationshipValidator
# ==============================================================================


class TestRelationshipValidatorPaths:
    """Cover RelationshipValidator validation branches."""

    def test_valid_belongs_to_has_many_pair(self):
        class Dept(RelationManagementMixin, BaseModel):
            id: int
            employees: ClassVar[HasMany["Emp"]] = HasMany(foreign_key="dept_id", inverse_of="department")

        class Emp(RelationManagementMixin, BaseModel):
            id: int
            dept_id: int
            department: ClassVar[BelongsTo["Dept"]] = BelongsTo(foreign_key="dept_id", inverse_of="employees")

        # Trigger validation by accessing relation
        Emp(id=1, dept_id=1).department()

    def test_valid_belongs_to_has_one_pair(self):
        class User(RelationManagementMixin, BaseModel):
            id: int
            profile: ClassVar[HasOne["Profile"]] = HasOne(foreign_key="user_id", inverse_of="user")

        class Profile(RelationManagementMixin, BaseModel):
            id: int
            user_id: int
            user: ClassVar[BelongsTo["User"]] = BelongsTo(foreign_key="user_id", inverse_of="profile")

        # Trigger validation
        Profile(id=1, user_id=1).user()

    def test_invalid_has_many_has_many_pair(self):
        """HasMany↔HasMany should fail validation on relation access."""

        class A(RelationManagementMixin, BaseModel):
            id: int
            bs: ClassVar[HasMany["B"]] = HasMany(foreign_key="a_id", inverse_of="a")

        class B(RelationManagementMixin, BaseModel):
            id: int
            a_id: int
            a: ClassVar[HasMany["A"]] = HasMany(foreign_key="a_id", inverse_of="bs")

        # Validation is lazy — triggered on relation access
        with pytest.raises(ValueError, match="Invalid relationship pair"):
            A(id=1).bs()

    def test_auto_set_inverse_of(self):
        """When inverse_of is None on the related model, it should be auto-set."""

        class A(RelationManagementMixin, BaseModel):
            id: int
            bs: ClassVar[HasMany["B"]] = HasMany(foreign_key="a_id", inverse_of="a")

        class B(RelationManagementMixin, BaseModel):
            id: int
            a_id: int
            a: ClassVar[BelongsTo["A"]] = BelongsTo(foreign_key="a_id")

        # Trigger validation by accessing the relation
        A(id=1).bs()
        assert B.get_relation("a").inverse_of == "bs"

    def test_async_valid_belongs_to_has_many_pair(self):
        class Dept(RelationManagementMixin, BaseModel):
            id: int
            employees: ClassVar[AsyncHasMany["Emp"]] = AsyncHasMany(foreign_key="dept_id", inverse_of="department")

        class Emp(RelationManagementMixin, BaseModel):
            id: int
            dept_id: int
            department: ClassVar[AsyncBelongsTo["Dept"]] = AsyncBelongsTo(foreign_key="dept_id", inverse_of="employees")

    def test_missing_inverse_relationship(self):
        """Inverse name does not exist on related model."""

        class A(RelationManagementMixin, BaseModel):
            id: int
            bs: ClassVar[HasMany["B"]] = HasMany(foreign_key="a_id", inverse_of="nonexistent")

        class B(RelationManagementMixin, BaseModel):
            id: int
            a_id: int

        with pytest.raises(ValueError, match="Inverse relationship.*not found"):
            A(id=1).bs()

    def test_non_relation_inverse(self):
        """Inverse exists but is not a RelationDescriptor."""

        class A(RelationManagementMixin, BaseModel):
            id: int
            bs: ClassVar[HasMany["B"]] = HasMany(foreign_key="a_id", inverse_of="a")

        class B(RelationManagementMixin, BaseModel):
            id: int
            a_id: int
            a: ClassVar[str] = "not_a_descriptor"

        with pytest.raises(ValueError, match="must be a RelationDescriptor"):
            A(id=1).bs()

    def test_async_missing_inverse_relationship(self):
        """Inverse name does not exist on related model."""

        class A(RelationManagementMixin, BaseModel):
            id: int
            bs: ClassVar[AsyncHasMany["B"]] = AsyncHasMany(foreign_key="a_id", inverse_of="nonexistent")

        class B(RelationManagementMixin, BaseModel):
            id: int
            a_id: int

        with pytest.raises(ValueError, match="Inverse relationship.*not found"):
            A(id=1).bs()

    def test_async_auto_set_inverse_of(self):
        class A(RelationManagementMixin, BaseModel):
            id: int
            bs: ClassVar[AsyncHasMany["B"]] = AsyncHasMany(foreign_key="a_id", inverse_of="a")

        class B(RelationManagementMixin, BaseModel):
            id: int
            a_id: int
            a: ClassVar[AsyncBelongsTo["A"]] = AsyncBelongsTo(foreign_key="a_id")

        # Trigger validation via get_related_model directly (avoids coroutine)
        desc = A.get_relation("bs")
        desc.get_related_model(A)
        assert B.get_relation("a").inverse_of == "bs"

    def test_inconsistent_inverse_wrong_owner(self):
        """Trigger 'Inconsistent inverse' by validating with an unrelated owner.

        WARNING: This simulates an unnatural scenario where validate() is called
        with an owner class that does NOT own the descriptor. Under normal class
        definition this path is unreachable, because validate() is only invoked
        from __set_name__, which always passes the actual owner class.
        Do NOT replicate this pattern in application code.
        """

        class A(RelationManagementMixin, BaseModel):
            id: int
            bs: ClassVar[HasMany["B"]] = HasMany(foreign_key="a_id", inverse_of="a")

        class B(RelationManagementMixin, BaseModel):
            id: int
            a_id: int
            a: ClassVar[BelongsTo["A"]] = BelongsTo(foreign_key="a_id", inverse_of="bs")

        # After B's validation, A.bs.inverse_of was auto-set to 'a'.
        # Now call A.bs's validator with an unrelated owner class C.
        class C(RelationManagementMixin, BaseModel):
            id: int

        with pytest.raises(ValueError, match="Inconsistent inverse"):
            A.get_relation("bs")._validator.validate(C, B)

    def test_async_inconsistent_inverse_wrong_owner(self):
        """Async: trigger 'Inconsistent inverse' via unrelated owner.

        WARNING: Same unnatural scenario as the sync version. Do NOT replicate
        in application code.
        """

        class A(RelationManagementMixin, BaseModel):
            id: int
            bs: ClassVar[AsyncHasMany["B"]] = AsyncHasMany(foreign_key="a_id", inverse_of="a")

        class B(RelationManagementMixin, BaseModel):
            id: int
            a_id: int
            a: ClassVar[AsyncBelongsTo["A"]] = AsyncBelongsTo(foreign_key="a_id", inverse_of="bs")

        class C(RelationManagementMixin, BaseModel):
            id: int

        with pytest.raises(ValueError, match="Inconsistent inverse"):
            A.get_relation("bs")._validator.validate(C, B)


# ==============================================================================
# 8. DefaultIRelationLoader & AsyncDefaultRelationLoader — basic init
# ==============================================================================


class TestDefaultLoadersInit:
    """Default loaders are created internally; verify existence."""

    def test_sync_default_loader_created(self):
        desc = BelongsTo(foreign_key="x_id")
        loader = desc._loader
        assert isinstance(loader, DefaultIRelationLoader)
        assert loader.descriptor is desc

    def test_async_default_loader_created(self):
        desc = AsyncBelongsTo(foreign_key="x_id")
        loader = desc._loader
        assert isinstance(loader, AsyncDefaultRelationLoader)
        assert loader.descriptor is desc


# ==============================================================================
# 9. _create_query_method coverage via descriptor
# ==============================================================================


class TestCreateQueryMethod:
    """Cover _create_query_method for both BelongsTo and HasOne/HasMany."""

    def test_query_method_exists(self):
        class Target(RelationManagementMixin, BaseModel):
            id: int

        class Source(RelationManagementMixin, BaseModel):
            id: int
            target_id: int
            target: ClassVar[BelongsTo["Target"]] = BelongsTo(foreign_key="target_id")

        assert hasattr(Source, "target_query")
        # Calling requires a proper instance with backend → skip call, just check existence.

    def test_async_query_method_exists(self):
        class Target(RelationManagementMixin, BaseModel):
            id: int

        class Source(RelationManagementMixin, BaseModel):
            id: int
            target_id: int
            target: ClassVar[AsyncBelongsTo["Target"]] = AsyncBelongsTo(foreign_key="target_id")

        assert hasattr(Source, "target_query")


# ==============================================================================
# 10. batch_load on RelationDescriptor / AsyncRelationDescriptor
# ==============================================================================


class TestDescriptorBatchLoad:
    """Cover RelationDescriptor.batch_load with empty records."""

    def test_sync_batch_load_empty_records(self):
        desc = BelongsTo(foreign_key="x_id")
        desc.name = "test_rel"
        result = desc.batch_load([], None)
        assert result == {}

    @pytest.mark.asyncio
    async def test_async_batch_load_empty_records(self):
        desc = AsyncBelongsTo(foreign_key="x_id")
        desc.name = "test_rel"
        result = await desc.batch_load([], None)
        assert result == {}


# ==============================================================================
# 11. log method with offset
# ==============================================================================


class TestLogMethod:
    """Cover the log method's offset handling."""

    def test_log_with_offset(self):
        desc = BelongsTo(foreign_key="x_id")
        # Should not crash even without _owner
        desc.log(10, "test message", offset=2)


# ==============================================================================
# 12. Resolve model type from annotations with ClassVar
# ==============================================================================


class TestResolveModel:
    """Cover _resolve_model with different annotation patterns."""

    def test_sync_resolve_belongs_to(self):
        class Target(RelationManagementMixin, BaseModel):
            id: int

        class Source(RelationManagementMixin, BaseModel):
            id: int
            target_id: int
            target: ClassVar[BelongsTo["Target"]] = BelongsTo(foreign_key="target_id")

        desc = Source.get_relation("target")
        model = desc.get_related_model(Source)
        assert model is Target

    def test_async_resolve_belongs_to(self):
        class Target(RelationManagementMixin, BaseModel):
            id: int

        class Source(RelationManagementMixin, BaseModel):
            id: int
            target_id: int
            target: ClassVar[AsyncBelongsTo["Target"]] = AsyncBelongsTo(foreign_key="target_id")

        desc = Source.get_relation("target")
        model = desc.get_related_model(Source)
        assert model is Target


# ==============================================================================
# 13. clear_cache on the bound relation method
# ==============================================================================


class TestRelationMethodClearCache:
    """Cover the clear_cache lambda on relation methods."""

    def test_sync_clear_cache(self):
        class Target(RelationManagementMixin, BaseModel):
            id: int

        class Source(RelationManagementMixin, BaseModel):
            id: int
            target_id: int
            target: ClassVar[BelongsTo["Target"]] = BelongsTo(foreign_key="target_id")

        instance = Source(id=1, target_id=1)
        InstanceCache.set(instance, "target", Target(id=1), CacheConfig())
        method = Source.target.__get__(instance, Source)
        method.clear_cache()
        assert InstanceCache.get(instance, "target", CacheConfig()) is None

    def test_async_clear_cache(self):
        class Target(RelationManagementMixin, BaseModel):
            id: int

        class Source(RelationManagementMixin, BaseModel):
            id: int
            target_id: int
            target: ClassVar[AsyncBelongsTo["Target"]] = AsyncBelongsTo(foreign_key="target_id")

        instance = Source(id=1, target_id=1)
        InstanceCache.set(instance, "target", Target(id=1), CacheConfig())
        method = Source.target.__get__(instance, Source)
        method.clear_cache()
        assert InstanceCache.get(instance, "target", CacheConfig()) is None
