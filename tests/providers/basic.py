# tests/providers/basic.py
"""
Concrete implementation of the ``IBasicSyncProvider`` / ``IBasicAsyncProvider``
interfaces defined in the ``rhosocial-activerecord-testsuite`` package, for the
BigQuery backend (tested against the goccy/bigquery-emulator).

Responsibilities:
1.  Report available test scenarios (BigQuery emulator configurations).
2.  Set up the database environment for a test: build the backend from the
    scenario config, configure the ActiveRecord model, and (re)create the
    table in the scenario's dataset.
3.  Clean up (drop tables, disconnect) after each test.

Backend-specific adaptations compared to the MySQL reference provider:

* Tables are created dataset-qualified (``<scenario dataset>.<table>``) and
  models get ``__schema_name__`` set to the scenario dataset, because the
  anonymous emulator client has no default dataset.
* DDL is emitted from raw SQL templates in
  :mod:`providers.fixtures.basic` (no DEFAULT/UNIQUE/INDEX/FK clauses —
  the emulator rejects or ignores them; BigQuery has no AUTO_INCREMENT and
  primary keys are generated client-side by the backend).
"""

import logging
from typing import List, Optional, Set, Tuple, Type

from rhosocial.activerecord.backend.type_adapter import BaseSQLTypeAdapter
from rhosocial.activerecord.model import ActiveRecord

logger = logging.getLogger(__name__)

# Resolve the newest fixture model module available for this interpreter, the
# same way the other backend providers do (Python is 3.14 here, so the 3.12+
# module is expected to load).
import importlib
import sys

_MODEL_NAMES = (
    "User", "AsyncUser",
    "TypeCase", "AsyncTypeCase",
    "TypeTestModel", "AsyncTypeTestModel",
    "ValidatedFieldUser", "AsyncValidatedFieldUser",
    "ValidatedUser", "AsyncValidatedUser",
    "PydanticValidatedModel", "AsyncPydanticValidatedModel",
    "TypeAdapterTest", "AsyncTypeAdapterTest",
    "MappedUser", "AsyncMappedUser",
    "MappedPost", "AsyncMappedPost",
    "MappedComment", "AsyncMappedComment",
    "ColumnMappingModel", "AsyncColumnMappingModel",
    "MixedAnnotationModel", "AsyncMixedAnnotationModel",
    "BulkUser", "AsyncBulkUser",
    "YesOrNoBooleanAdapter",
)

_FIXTURE_MODULE_PREFIX = "rhosocial.activerecord.testsuite.feature.basic.fixtures"
# Only probe fixture modules compatible with the running interpreter;
# models_py312 uses PEP 695 syntax and would raise SyntaxError on < 3.12.
_MODNAME_CANDIDATES = ["models"]
if sys.version_info >= (3, 10):
    _MODNAME_CANDIDATES.insert(0, "models_py310")
if sys.version_info >= (3, 11):
    _MODNAME_CANDIDATES.insert(0, "models_py311")
if sys.version_info >= (3, 12):
    _MODNAME_CANDIDATES.insert(0, "models_py312")
_models_mod = None
for _modname in _MODNAME_CANDIDATES:
    try:
        _candidate = importlib.import_module(f"{_FIXTURE_MODULE_PREFIX}.{_modname}")
        if all(hasattr(_candidate, n) for n in _MODEL_NAMES):
            _models_mod = _candidate
            break
    except (ImportError, SyntaxError) as e:
        logger.debug("fixtures module %s unavailable: %s", _modname, e)
if _models_mod is None:
    _models_mod = importlib.import_module(f"{_FIXTURE_MODULE_PREFIX}.models")
logger.info("Selected BigQuery basic fixtures from %s", _models_mod.__name__)

for _name in _MODEL_NAMES:
    globals()[_name] = getattr(_models_mod, _name)
del _name

