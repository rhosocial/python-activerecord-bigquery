# tests/providers/relation.py
"""
Concrete implementation of the ``IRelationSyncProvider`` /
``IRelationAsyncProvider`` interfaces defined in the
``rhosocial-activerecord-testsuite`` package, for the BigQuery backend
(tested against the goccy/bigquery-emulator).

Mirrors the structure of the MySQL reference provider
(``python-activerecord-mysql/tests/providers/relation.py``), with these
BigQuery-specific adaptations:

* Raw DDL templates come from :mod:`providers.fixtures.relation` with tables
  created dataset-qualified; models get ``__schema_name__`` set to the
  scenario dataset because the anonymous emulator client has no default
  dataset.
* No ``FOREIGN_KEY_CHECKS`` toggling and no AUTO_INCREMENT — BigQuery has no
  enforced foreign keys and the backend generates primary keys client-side.
* ``get_test_scenarios`` does not probe for JSON support: the relation
  fixture models declare their JSON payload fields as ``str`` and the DDL
  uses ``STRING`` columns, so every enabled scenario qualifies.
"""

from typing import Dict, List, Set, Tuple, Type

from rhosocial.activerecord.model import ActiveRecord, AsyncActiveRecord
from rhosocial.activerecord.testsuite.feature.relation.interfaces import (
    IRelationSyncProvider,
    IRelationAsyncProvider,
)
from rhosocial.activerecord.testsuite.feature.relation.fixtures.models import (
    Employee,
    Department,
    Author,
    Book,
    Chapter,
    Profile,
    User,
    Post,
    Comment,
    AsyncUser,
    AsyncPost,
    AsyncComment,
    BoundaryOwner,
    BoundaryProfile,
    BoundaryPost,
    AsyncBoundaryOwner,
    AsyncBoundaryProfile,
    AsyncBoundaryPost,
)

from .scenarios import get_enabled_scenarios, get_scenario
from .fixtures.relation import TABLE_EXPRESSIONS


def _dataset_of(config) -> str:
    return getattr(config, "dataset", None) or None


_EMPLOYEE_DEPARTMENT_TABLES = ["employees", "departments"]
_AUTHOR_BOOK_TABLES = ["authors", "books", "chapters", "profiles"]
_USER_POST_COMMENT_TABLES = ["users", "posts", "comments"]
_RELATION_BOUNDARY_TABLES = [
    "relation_boundary_owners",
    "relation_boundary_profiles",
    "relation_boundary_posts",
]


class RelationProviderBase:
    def __init__(self):
        self._created_tables: Set[str] = set()

    def get_test_scenarios(self) -> List[str]:
        return list(get_enabled_scenarios().keys())

    def _table_ddl(self, dataset, table_name: str) -> str:
        if fn := TABLE_EXPRESSIONS.get(table_name):
            return fn(dataset, table_name)
        raise KeyError(f"No BigQuery DDL template registered for table '{table_name}'")


