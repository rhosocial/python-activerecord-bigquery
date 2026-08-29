# tests/providers/query.py
"""
Concrete implementation of the ``IQuerySyncProvider`` /
``IQueryAsyncProvider`` interfaces defined in the
``rhosocial-activerecord-testsuite`` package, for the BigQuery backend
(tested against the goccy/bigquery-emulator).

Adaptations from the MySQL reference provider
(``python-activerecord-mysql/tests/providers/query.py``):

* Raw DDL templates come from :mod:`providers.fixtures.query` as plain SQL
  strings (no ``CreateTableExpression``), with tables created
  dataset-qualified; models get ``__schema_name__`` set to the scenario dataset.
* No ``FOREIGN_KEY_CHECKS`` toggling and no AUTO_INCREMENT — BigQuery has no
  enforced foreign keys and the backend generates primary keys client-side.
* ``setup_json_user_fixtures`` does not probe for JSON type support: the
  fixture model declares JSON payload fields as ``str`` and the DDL uses
  ``STRING`` columns, so every enabled scenario qualifies.
"""

import logging
from typing import Dict, List, Optional, Set, Tuple, Type

from rhosocial.activerecord.model import ActiveRecord, AsyncActiveRecord

logger = logging.getLogger(__name__)

# Import models from the testsuite query fixtures, same strategy as basic.py.
# Python 3.14 here: the 3.12+ module is expected to load.
import importlib

_MODEL_NAMES = (
    "User", "JsonUser", "Order", "OrderItem", "Post", "Comment",
    "MappedUser", "MappedPost", "MappedComment",
)

_FIXTURE_MODULE_PREFIX = "rhosocial.activerecord.testsuite.feature.query.fixtures"
import sys

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
        logger.debug("query fixtures module %s unavailable: %s", _modname, e)
if _models_mod is None:
    _models_mod = importlib.import_module(f"{_FIXTURE_MODULE_PREFIX}.models")
logger.info("Selected BigQuery query fixtures from %s", _models_mod.__name__)

for _name in _MODEL_NAMES:
    globals()[_name] = getattr(_models_mod, _name)
del _name

# Async mapped models live in the base models module.
from rhosocial.activerecord.testsuite.feature.query.fixtures.models import (  # noqa: E402
    AsyncMappedUser,
    AsyncMappedPost,
    AsyncMappedComment,
)

from rhosocial.activerecord.testsuite.feature.query.fixtures.cte_models import Node  # noqa: E402
from rhosocial.activerecord.testsuite.feature.query.fixtures.extended_models import ExtendedOrder, ExtendedOrderItem  # noqa: E402

from rhosocial.activerecord.testsuite.feature.query.interfaces import (  # noqa: E402
    IQuerySyncProvider,
    IQueryAsyncProvider,
)

from .scenarios import get_enabled_scenarios, get_scenario  # noqa: E402
from .fixtures.query import TABLE_EXPRESSIONS  # noqa: E402
from ._reset import clear_table_candidates, ensure_table_created, ensure_table_created_async  # noqa: E402


def _dataset_of(config) -> Optional[str]:
    return getattr(config, "dataset", None) or None


class QueryProviderBase:
    def __init__(self):
        self._created_tables: Set[str] = set()

    def get_test_scenarios(self) -> List[str]:
        return list(get_enabled_scenarios().keys())

    def _table_ddl(self, dataset: Optional[str], table_name: str) -> str:
        if fn := TABLE_EXPRESSIONS.get(table_name):
            return fn(dataset, table_name)
        raise KeyError(f"No BigQuery DDL template registered for table '{table_name}'")

    @staticmethod
    def _track_backend(backend_instance, collection: List) -> None:
        if backend_instance not in collection:
            collection.append(backend_instance)

    def _set_schema(self, model_class: Type[ActiveRecord], dataset: Optional[str]) -> None:
        model_class.__schema_name__ = dataset