# Composite-PK and derived-field models live in the base fixtures module and
# are shared across Python versions.
from rhosocial.activerecord.testsuite.feature.basic.fixtures.models import (  # noqa: E402
    OrderItem as CompositeOrderItem,
    AsyncOrderItem as AsyncCompositeOrderItem,
    StoreInventory as StoreInventoryModel,
    AsyncStoreInventory as AsyncStoreInventoryModel,
    Order as OrderModel,
    AsyncOrder as AsyncOrderModel,
    MappedOrderItem as MappedOrderItemModel,
    AsyncMappedOrderItem as AsyncMappedOrderItemModel,
    Product as ProductModel,
    AsyncProduct as AsyncProductModel,
    ProductFormA as ProductFormAModel,
    AsyncProductFormA as AsyncProductFormAModel,
    ProductWithProxy as ProductWithProxyModel,
    AsyncProductWithProxy as AsyncProductWithProxyModel,
    ProductWithColumnAndAdapter as ProductWithColumnAndAdapterModel,
    AsyncProductWithColumnAndAdapter as AsyncProductWithColumnAndAdapterModel,
)

from rhosocial.activerecord.testsuite.feature.basic.interfaces import (  # noqa: E402
    IBasicSyncProvider,
    IBasicAsyncProvider,
)

from .scenarios import get_enabled_scenarios, get_scenario  # noqa: E402
from .fixtures.basic import TABLE_EXPRESSIONS  # noqa: E402


def _dataset_of(config) -> Optional[str]:
    return getattr(config, "dataset", None) or None


class BasicProviderBase:
    def __init__(self):
        self._created_tables: Set[str] = set()

    def get_test_scenarios(self) -> List[str]:
        return list(get_enabled_scenarios().keys())

    def get_yes_no_adapter(self) -> "BaseSQLTypeAdapter":
        return YesOrNoBooleanAdapter()

    def get_dialect(self, scenario_name: str = "default"):
        """Return a bare, fully-constructed BigQuery dialect instance.

        Used by the ``feature/basic/ddl`` subtopic (expression/dialect
        contract).
        """
        from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect

        return BigQueryDialect(version=(3, 0, 0))

    @staticmethod
    def _track_backend(backend_instance, collection: List) -> None:
        if backend_instance not in collection:
            collection.append(backend_instance)

    def _set_schema(self, model_class: Type[ActiveRecord], dataset: Optional[str]) -> None:
        # Qualify all model SQL with the scenario dataset; without it the
        # emulator client would resolve bare table names against nothing.
        model_class.__schema_name__ = dataset

    def _table_ddl(self, dataset: Optional[str], table_name: str) -> str:
        if fn := TABLE_EXPRESSIONS.get(table_name):
            return fn(dataset, table_name)
        raise KeyError(f"No BigQuery DDL template registered for table '{table_name}'")