class RelationSyncProvider(RelationProviderBase, IRelationSyncProvider):
    def __init__(self):
        super().__init__()
        self._active_backends = []
        self._sync_user_post_comment_setup = False
        self._sync_relation_boundary_setup = False

    def _execute_ddl(self, backend, sql: str):
        from rhosocial.activerecord.backend.options import ExecutionOptions
        from rhosocial.activerecord.backend.schema import StatementType

        backend.execute(sql, options=ExecutionOptions(stmt_type=StatementType.DDL))

    def _reset_tables(self, backend, table_names):
        dataset = _dataset_of(backend.config)
        for table_name in table_names:
            qualified = f"`{dataset}`.`{table_name}`" if dataset else f"`{table_name}`"
            try:
                self._execute_ddl(backend, f"DROP TABLE IF EXISTS {qualified}")
            except Exception:
                pass
            self._execute_ddl(backend, self._table_ddl(dataset, table_name))
            self._created_tables.add(table_name)

    def _configure_with_shared_backend(self, model_class, config, backend_class, backend, dataset):
        model_class.__connection_config__ = config
        model_class.__backend_class__ = backend_class
        model_class.__backend__ = backend
        model_class.__schema_name__ = dataset

    def _setup_employee_department(self, scenario_name):
        backend_class, config = get_scenario(scenario_name)
        Employee.configure(config, backend_class)
        backend = Employee.backend()
        self._active_backends.append(backend)
        self._configure_with_shared_backend(Department, config, backend_class, backend, _dataset_of(config))
        Employee.__schema_name__ = _dataset_of(config)
        self._reset_tables(backend, _EMPLOYEE_DEPARTMENT_TABLES)
        return Employee, Department

    def _setup_author_book(self, scenario_name):
        backend_class, config = get_scenario(scenario_name)
        Author.configure(config, backend_class)
        backend = Author.backend()
        self._active_backends.append(backend)
        dataset = _dataset_of(config)
        Author.__schema_name__ = dataset
        self._configure_with_shared_backend(Book, config, backend_class, backend, dataset)
        self._configure_with_shared_backend(Chapter, config, backend_class, backend, dataset)
        self._configure_with_shared_backend(Profile, config, backend_class, backend, dataset)
        self._reset_tables(backend, _AUTHOR_BOOK_TABLES)
        return Author, Book, Chapter, Profile

    def _setup_user_post_comment_sync(self, scenario_name):
        if not self._sync_user_post_comment_setup:
            backend_class, config = get_scenario(scenario_name)
            User.configure(config, backend_class)
            backend = User.backend()
            self._active_backends.append(backend)
            dataset = _dataset_of(config)
            User.__schema_name__ = dataset
            self._configure_with_shared_backend(Post, config, backend_class, backend, dataset)
            self._configure_with_shared_backend(Comment, config, backend_class, backend, dataset)
            self._reset_tables(backend, _USER_POST_COMMENT_TABLES)
            self._sync_user_post_comment_setup = True

    def _setup_relation_boundary_sync(self, scenario_name):
        if not self._sync_relation_boundary_setup:
            backend_class, config = get_scenario(scenario_name)
            BoundaryOwner.configure(config, backend_class)
            backend = BoundaryOwner.backend()
            self._active_backends.append(backend)
            dataset = _dataset_of(config)
            BoundaryOwner.__schema_name__ = dataset
            self._configure_with_shared_backend(BoundaryProfile, config, backend_class, backend, dataset)
            self._configure_with_shared_backend(BoundaryPost, config, backend_class, backend, dataset)
            self._reset_tables(backend, _RELATION_BOUNDARY_TABLES)
            self._sync_relation_boundary_setup = True

    def setup_employee_department_fixtures(
        self,
        scenario_name: str,
    ) -> Tuple[Type[ActiveRecord], Type[ActiveRecord]]:
        return self._setup_employee_department(scenario_name)

    def setup_author_book_fixtures(
        self,
        scenario_name: str,
    ) -> Tuple[
        Type[ActiveRecord],
        Type[ActiveRecord],
        Type[ActiveRecord],
        Type[ActiveRecord],
    ]:
        return self._setup_author_book(scenario_name)

    def setup_user_model(self, scenario_name: str) -> Type[ActiveRecord]:
        self._setup_user_post_comment_sync(scenario_name)
        return User

    def setup_post_model(self, scenario_name: str) -> Type[ActiveRecord]:
        self._setup_user_post_comment_sync(scenario_name)
        return Post

    def setup_comment_model(self, scenario_name: str) -> Type[ActiveRecord]:
        self._setup_user_post_comment_sync(scenario_name)
        return Comment

    def setup_relation_boundary_fixtures(
        self,
        scenario_name: str,
    ) -> Tuple[Type[ActiveRecord], Type[ActiveRecord], Type[ActiveRecord]]:
        self._setup_relation_boundary_sync(scenario_name)
        return BoundaryOwner, BoundaryProfile, BoundaryPost

    def load_relation_boundary_dataset(self, scenario_name: str, dataset_name: str) -> Dict[str, int]:
        self._setup_relation_boundary_sync(scenario_name)
        return self._load_relation_boundary_dataset(dataset_name)

    def _load_relation_boundary_dataset(self, dataset_name):
        if dataset_name == "null_foreign_key":
            profile = BoundaryProfile(bio="No owner", owner_id=None)
            profile.save()
            return {"profile_id": profile.id}

        if dataset_name == "orphan_foreign_key":
            missing_owner_id = 999999
            post = BoundaryPost(title="Orphan post", owner_id=missing_owner_id)
            post.save()
            return {"post_id": post.id, "missing_owner_id": missing_owner_id}

        if dataset_name == "owner_without_children":
            owner = BoundaryOwner(name="Owner without children")
            owner.save()
            return {"owner_id": owner.id}

        if dataset_name == "multiple_has_one_matches":
            owner = BoundaryOwner(name="Owner with duplicate profiles")
            owner.save()
            first = BoundaryProfile(bio="First profile", owner_id=owner.id)
            first.save()
            second = BoundaryProfile(bio="Second profile", owner_id=owner.id)
            second.save()
            return {
                "owner_id": owner.id,
                "first_profile_id": first.id,
                "second_profile_id": second.id,
            }

        raise ValueError(f"Unknown relation boundary dataset: {dataset_name}")

    def _reset_sync_setup_state(self):
        self._sync_user_post_comment_setup = False
        self._sync_relation_boundary_setup = False

    def cleanup_after_test(self, scenario_name: str) -> None:
        for backend in self._active_backends:
            try:
                for table in list(self._created_tables):
                    try:
                        self._execute_ddl(backend, f"DROP TABLE IF EXISTS `{_dataset_of(backend.config)}`.`{table}`")
                    except Exception:
                        pass
            finally:
                try:
                    backend.disconnect()
                except Exception:
                    pass
        self._active_backends.clear()
        self._created_tables.clear()
        self._reset_sync_setup_state()