class QuerySyncProvider(QueryProviderBase, IQuerySyncProvider):
    def __init__(self):
        super().__init__()
        self._active_backends = []

    def _execute_ddl(self, backend, sql: str):
        from rhosocial.activerecord.backend.options import ExecutionOptions
        from rhosocial.activerecord.backend.schema import StatementType

        backend.execute(sql, options=ExecutionOptions(stmt_type=StatementType.DDL))

    def _reset_table(self, backend, dataset: Optional[str], table_name: str,
                     ddl: Optional[str] = None) -> None:
        # goccy/bigquery-emulator accumulates per-DDL metadata in its backing
        # sqlite store, so DROP+CREATE-per-test quickly degrades per-query
        # latency from ~0.3s to several seconds. The table is therefore
        # created once per pytest process and only cleared (TRUNCATE) between
        # tests.
        ddl_sql = ddl or self._table_ddl(dataset, table_name)
        qualified = ensure_table_created(
            lambda sql: self._execute_ddl(backend, sql),
            dataset, table_name, ddl_sql,
        )
        # BigQuery DELETE mandates a WHERE clause, so prefer TRUNCATE TABLE,
        # fall back to DELETE ... WHERE TRUE; final resort is DROP+CREATE
        # (recreated from the bare DDL below).
        cleared = False
        for sql in clear_table_candidates(backend.dialect, qualified):
            try:
                self._execute_ddl(backend, sql)
                cleared = True
                break
            except Exception:
                continue
        if not cleared:
            try:
                self._execute_ddl(backend, f"DROP TABLE IF EXISTS {qualified}")
            except Exception:
                pass
            self._execute_ddl(backend, ddl_sql)
        self._created_tables.add(table_name)

    def _setup_model(
        self, model_class: Type[ActiveRecord], scenario_name: str, table_name: str
    ) -> Type[ActiveRecord]:
        backend_class, config = get_scenario(scenario_name)
        model_class.configure(config, backend_class)
        backend_instance = model_class.__backend__
        self._track_backend(backend_instance, self._active_backends)
        self._set_schema(model_class, _dataset_of(config))
        self._reset_table(backend_instance, _dataset_of(config), table_name)
        return model_class

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
            self._reset_table(shared_backend, _dataset_of(shared_backend.config), table_name)
            result.append(model_class)
        return tuple(result)

    def setup_order_fixtures(
        self, scenario_name: str
    ) -> Tuple[Type[ActiveRecord], Type[ActiveRecord], Type[ActiveRecord]]:
        return self._setup_multiple_models(
            [(User, "users"), (Order, "orders"), (OrderItem, "order_items")], scenario_name
        )

    def setup_blog_fixtures(
        self, scenario_name: str
    ) -> Tuple[Type[ActiveRecord], Type[ActiveRecord], Type[ActiveRecord]]:
        return self._setup_multiple_models(
            [(User, "users"), (Post, "posts"), (Comment, "comments")], scenario_name
        )

    def setup_json_user_fixtures(self, scenario_name: str) -> Tuple[Type[ActiveRecord], ...]:
        json_user_model = self._setup_model(JsonUser, scenario_name, "json_users")
        return (json_user_model,)

    def setup_tree_fixtures(self, scenario_name: str) -> Tuple[Type[ActiveRecord], ...]:
        node_model = self._setup_model(Node, scenario_name, "nodes")
        return (node_model,)

    def setup_extended_order_fixtures(
        self, scenario_name: str
    ) -> Tuple[Type[ActiveRecord], Type[ActiveRecord], Type[ActiveRecord]]:
        return self._setup_multiple_models(
            [(User, "users"), (ExtendedOrder, "extended_orders"), (ExtendedOrderItem, "extended_order_items")],
            scenario_name,
        )

    def setup_combined_fixtures(
        self, scenario_name: str
    ) -> Tuple[Type[ActiveRecord], Type[ActiveRecord], Type[ActiveRecord], Type[ActiveRecord], Type[ActiveRecord]]:
        return self._setup_multiple_models(
            [(User, "users"), (Order, "orders"), (OrderItem, "order_items"), (Post, "posts"), (Comment, "comments")],
            scenario_name,
        )

    def setup_annotated_query_fixtures(self, scenario_name: str) -> Tuple[Type[ActiveRecord], ...]:
        from rhosocial.activerecord.testsuite.feature.query.fixtures.annotated_adapter_models import SearchableItem
        return self._setup_multiple_models(
            [(SearchableItem, "searchable_items")],
            scenario_name,
        )

    def setup_mapped_models(
        self, scenario_name: str
    ) -> Tuple[Type[ActiveRecord], Type[ActiveRecord], Type[ActiveRecord]]:
        return self._setup_multiple_models(
            [(MappedUser, "users"), (MappedPost, "posts"), (MappedComment, "comments")], scenario_name
        )

    def setup_profile_fixtures(
        self, scenario_name: str
    ) -> Tuple[Type[ActiveRecord], Type[ActiveRecord]]:
        Profile = User.get_relation('profile').get_related_model(User)
        return self._setup_multiple_models([(User, "users"), (Profile, "profiles")], scenario_name)

    def setup_order_item_model(self, scenario_name: str) -> Type[ActiveRecord]:
        from rhosocial.activerecord.testsuite.feature.basic.fixtures.models import (
            OrderItem as CompositeOrderItem,
        )
        from .fixtures.query import create_composite_order_items_table
        backend_class, config = get_scenario(scenario_name)
        CompositeOrderItem.configure(config, backend_class)
        backend_instance = CompositeOrderItem.__backend__
        self._track_backend(backend_instance, self._active_backends)
        self._set_schema(CompositeOrderItem, _dataset_of(config))
        self._reset_table(backend_instance, _dataset_of(config), "order_items",
                          ddl=create_composite_order_items_table(_dataset_of(config)))
        return CompositeOrderItem

    def cleanup_after_test(self, scenario_name: str):
        # Tables are NOT dropped here: goccy/bigquery-emulator degrades as DDL
        # metadata accumulates, so tables are created once per pytest process
        # and only cleared (TRUNCATE) between tests by _reset_table.
        for backend_instance in self._active_backends:
            try:
                backend_instance.disconnect()
            except Exception:
                pass
        self._active_backends.clear()
        self._created_tables.clear()