class BasicSyncProvider(BasicProviderBase, IBasicSyncProvider):
    def __init__(self):
        super().__init__()
        self._active_backends = []

    def _setup_model(self, model_class: Type[ActiveRecord], scenario_name: str, table_name: str) -> Type[ActiveRecord]:
        backend_class, config = get_scenario(scenario_name)
        model_class.configure(config, backend_class)
        backend_instance = model_class.__backend__
        self._track_backend(backend_instance, self._active_backends)
        self._set_schema(model_class, _dataset_of(config))
        self._reset_table_sync(model_class, table_name)
        self._created_tables.add(table_name)
        return model_class

    def _reset_table_sync(self, model_class: Type[ActiveRecord], table_name: str) -> None:
        from rhosocial.activerecord.backend.options import ExecutionOptions
        from rhosocial.activerecord.backend.schema import StatementType
        from rhosocial.activerecord.backend.expression import DropTableExpression, TableExpression

        options = ExecutionOptions(stmt_type=StatementType.DDL)
        backend = model_class.__backend__
        dataset = _dataset_of(backend.config)
        try:
            drop_expr = DropTableExpression(
                dialect=backend.dialect,
                table=TableExpression(backend.dialect, table_name, schema_name=dataset),
                if_exists=True,
            )
            backend.execute(*drop_expr.to_sql(), options=options)
        except Exception:
            qualified = f"`{dataset}`.`{table_name}`" if dataset else f"`{table_name}`"
            backend.execute(f"DROP TABLE IF EXISTS {qualified}", options=options)
        backend.execute(self._table_ddl(dataset, table_name), options=options)

    def _initialize_model_schema(self, model_class: Type[ActiveRecord], table_name: str) -> None:
        self._reset_table_sync(model_class, table_name)

    def _setup_multiple_models(
        self, model_classes: List[Tuple[Type[ActiveRecord], str]], scenario_name: str
    ) -> Tuple[Type[ActiveRecord], ...]:
        if not model_classes:
            return tuple()
        first_model_class, first_table_name = model_classes[0]
        first_model = self._setup_model(first_model_class, scenario_name, first_table_name)
        shared_backend = first_model.__backend__
        result = [first_model]
        for model_class, table_name in model_classes[1:]:
            model_class.__connection_config__ = first_model.__connection_config__
            model_class.__backend_class__ = first_model.__backend_class__
            model_class.__backend__ = shared_backend
            model_class.__schema_name__ = first_model.__schema_name__
            self._track_backend(shared_backend, self._active_backends)
            self._initialize_model_schema(model_class, table_name)
            self._created_tables.add(table_name)
            result.append(model_class)
        return tuple(result)

    def setup_user_model(self, scenario_name: str) -> Type[ActiveRecord]:
        return self._setup_model(User, scenario_name, "users")

    def setup_type_case_model(self, scenario_name: str) -> Type[ActiveRecord]:
        return self._setup_model(TypeCase, scenario_name, "type_cases")

    def setup_type_test_model(self, scenario_name: str) -> Type[ActiveRecord]:
        return self._setup_model(TypeTestModel, scenario_name, "type_tests")

    def setup_validated_field_user_model(self, scenario_name: str) -> Type[ActiveRecord]:
        return self._setup_model(ValidatedFieldUser, scenario_name, "validated_field_users")

    def setup_validated_user_model(self, scenario_name: str) -> Type[ActiveRecord]:
        return self._setup_model(ValidatedUser, scenario_name, "validated_users")

    def setup_pydantic_validated_model(self, scenario_name: str) -> Type[ActiveRecord]:
        return self._setup_model(PydanticValidatedModel, scenario_name, "pydantic_validated_models")

    def setup_mapped_models(
        self, scenario_name: str
    ) -> Tuple[Type[ActiveRecord], Type[ActiveRecord], Type[ActiveRecord]]:
        return self._setup_multiple_models(
            [(MappedUser, "users"), (MappedPost, "posts"), (MappedComment, "comments")], scenario_name
        )

    def setup_mixed_models(self, scenario_name: str) -> Tuple[Type[ActiveRecord], ...]:
        return self._setup_multiple_models(
            [(ColumnMappingModel, "column_mapping_items"), (MixedAnnotationModel, "mixed_annotation_items")],
            scenario_name,
        )

    def setup_type_adapter_model_and_schema(self, scenario_name: Optional[str] = None) -> Type[ActiveRecord]:
        if scenario_name is None:
            scenarios = self.get_test_scenarios()
            scenario_name = scenarios[0] if scenarios else "default"
        return self._setup_model(TypeAdapterTest, scenario_name, "type_adapter_tests")

    def setup_bulk_user_model(self, scenario_name: str) -> Type[ActiveRecord]:
        return self._setup_model(BulkUser, scenario_name, "bulk_users")

    # --- Composite PK setup methods ---

    def setup_order_item_model(self, scenario_name: str) -> Type[ActiveRecord]:
        return self._setup_model(CompositeOrderItem, scenario_name, "order_items")

    def setup_order_model(self, scenario_name: str) -> Type[ActiveRecord]:
        return self._setup_model(OrderModel, scenario_name, "orders")

    def setup_mapped_order_item_model(self, scenario_name: str) -> Type[ActiveRecord]:
        return self._setup_model(MappedOrderItemModel, scenario_name, "order_items")

    # --- Derived field setup methods ---

    def setup_product_model(self, scenario_name: str) -> Type[ActiveRecord]:
        return self._setup_model(ProductModel, scenario_name, "product")

    def setup_product_form_a_model(self, scenario_name: str) -> Type[ActiveRecord]:
        return self._setup_model(ProductFormAModel, scenario_name, "product")

    def setup_product_with_proxy_model(self, scenario_name: str) -> Type[ActiveRecord]:
        return self._setup_model(ProductWithProxyModel, scenario_name, "product")

    def setup_product_with_column_and_adapter_model(self, scenario_name: str) -> Type[ActiveRecord]:
        return self._setup_model(ProductWithColumnAndAdapterModel, scenario_name, "product")

    def cleanup_after_test(self, scenario_name: str):
        from rhosocial.activerecord.backend.options import ExecutionOptions
        from rhosocial.activerecord.backend.schema import StatementType

        options = ExecutionOptions(stmt_type=StatementType.DDL)
        for backend_instance in self._active_backends:
            dataset = _dataset_of(backend_instance.config)
            for table_name in list(self._created_tables):
                qualified = f"`{dataset}`.`{table_name}`" if dataset else f"`{table_name}`"
                try:
                    backend_instance.execute(f"DROP TABLE IF EXISTS {qualified}", options=options)
                except Exception:
                    pass
            try:
                backend_instance.disconnect()
            except Exception:
                pass
        self._active_backends.clear()
        self._created_tables.clear()