class RelationAsyncProvider(RelationProviderBase, IRelationAsyncProvider):
    def __init__(self):
        super().__init__()
        self._active_async_backends = []
        self._async_user_post_comment_setup = False
        self._async_relation_boundary_setup = False

    async def _execute_ddl_async(self, backend, sql: str):
        from rhosocial.activerecord.backend.options import ExecutionOptions
        from rhosocial.activerecord.backend.schema import StatementType

        await backend.execute(sql, options=ExecutionOptions(stmt_type=StatementType.DDL))

    async def _reset_tables_async(self, backend, table_names):
        dataset = _dataset_of(backend.config)
        for table_name in table_names:
            qualified = f"`{dataset}`.`{table_name}`" if dataset else f"`{table_name}`"
            try:
                await self._execute_ddl_async(backend, f"DROP TABLE IF EXISTS {qualified}")
            except Exception:
                pass
            await self._execute_ddl_async(backend, self._table_ddl(dataset, table_name))
            self._created_tables.add(table_name)

    def _configure_async_model(
        self, model_class, config, shared_backend=None
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

    async def _setup_employee_department_async(self, scenario_name):
        _, config = get_scenario(scenario_name)
        backend = self._configure_async_model(Employee, config)
        self._configure_async_model(Department, config, backend)
        self._active_async_backends.append(backend)
        await backend.connect()
        await self._reset_tables_async(backend, _EMPLOYEE_DEPARTMENT_TABLES)
        return Employee, Department

    async def _setup_author_book_async(self, scenario_name):
        _, config = get_scenario(scenario_name)
        backend = self._configure_async_model(Author, config)
        self._configure_async_model(Book, config, backend)
        self._configure_async_model(Chapter, config, backend)
        self._configure_async_model(Profile, config, backend)
        self._active_async_backends.append(backend)
        await backend.connect()
        await self._reset_tables_async(backend, _AUTHOR_BOOK_TABLES)
        return Author, Book, Chapter, Profile

    async def _setup_user_post_comment_async(self, scenario_name):
        if not self._async_user_post_comment_setup:
            _, config = get_scenario(scenario_name)
            backend = self._configure_async_model(AsyncUser, config)
            self._configure_async_model(AsyncPost, config, backend)
            self._configure_async_model(AsyncComment, config, backend)
            self._active_async_backends.append(backend)
            await backend.connect()
            await self._reset_tables_async(backend, _USER_POST_COMMENT_TABLES)
            self._async_user_post_comment_setup = True

    async def _setup_relation_boundary_async(self, scenario_name):
        if not self._async_relation_boundary_setup:
            _, config = get_scenario(scenario_name)
            backend = self._configure_async_model(AsyncBoundaryOwner, config)
            self._configure_async_model(AsyncBoundaryProfile, config, backend)
            self._configure_async_model(AsyncBoundaryPost, config, backend)
            self._active_async_backends.append(backend)
            await backend.connect()
            await self._reset_tables_async(backend, _RELATION_BOUNDARY_TABLES)
            self._async_relation_boundary_setup = True

    async def setup_employee_department_fixtures(
        self,
        scenario_name: str,
    ) -> Tuple[Type[ActiveRecord], Type[ActiveRecord]]:
        return await self._setup_employee_department_async(scenario_name)

    async def setup_author_book_fixtures(
        self,
        scenario_name: str,
    ) -> Tuple[
        Type[ActiveRecord],
        Type[ActiveRecord],
        Type[ActiveRecord],
        Type[ActiveRecord],
    ]:
        return await self._setup_author_book_async(scenario_name)

    async def setup_user_model(self, scenario_name: str) -> Type[AsyncActiveRecord]:
        await self._setup_user_post_comment_async(scenario_name)
        return AsyncUser

    async def setup_post_model(self, scenario_name: str) -> Type[AsyncActiveRecord]:
        await self._setup_user_post_comment_async(scenario_name)
        return AsyncPost

    async def setup_comment_model(self, scenario_name: str) -> Type[AsyncActiveRecord]:
        await self._setup_user_post_comment_async(scenario_name)
        return AsyncComment

    async def setup_relation_boundary_fixtures(
        self,
        scenario_name: str,
    ) -> Tuple[Type[AsyncActiveRecord], Type[AsyncActiveRecord], Type[AsyncActiveRecord]]:
        await self._setup_relation_boundary_async(scenario_name)
        return AsyncBoundaryOwner, AsyncBoundaryProfile, AsyncBoundaryPost

    async def load_relation_boundary_dataset(
        self,
        scenario_name: str,
        dataset_name: str,
    ) -> Dict[str, int]:
        await self._setup_relation_boundary_async(scenario_name)
        return await self._load_async_relation_boundary_dataset(dataset_name)

    async def _load_async_relation_boundary_dataset(self, dataset_name):
        if dataset_name == "null_foreign_key":
            profile = AsyncBoundaryProfile(bio="No owner", owner_id=None)
            await profile.save()
            return {"profile_id": profile.id}

        if dataset_name == "orphan_foreign_key":
            missing_owner_id = 999999
            post = AsyncBoundaryPost(title="Orphan post", owner_id=missing_owner_id)
            await post.save()
            return {"post_id": post.id, "missing_owner_id": missing_owner_id}

        if dataset_name == "owner_without_children":
            owner = AsyncBoundaryOwner(name="Owner without children")
            await owner.save()
            return {"owner_id": owner.id}

        if dataset_name == "multiple_has_one_matches":
            owner = AsyncBoundaryOwner(name="Owner with duplicate profiles")
            await owner.save()
            first = AsyncBoundaryProfile(bio="First profile", owner_id=owner.id)
            await first.save()
            second = AsyncBoundaryProfile(bio="Second profile", owner_id=owner.id)
            await second.save()
            return {
                "owner_id": owner.id,
                "first_profile_id": first.id,
                "second_profile_id": second.id,
            }

        raise ValueError(f"Unknown relation boundary dataset: {dataset_name}")

    def _reset_async_setup_state(self):
        self._async_user_post_comment_setup = False
        self._async_relation_boundary_setup = False

    async def cleanup_after_test(self, scenario_name: str):
        for backend in self._active_async_backends:
            try:
                for table in list(self._created_tables):
                    try:
                        await self._execute_ddl_async(
                            backend, f"DROP TABLE IF EXISTS `{_dataset_of(backend.config)}`.`{table}`"
                        )
                    except Exception:
                        pass
            finally:
                try:
                    await backend.disconnect()
                except Exception:
                    pass
        self._active_async_backends.clear()
        self._created_tables.clear()
        self._reset_async_setup_state()
