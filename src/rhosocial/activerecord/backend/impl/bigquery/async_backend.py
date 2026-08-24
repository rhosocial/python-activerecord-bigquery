"""BigQuery asynchronous backend implementation."""
from typing import Any, Dict, List, Optional, Tuple

from rhosocial.activerecord.backend.base import AsyncStorageBackend
from rhosocial.activerecord.backend.errors import ConnectionError, DatabaseError
from rhosocial.activerecord.backend.result import QueryResult

from .config import BigQueryConnectionConfig
from .dialect import BigQueryDialect
from .async_transaction import AsyncBigQueryTransactionManager


class AsyncBigQueryBackend(AsyncStorageBackend):
    """BigQuery native async backend."""

    def __init__(self, **kwargs):
        version = kwargs.pop('version', None) or (3, 0, 0)
        if 'connection_config' not in kwargs or kwargs.get('connection_config') is None:
            config_params = {
                'project': kwargs.get('project'),
                'dataset': kwargs.get('dataset'),
                'location': kwargs.get('location'),
                'credentials_path': kwargs.get('credentials_path'),
                'credentials_json': kwargs.get('credentials_json'),
                'api_endpoint': kwargs.get('api_endpoint'),
                'use_anonymous_credentials': kwargs.get('use_anonymous_credentials') or False,
            }
            config_params = {k: v for k, v in config_params.items() if v is not None}
            kwargs['connection_config'] = BigQueryConnectionConfig(**config_params)
        super().__init__(**kwargs)
        self._version = version
        # Monotonic per-column client-side PK counters (see insert()).
        self._pk_counters = {}
        # Keep the async backend's adapter registry in step with the sync one.
        from .backend import BigQueryBackend
        BigQueryBackend._register_bigquery_adapters(self)

    def get_default_adapter_suggestions(self) -> Dict:
        from .backend import BigQueryBackend
        return BigQueryBackend.get_default_adapter_suggestions(self)

    async def connect(self) -> None:
        try:
            from google.cloud import bigquery
            from google.auth.credentials import AnonymousCredentials
            from google.api_core.client_options import ClientOptions
            config = self.config
            endpoint = getattr(config, 'api_endpoint', None) or None
            use_anonymous = getattr(config, 'use_anonymous_credentials', False)
            client_options = ClientOptions(api_endpoint=endpoint) if endpoint else None
            if use_anonymous:
                self._client = bigquery.Client(
                    project=getattr(config, 'project', None) or 'test',
                    credentials=AnonymousCredentials(),
                    client_options=client_options,
                )
            elif getattr(config, 'credentials_path', None):
                self._client = bigquery.Client.from_service_account_json(
                    config.credentials_path, client_options=client_options)
            elif getattr(config, 'credentials_json', None):
                self._client = bigquery.Client.from_service_account_info(
                    config.credentials_json, client_options=client_options)
            else:
                project = getattr(config, 'project', None)
                self._client = bigquery.Client(project=project, client_options=client_options)
            self._connected = True
        except Exception as e:
            raise ConnectionError(f"Failed to connect to BigQuery: {e}") from e

    async def disconnect(self) -> None:
        if hasattr(self, '_client') and self._client:
            self._client = None
            self._connected = False

    async def ping(self, reconnect: bool = True) -> bool:
        if not hasattr(self, '_client') or self._client is None:
            if reconnect:
                await self.connect()
                return True
            return False
        try:
            dataset_ref = self._client.dataset(getattr(self.config, 'dataset', None) or 'default')
            list(self._client.list_dataset_refs(dataset_ref))
            return True
        except Exception:
            if reconnect:
                await self.disconnect()
                await self.connect()
                return True if self._client else False
            return False

    @property
    def transaction_manager(self):
        return AsyncBigQueryTransactionManager(self)

    @property
    def dialect(self) -> BigQueryDialect:
        return BigQueryDialect(version=self._version)

    async def execute(self, sql: str, params: Optional[Tuple] = None, returning: Optional[Any] = None, column_adapters: Optional[Dict] = None, *, options: Optional[Any] = None) -> QueryResult:
        from rhosocial.activerecord.backend.schema import StatementType
        from .backend import BigQueryBackend

        if options is not None:
            column_adapters = column_adapters or getattr(options, 'column_adapters', None)
            column_mapping = getattr(options, 'column_mapping', None)
            if getattr(options, 'process_result_set', None) is not None:
                is_select = options.process_result_set
            else:
                is_select = getattr(options, 'stmt_type', None) == StatementType.DQL
        else:
            column_mapping = None
            is_select = sql.strip().upper().startswith(("SELECT", "WITH"))
        try:
            if getattr(self.config, 'api_endpoint', None):
                # Emulator REST fast path: see BigQueryBackend.execute.
                return BigQueryBackend._execute_via_rest(
                    self, sql, params, is_select, column_adapters, column_mapping
                )
            if not getattr(self, '_connected', False) or getattr(self, '_client', None) is None:
                await self.connect()
            job_config = BigQueryBackend._build_job_config(params)
            job = self._client.query(sql, job_config=job_config)
            # Fail fast on job-level errors (see sync backend for rationale).
            if job.errors:
                exc = job.exception()
                if exc is not None:
                    raise exc
                from rhosocial.activerecord.backend.errors import DatabaseError
                raise DatabaseError(str(job.errors))
            if is_select:
                rows_iter = job.result()
                # See BigQueryBackend.execute: rows are converted to dicts and
                # run through type adapters / column mapping.
                adapters = column_adapters or {}
                mapping = column_mapping or {}
                rows = []
                for row in rows_iter:
                    row_dict = dict(row.items())
                    rows.append(self._remap_row_columns(self._adapt_row_types(row_dict, adapters), mapping))
                affected_rows = len(rows)
                result_data = rows
            else:
                job.result()
                affected_rows = job.num_dml_affected_rows or 0
                result_data = None
            duration = (job.ended - job.started).total_seconds() if job.started and job.ended else None
            return QueryResult(data=result_data, affected_rows=affected_rows, duration=duration)
        except Exception as e:
            self._handle_error(e)

    # -- Client-side PK generation (see BigQueryBackend for rationale) ----------

    async def _next_pk_value(self, table: str, schema_name, pk_column: str) -> int:
        from rhosocial.activerecord.backend.options import ExecutionOptions
        from rhosocial.activerecord.backend.schema import StatementType

        qualified = f"`{schema_name}`.`{table}`" if schema_name else f"`{table}`"
        sql = f"SELECT COALESCE(MAX(`{pk_column}`), 0) + 1 AS next_id FROM {qualified}"
        result = await self.execute(sql, options=ExecutionOptions(stmt_type=StatementType.DQL))
        row = result.data[0]
        value = row.get("next_id") if isinstance(row, dict) else row[0]
        key = (schema_name, table, pk_column)
        value = max(int(value), self._pk_counters.get(key, 0) + 1)
        self._pk_counters[key] = value
        return value

    async def insert(self, options) -> QueryResult:
        from dataclasses import replace

        pk = getattr(options, 'primary_key', None)
        data = options.data
        if pk and isinstance(pk, str) and data.get(pk) is None:
            new_id = await self._next_pk_value(options.table, options.schema_name, pk)
            options = replace(options, data={**data, pk: new_id})
            result = await super().insert(options)
            result.last_insert_id = new_id
        else:
            result = await super().insert(options)
        if result.affected_rows == 0 and self._is_emulator_mode():
            result.affected_rows = 1
        return result

    async def bulk_insert(self, options) -> QueryResult:
        from dataclasses import replace

        pk = getattr(options, 'primary_key', None)
        if pk and isinstance(pk, str) and options.rows:
            columns = list(options.columns or [])
            if pk not in columns:
                # See BigQueryBackend.bulk_insert: the model layer omits unset
                # pk fields from the column list entirely.
                start = await self._next_pk_value(options.table, options.schema_name, pk)
                count = len(options.rows)
                self._pk_counters[(options.schema_name, options.table, pk)] = start + count - 1
                new_rows = [list(row) + [start + i] for i, row in enumerate(options.rows)]
                options = replace(options, columns=columns + [pk], rows=new_rows)
                result = await super().bulk_insert(options)
                result.last_insert_id = start
            else:
                idx = columns.index(pk)
                missing = [i for i, row in enumerate(options.rows)
                           if idx < len(row) and row[idx] is None]
                if missing:
                    start = await self._next_pk_value(options.table, options.schema_name, pk)
                    self._pk_counters[(options.schema_name, options.table, pk)] = start + len(missing) - 1
                    new_rows = [list(row) for row in options.rows]
                    for offset, row_idx in enumerate(missing):
                        new_rows[row_idx][idx] = start + offset
                    options = replace(options, rows=new_rows)
                    result = await super().bulk_insert(options)
                    result.last_insert_id = start
                else:
                    result = await super().bulk_insert(options)
        else:
            result = await super().bulk_insert(options)
        if result.affected_rows == 0 and self._is_emulator_mode():
            result.affected_rows = len(options.rows)
        return result

    async def bulk_update(self, options) -> QueryResult:
        # See BigQueryBackend.bulk_update: explicit ELSE branch per CASE.
        from rhosocial.activerecord.backend.expression import (
            Column, Literal, UpdateExpression, TableExpression, ComparisonPredicate, InPredicate,
        )
        from rhosocial.activerecord.backend.expression.advanced_functions import CaseExpression
        from rhosocial.activerecord.backend.options import ExecutionOptions
        from rhosocial.activerecord.backend.schema import StatementType

        pk_col = Column(self.dialect, options.pk_column)
        assignments = {}
        for field_name, values in options.field_values.items():
            cases = []
            for pk_val, field_val in zip(options.pk_values, values):
                condition = ComparisonPredicate(self.dialect, "=", pk_col, Literal(self.dialect, pk_val))
                result_expr = Literal(self.dialect, field_val)
                cases.append((condition, result_expr))
            assignments[field_name] = CaseExpression(
                self.dialect, cases=cases, else_result=Column(self.dialect, field_name),
            )

        pk_literals = Literal(self.dialect, options.pk_values)
        where_predicate = InPredicate(self.dialect, pk_col, pk_literals)
        update_expr = UpdateExpression(
            dialect=self.dialect,
            table=TableExpression(self.dialect, options.table, schema_name=options.schema_name)
            if options.schema_name
            else options.table,
            assignments=assignments,
            where=where_predicate,
        )
        sql, params = update_expr.to_sql()
        exec_options = ExecutionOptions(
            stmt_type=StatementType.DML,
            column_adapters=options.column_adapters,
            column_mapping=options.column_mapping,
        )
        result = await self.execute(sql, params, options=exec_options)
        if options.auto_commit:
            self._handle_auto_commit_if_needed()
        if result.affected_rows == 0 and self._is_emulator_mode():
            result.affected_rows = len(getattr(options, "pk_values", None) or [])
        return result

    # -- Emulator DML row-count fallback (see BigQueryBackend) -------------------

    def _is_emulator_mode(self) -> bool:
        return bool(getattr(self.config, 'api_endpoint', None))

    async def _count_matching(self, table: str, schema_name, where):
        if where is None:
            return None
        from rhosocial.activerecord.backend.options import ExecutionOptions
        from rhosocial.activerecord.backend.schema import StatementType

        where_sql, params = where.to_sql()
        stripped = where_sql.strip()
        if stripped.upper().startswith("WHERE "):
            where_sql = stripped[5:].strip()
        qualified = f"`{schema_name}`.`{table}`" if schema_name else f"`{table}`"
        sql = f"SELECT COUNT(*) AS n FROM {qualified} WHERE {where_sql}"
        result = await self.execute(sql, params, options=ExecutionOptions(stmt_type=StatementType.DQL))
        if not result.data:
            return None
        row = result.data[0]
        value = row.get("n") if isinstance(row, dict) else row[0]
        return int(value)

    async def update(self, options) -> QueryResult:
        matched = None
        if self._is_emulator_mode():
            matched = await self._count_matching(options.table, options.schema_name, options.where)
        result = await super().update(options)
        if result.affected_rows == 0 and matched:
            result.affected_rows = matched
        return result

    async def delete(self, options) -> QueryResult:
        matched = None
        if self._is_emulator_mode():
            matched = await self._count_matching(options.table, options.schema_name, options.where)
        result = await super().delete(options)
        if result.affected_rows == 0 and matched:
            result.affected_rows = matched
        return result

    def _handle_error(self, error: Exception) -> None:
        from rhosocial.activerecord.backend.errors import (
            ConnectionError, IntegrityError, QueryError, DatabaseError,
        )
        category = self._classify_error(error)
        if category == 'connection':
            raise ConnectionError(str(error)) from error
        elif category == 'integrity':
            raise IntegrityError(str(error)) from error
        elif category == 'query':
            raise QueryError(str(error)) from error
        else:
            raise DatabaseError(str(error)) from error

    def _classify_error(self, error: Exception) -> str:
        """Classify a google-cloud / google-api-core exception into an
        error category used by :meth:`_handle_error`.

        Returns one of: 'connection', 'integrity', 'query', 'generic'.
        """
        try:
            from google.api_core import exceptions as gexc
        except ImportError:  # google-cloud-bigquery not installed
            return 'generic'

        if isinstance(error, gexc.InternalServerError):
            # BigQuery (and the emulator) often reports query analysis /
            # execution failures as jobInternalError 500s; only treat a bare
            # internal error as a connection problem.
            msg = str(error).lower()
            integrity_hints = ('constraint failed', 'duplicate', 'not null',
                               'primary key', 'foreign key', 'unique')
            query_hints = ('failed to analyze', 'failed to parse', 'failed to exec',
                           'not found', 'syntax error', 'unrecognized', 'invalid',
                           'type mismatch', 'no such table', 'already exists')
            if any(h in msg for h in integrity_hints):
                return 'integrity'
            if any(h in msg for h in query_hints):
                return 'query'
            return 'connection'
        if isinstance(error, (
            gexc.ServiceUnavailable, gexc.DeadlineExceeded, gexc.GatewayTimeout,
            gexc.Aborted, gexc.Unauthenticated,
            gexc.ResourceExhausted, gexc.TooManyRequests,
        )):
            return 'connection'
        if isinstance(error, (gexc.AlreadyExists, gexc.FailedPrecondition,
                              gexc.PermissionDenied)):
            return 'integrity'
        if isinstance(error, (gexc.BadRequest, gexc.InvalidArgument,
                              gexc.NotFound)):
            msg = str(error).lower()
            if any(k in msg for k in ('duplicate', 'constraint', 'primary key',
                                      'foreign key', 'not null')):
                return 'integrity'
            return 'query'
        return 'generic'

    def get_server_version(self) -> Tuple[int, ...]:
        return self._version

    async def introspect_and_adapt(self) -> None:
        """See :meth:`BigQueryBackend.introspect_and_adapt`."""
        if not getattr(self, '_client', None):
            return
        import logging
        try:
            dataset_name = getattr(self.config, 'dataset', None)
            if dataset_name:
                self._client.get_dataset(dataset_name)
            else:
                list(self._client.list_datasets(max_results=1))
        except Exception as e:
            self.log(logging.WARNING, f"BigQuery introspection failed: {e}")