class QueryAsyncProvider(QueryProviderBase, IQueryAsyncProvider):
    def __init__(self):
        super().__init__()
        self._active_async_backends = []

    async def _execute_ddl_async(self, backend, sql: str):
        from rhosocial.activerecord.backend.options import ExecutionOptions
        from rhosocial.activerecord.backend.schema import StatementType

        await backend.execute(sql, options=ExecutionOptions(stmt_type=StatementType.DDL))

    async def _reset_table_async(self, backend, dataset: Optional[str], table_name: str,
                                 ddl: Optional[str] = None) -> None:
        # See the sync _reset_table for rationale on avoiding DROP+CREATE per
        # test against the goccy/bigquery-emulator.
        ddl_sql = ddl or self._table_ddl(dataset, table_name)
        qualified = await ensure_table_created_async(
            lambda sql: self._execute_ddl_async(backend, sql),
            dataset, table_name, ddl_sql,
        )
        # BigQuery DELETE mandates a WHERE clause, so prefer TRUNCATE TABLE,
        # fall back to DELETE ... WHERE TRUE; final resort is DROP+CREATE
        # (see _reset_table for full rationale).
        cleared = False
        for sql in clear_table_candidates(backend.dialect, qualified):
            try:
                await self._execute_ddl_async(backend, sql)
                cleared = True
                break
            except Exception:
                continue
        if not cleared:
            try:
                await self._execute_ddl_async(backend, f"DROP TABLE IF EXISTS {qualified}")
            except Exception:
                pass
            await self._execute_ddl_async(backend, ddl_sql)
        self._created_tables.add(table_name)

    def _configure_async_model(
        self, model_class: Type[ActiveRecord], config, shared_backend=None
    ):
        from rhosocial.activerecord.backend.impl.bigquery.async_backend import AsyncBigQueryBackend

        backend = shared_backend
        if backend is None:
            backend = AsyncBigQueryBackend(connection_config=config)
        model_class.__connection_config__ = config
        model_class.__backend_class__ = AsyncBigQueryBackend
        model_class.__backend__ = backend
        model_class.__schema_name__ = _dataset_of(config)
        return backend

    async def _setup_async_model(
        self, model_class: Type[ActiveRecord], scenario_name: str, table_name: str
    ) -> Type[ActiveRecord]:
        _, config = get_scenario(scenario_name)
        backend = self._configure_async_model(model_class, config)
        self._track_backend(backend, self._active_async_backends)
        await backend.connect()
        await self._reset_table_async(backend, _dataset_of(config), table_name)
        return model_class

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
            self._configure_async_model(model_class, first_model.__connection_config__, shared_backend)
            await self._reset_table_async(shared_backend, _dataset_of(shared_backend.config), table_name)
            result.append(model_class)
        return tuple(result)

    async def setup_order_fixtures(
        self, scenario_name: str
    ) -> Tuple[Type[ActiveRecord], Type[ActiveRecord], Type[ActiveRecord]]:
        from rhosocial.activerecord.testsuite.feature.query.fixtures.async_models import (
            AsyncUser,
            AsyncOrder,
            AsyncOrderItem,
        )
        return await self._setup_multiple_async_models(
            [(AsyncUser, "users"), (AsyncOrder, "orders"), (AsyncOrderItem, "order_items")], scenario_name
        )

    async def setup_blog_fixtures(
        self, scenario_name: str
    ) -> Tuple[Type[ActiveRecord], Type[ActiveRecord], Type[ActiveRecord]]:
        from rhosocial.activerecord.testsuite.feature.query.fixtures.async_blog_models import AsyncPost, AsyncComment
        from rhosocial.activerecord.testsuite.feature.query.fixtures.async_models import AsyncUser
        return await self._setup_multiple_async_models(
            [(AsyncUser, "users"), (AsyncPost, "posts"), (AsyncComment, "comments")], scenario_name
        )

    async def setup_json_user_fixtures(self, scenario_name: str) -> Tuple[Type[ActiveRecord], ...]:
        from rhosocial.activerecord.testsuite.feature.query.fixtures.async_json_models import AsyncJsonUser
        json_user_model = await self._setup_async_model(AsyncJsonUser, scenario_name, "json_users")
        return (json_user_model,)

    async def setup_tree_fixtures(self, scenario_name: str) -> Tuple[Type[ActiveRecord], ...]:
        from rhosocial.activerecord.testsuite.feature.query.fixtures.async_cte_models import AsyncNode
        node_model = await self._setup_async_model(AsyncNode, scenario_name, "nodes")
        return (node_model,)

    async def setup_extended_order_fixtures(
        self, scenario_name: str
    ) -> Tuple[Type[ActiveRecord], Type[ActiveRecord], Type[ActiveRecord]]:
        from rhosocial.activerecord.testsuite.feature.query.fixtures.async_extended_models import (
            AsyncUser,
            AsyncExtendedOrder,
            AsyncExtendedOrderItem,
        )
        return await self._setup_multiple_async_models(
            [
                (AsyncUser, "users"),
                (AsyncExtendedOrder, "extended_orders"),
                (AsyncExtendedOrderItem, "extended_order_items"),
            ],
            scenario_name,
        )

    async def setup_combined_fixtures(
        self, scenario_name: str
    ) -> Tuple[Type[ActiveRecord], Type[ActiveRecord], Type[ActiveRecord], Type[ActiveRecord], Type[ActiveRecord]]:
        from rhosocial.activerecord.testsuite.feature.query.fixtures.async_models import (
            AsyncUser,
            AsyncOrder,
            AsyncOrderItem,
        )
        from rhosocial.activerecord.testsuite.feature.query.fixtures.async_blog_models import AsyncPost, AsyncComment
        return await self._setup_multiple_async_models(
            [
                (AsyncUser, "users"),
                (AsyncOrder, "orders"),
                (AsyncOrderItem, "order_items"),
                (AsyncPost, "posts"),
                (AsyncComment, "comments"),
            ],
            scenario_name,
        )

    async def setup_annotated_query_fixtures(self, scenario_name: str) -> Tuple[Type[ActiveRecord], ...]:
        from rhosocial.activerecord.testsuite.feature.query.fixtures.async_annotated_adapter_models import (
            AsyncSearchableItem,
        )
        return await self._setup_multiple_async_models(
            [(AsyncSearchableItem, "searchable_items")],
            scenario_name,
        )

    async def setup_mapped_models(
        self, scenario_name: str
    ) -> Tuple[Type[ActiveRecord], Type[ActiveRecord], Type[ActiveRecord]]:
        return await self._setup_multiple_async_models(
            [(AsyncMappedUser, "users"), (AsyncMappedPost, "posts"), (AsyncMappedComment, "comments")], scenario_name
        )

    async def setup_profile_fixtures(
        self, scenario_name: str
    ) -> Tuple[Type[AsyncActiveRecord], Type[AsyncActiveRecord]]:
        from rhosocial.activerecord.testsuite.feature.query.fixtures.async_models import (
            AsyncUser,
            AsyncProfile,
        )
        return await self._setup_multiple_async_models(
            [(AsyncUser, "users"), (AsyncProfile, "profiles")], scenario_name
        )

    async def setup_order_item_model(self, scenario_name: str) -> Type[AsyncActiveRecord]:
        from rhosocial.activerecord.testsuite.feature.basic.fixtures.models import (
            AsyncOrderItem as AsyncCompositeOrderItem,
        )
        from .fixtures.query import create_composite_order_items_table
        _, config = get_scenario(scenario_name)
        backend = self._configure_async_model(AsyncCompositeOrderItem, config)
        self._track_backend(backend, self._active_async_backends)
        await backend.connect()
        await self._reset_table_async(backend, _dataset_of(config), "order_items",
                                      ddl=create_composite_order_items_table(_dataset_of(config)))
        return AsyncCompositeOrderItem

    async def cleanup_after_test(self, scenario_name: str):
        # Tables are NOT dropped here (see sync cleanup_after_test for the
        # rationale against per-test DDL against goccy/bigquery-emulator).
        for backend_instance in self._active_async_backends:
            try:
                await backend_instance.disconnect()
            except Exception:
                pass
        self._active_async_backends.clear()
        self._created_tables.clear()