class BasicAsyncProvider(BasicProviderBase, IBasicAsyncProvider):
    def __init__(self):
        super().__init__()
        self._active_async_backends = []

    async def get_dialect(self, scenario_name: str = "default"):
        """Async mirror of ``BasicProviderBase.get_dialect``."""
        return super().get_dialect(scenario_name)

    async def _setup_async_model(
        self, model_class: Type[ActiveRecord], scenario_name: str, table_name: str
    ) -> Type[ActiveRecord]:
        from rhosocial.activerecord.backend.impl.bigquery.async_backend import AsyncBigQueryBackend

        _, config = get_scenario(scenario_name)
        await model_class.configure(config, AsyncBigQueryBackend)
        backend_instance = model_class.__backend__
        self._track_backend(backend_instance, self._active_async_backends)
        self._set_schema(model_class, _dataset_of(config))
        await self._reset_table_async(model_class, table_name)
        self._created_tables.add(table_name)
        return model_class

    async def _reset_table_async(self, model_class: Type[ActiveRecord], table_name: str) -> None:
        from rhosocial.activerecord.backend.options import ExecutionOptions
        from rhosocial.activerecord.backend.schema import StatementType
        from rhosocial.activerecord.backend.expression import DropTableExpression, TableExpression

        options = ExecutionOptions(stmt_type=StatementType.DDL)
        backend = model_class.__backend__
        dataset = _dataset_of(backend.config)
        try:
            drop_expr = DropTableExpression(
                dialect=backend.dialect,
                table=TableExpression(backend.dialect, table_name, schema_name=dataset),
                if_exists=True,
            )
            await backend.execute(*drop_expr.to_sql(), options=options)
        except Exception:
            qualified = f"`{dataset}`.`{table_name}`" if dataset else f"`{table_name}`"
            await backend.execute(f"DROP TABLE IF EXISTS {qualified}", options=options)
        await backend.execute(self._table_ddl(dataset, table_name), options=options)

    async def _initialize_async_model_schema(self, model_class: Type[ActiveRecord], table_name: str):
        await self._reset_table_async(model_class, table_name)

    async def _setup_multiple_async_models(
        self, model_classes: List[Tuple[Type[ActiveRecord], str]], scenario_name: str
    ) -> Tuple[Type[ActiveRecord], ...]:
        if not model_classes:
            return tuple()
        first_model_class, first_table_name = model_classes[0]
        first_model = await self._setup_async_model(first_model_class, scenario_name, first_table_name)
        shared_backend = first_model.__backend__
        result = [first_model]
        for model_class, table_name in model_classes[1:]:
            model_class.__connection_config__ = first_model.__connection_config__
            model_class.__backend_class__ = first_model.__backend_class__
            model_class.__backend__ = shared_backend
            model_class.__schema_name__ = first_model.__schema_name__
            await self._initialize_async_model_schema(model_class, table_name)
            self._created_tables.add(table_name)
            result.append(model_class)
        return tuple(result)

    async def setup_user_model(self, scenario_name: str) -> Type[ActiveRecord]:
        return await self._setup_async_model(AsyncUser, scenario_name, "users")

    async def setup_type_case_model(self, scenario_name: str) -> Type[ActiveRecord]:
        return await self._setup_async_model(AsyncTypeCase, scenario_name, "type_cases")

    async def setup_type_test_model(self, scenario_name: str) -> Type[ActiveRecord]:
        return await self._setup_async_model(AsyncTypeTestModel, scenario_name, "type_tests")

    async def setup_validated_field_user_model(self, scenario_name: str) -> Type[ActiveRecord]:
        return await self._setup_async_model(AsyncValidatedFieldUser, scenario_name, "validated_field_users")

    async def setup_validated_user_model(self, scenario_name: str) -> Type[ActiveRecord]:
        return await self._setup_async_model(AsyncValidatedUser, scenario_name, "validated_users")

    async def setup_pydantic_validated_model(self, scenario_name: str) -> Type[ActiveRecord]:
        return await self._setup_async_model(AsyncPydanticValidatedModel, scenario_name, "pydantic_validated_models")

    async def setup_mapped_models(
        self, scenario_name: str
    ) -> Tuple[Type[ActiveRecord], Type[ActiveRecord], Type[ActiveRecord]]:
        return await self._setup_multiple_async_models(
            [(AsyncMappedUser, "users"), (AsyncMappedPost, "posts"), (AsyncMappedComment, "comments")],
            scenario_name,
        )

    async def setup_mixed_models(self, scenario_name: str) -> Tuple[Type[ActiveRecord], ...]:
        return await self._setup_multiple_async_models(
            [(AsyncColumnMappingModel, "column_mapping_items"), (AsyncMixedAnnotationModel, "mixed_annotation_items")],
            scenario_name,
        )

    async def setup_type_adapter_model_and_schema(self, scenario_name: str) -> Type[ActiveRecord]:
        return await self._setup_async_model(AsyncTypeAdapterTest, scenario_name, "type_adapter_tests")

    async def setup_bulk_user_model(self, scenario_name: str) -> Type[ActiveRecord]:
        return await self._setup_async_model(AsyncBulkUser, scenario_name, "bulk_users")

    # --- Composite PK setup methods ---

    async def setup_order_item_model(self, scenario_name: str) -> Type[ActiveRecord]:
        return await self._setup_async_model(AsyncCompositeOrderItem, scenario_name, "order_items")

    async def setup_order_model(self, scenario_name: str) -> Type[ActiveRecord]:
        return await self._setup_async_model(AsyncOrderModel, scenario_name, "orders")

    async def setup_mapped_order_item_model(self, scenario_name: str) -> Type[ActiveRecord]:
        return await self._setup_async_model(AsyncMappedOrderItemModel, scenario_name, "order_items")

    # --- Derived field setup methods ---

    async def setup_product_model(self, scenario_name: str) -> Type[ActiveRecord]:
        return await self._setup_async_model(AsyncProductModel, scenario_name, "product")

    async def setup_product_form_a_model(self, scenario_name: str) -> Type[ActiveRecord]:
        return await self._setup_async_model(AsyncProductFormAModel, scenario_name, "product")

    async def setup_product_with_proxy_model(self, scenario_name: str) -> Type[ActiveRecord]:
        return await self._setup_async_model(AsyncProductWithProxyModel, scenario_name, "product")

    async def setup_product_with_column_and_adapter_model(self, scenario_name: str) -> Type[ActiveRecord]:
        return await self._setup_async_model(AsyncProductWithColumnAndAdapterModel, scenario_name, "product")

    async def cleanup_after_test(self, scenario_name: str):
        from rhosocial.activerecord.backend.options import ExecutionOptions
        from rhosocial.activerecord.backend.schema import StatementType

        options = ExecutionOptions(stmt_type=StatementType.DDL)
        for backend_instance in self._active_async_backends:
            dataset = _dataset_of(backend_instance.config)
            for table_name in list(self._created_tables):
                qualified = f"`{dataset}`.`{table_name}`" if dataset else f"`{table_name}`"
                try:
                    await backend_instance.execute(f"DROP TABLE IF EXISTS {qualified}", options=options)
                except Exception:
                    pass
            try:
                await backend_instance.disconnect()
            except Exception:
                pass
        self._active_async_backends.clear()
        self._created_tables.clear()
