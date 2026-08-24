"""BigQuery synchronous backend implementation."""
import logging
from typing import Any, Dict, List, Optional, Tuple

from rhosocial.activerecord.backend.base import StorageBackend
from rhosocial.activerecord.backend.errors import (
    ConnectionError, DatabaseError, IntegrityError, QueryError,
)
from rhosocial.activerecord.backend.result import QueryResult

from .config import BigQueryConnectionConfig
from .dialect import BigQueryDialect
from .transaction import BigQueryTransactionManager


class BigQueryBackend(StorageBackend):
    """BigQuery-specific backend (synchronous)."""

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
        self._register_bigquery_adapters()
        # Monotonic per-column client-side PK counters (see insert()).
        self._pk_counters: Dict[Tuple, int] = {}

    def connect(self) -> None:
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
                    config.credentials_path,
                    client_options=client_options,
                )
            elif getattr(config, 'credentials_json', None):
                import json
                self._client = bigquery.Client.from_service_account_info(
                    config.credentials_json,
                    client_options=client_options,
                )
            else:
                project = getattr(config, 'project', None)
                self._client = bigquery.Client(
                    project=project,
                    client_options=client_options,
                )
            self._connected = True
            self.log(logging.INFO, "Connected to BigQuery")
        except Exception as e:
            raise ConnectionError(f"Failed to connect to BigQuery: {e}") from e

    def disconnect(self) -> None:
        if hasattr(self, '_client') and self._client:
            try:
                # BigQuery client doesn't require explicit close
                pass
            except Exception as e:
                self.log(logging.WARNING, f"Error disconnecting from BigQuery: {e}")
            finally:
                self._client = None
                self._connected = False

    def ping(self, reconnect: bool = True) -> bool:
        if not hasattr(self, '_client') or self._client is None:
            if reconnect:
                self.connect()
                return True
            return False
        try:
            from google.cloud import bigquery
            dataset_ref = self._client.dataset(getattr(self.config, 'dataset', None) or 'default')
            list(self._client.list_dataset_refs(dataset_ref))
            return True
        except Exception:
            if reconnect:
                try:
                    self.disconnect()
                    self.connect()
                    return True
                except Exception:
                    return False
            return False

    def _handle_error(self, error: Exception) -> None:
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

    def introspect_and_adapt(self) -> None:
        """Introspect the BigQuery server and adapt backend capabilities.

        Verifies connectivity and (when configured) the existence of the
        target dataset. Informational only at present: BigQuery exposes a
        stable standard SQL feature set, so no dialect adjustments are made.
        Failures are logged but do not prevent usage.
        """
        if not getattr(self, '_client', None):
            return
        try:
            dataset_name = getattr(self.config, 'dataset', None)
            if dataset_name:
                self._client.get_dataset(dataset_name)
            else:
                # Connection smoke test: list one dataset
                list(self._client.list_datasets(max_results=1))
            self.log(logging.DEBUG, "BigQuery introspection completed")
        except Exception as e:
            self.log(logging.WARNING, f"BigQuery introspection failed: {e}")

    @staticmethod
    def _to_param_value(value: Any) -> Any:
        """Serialize a Python scalar to the wire representation BigQuery expects.

        Query parameter values are transmitted as JSON strings (the REST
        ``QueryParameterValue.value`` field is a string); the emulator
        (goccy/bigquery-emulator) rejects numeric JSON literals outright,
        so everything non-string is stringified here.
        """
        from datetime import date, datetime, time
        from decimal import Decimal

        if value is None or isinstance(value, str):
            return value
        if isinstance(value, bool):
            return 'true' if value else 'false'
        if isinstance(value, (int, float, Decimal)):
            return str(value)
        if isinstance(value, (datetime, date, time)):
            return value.isoformat()
        import uuid
        if isinstance(value, uuid.UUID):
            return str(value)
        if isinstance(value, (bytes, bytearray)):
            # NOTE: real BigQuery expects base64 for BYTES parameters, but
            # goccy/bigquery-emulator base64-encodes the parameter string
            # a second time internally before storing it. Passing the raw
            # UTF-8 text keeps the emulator round-trip stable; binary-safe
            # payloads should use base64 against real BigQuery only.
            return bytes(value).decode("utf-8", errors="backslashreplace")
        return value

    @staticmethod
    def _build_job_config(params: Optional[Tuple]) -> Any:
        """Build a QueryJobConfig with positional query parameters."""
        if not params:
            return None
        from google.cloud import bigquery
        query_parameters = []
        for value in params:
            if isinstance(value, dict):
                query_parameters.append(bigquery.StructQueryParameter(None, *[
                    bigquery.ScalarQueryParameter(
                        k, BigQueryBackend._infer_param_type(v), BigQueryBackend._to_param_value(v)
                    )
                    for k, v in value.items()
                ]))
            elif isinstance(value, (list, tuple)):
                elem = value[0] if value else None
                query_parameters.append(bigquery.ArrayQueryParameter(
                    None,
                    BigQueryBackend._infer_param_type(elem),
                    [BigQueryBackend._to_param_value(v) for v in value]))
            else:
                query_parameters.append(bigquery.ScalarQueryParameter(
                    None,
                    BigQueryBackend._infer_param_type(value),
                    BigQueryBackend._to_param_value(value)))
        return bigquery.QueryJobConfig(query_parameters=query_parameters)

    @staticmethod
    def _infer_param_type(value: Any) -> str:
        from datetime import date, datetime, time
        from decimal import Decimal
        if isinstance(value, bool):
            return 'BOOL'
        if isinstance(value, int):
            return 'INT64'
        if isinstance(value, float):
            # The google client serializes FLOAT64 parameters back into
            # JSON numbers, which the emulator (and the REST wire format,
            # which strings for every other type) rejects; BIGNUMERIC is
            # serialized as a string and coerces to FLOAT64 in expressions.
            return 'BIGNUMERIC'
        if isinstance(value, Decimal):
            return 'BIGNUMERIC'
        if isinstance(value, datetime):
            return 'TIMESTAMP'
        if isinstance(value, date):
            return 'DATE'
        if isinstance(value, time):
            return 'TIME'
        if isinstance(value, bytes):
            return 'BYTES'
        return 'STRING'

    def execute(self, sql: str, params: Optional[Tuple] = None, returning: Optional[Any] = None, column_adapters: Optional[Dict] = None, *, options: Optional[Any] = None) -> QueryResult:
        """
        Execute a SQL statement against BigQuery.

        Accepts the base-class style ``options`` (ExecutionOptions) keyword.
        Statement type resolution order: options.stmt_type >
        process_result_set heuristic > SQL prefix detection.
        """
        from rhosocial.activerecord.backend.result import QueryResult
        from rhosocial.activerecord.backend.schema import StatementType

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
            if self._is_emulator_mode():
                # Emulator fast path: one ``jobs.query`` REST call per SQL
                # statement. The full client job lifecycle (submit + poll +
                # getQueryResults) costs ~6s per statement against the
                # emulator while a single jobs.query call completes in ~2s.
                return self._execute_via_rest(sql, params, is_select, column_adapters, column_mapping)
            if not getattr(self, '_connected', False) or getattr(self, '_client', None) is None:
                self.connect()
            job_config = self._build_job_config(params)
            job = self._client.query(sql, job_config=job_config)
            # Fail fast on job-level errors before fetching results:
            # some backends (e.g. goccy/bigquery-emulator) surface failures as
            # job errors whose 500 status would otherwise be retried
            # indefinitely by result-fetch calls.
            if job.errors:
                exc = job.exception()
                if exc is not None:
                    raise exc
                raise DatabaseError(str(job.errors))
            if is_select:
                rows_iter = job.result()
                # The model layer expects dictionary rows keyed by column name
                # (mirroring how DB-API backends map cursor.description), so
                # BigQuery Row objects are converted to plain dicts here. Type
                # adapters and column mapping are applied like other backends.
                adapters = column_adapters or {}
                mapping = column_mapping or {}
                rows = []
                for row in rows_iter:
                    row_dict = dict(row.items())
                    rows.append(self._remap_row_columns(self._adapt_row_types(row_dict, adapters), mapping))
                affected_rows = len(rows)
                result_data = rows
            else:
                job.result()  # wait for completion
                affected_rows = job.num_dml_affected_rows or 0
                result_data = None
            duration = (job.ended - job.started).total_seconds() if job.started and job.ended else None
            return QueryResult(data=result_data, affected_rows=affected_rows, duration=duration)
        except Exception as e:
            self._handle_error(e)

    @property
    def transaction_manager(self):
        return BigQueryTransactionManager(self)

    @property
    def dialect(self) -> BigQueryDialect:
        return BigQueryDialect(version=self._version)

        # -- Emulator REST fast path ---------------------------------------------------

    @staticmethod
    def _params_to_rest(params: Optional[Tuple]) -> Optional[List[Dict]]:
        """Serialize positional parameters to the REST ``queryParameters`` JSON form."""
        if not params:
            return None
        serialized = []
        for value in params:
            if isinstance(value, dict):
                struct = {
                    k: {"value": BigQueryBackend._to_param_value(v)}
                    for k, v in value.items()
                }
                serialized.append({"parameterType": {"type": "STRUCT"}, "parameterValue": {"structValues": struct}})
            elif isinstance(value, (list, tuple)):
                elem = value[0] if value else None
                serialized.append({
                    "parameterType": {"type": "ARRAY",
                                      "arrayType": {"type": BigQueryBackend._infer_param_type(elem)}},
                    "parameterValue": {
                        "arrayValues": [{"value": BigQueryBackend._to_param_value(v)} for v in value]
                    },
                })
            else:
                serialized.append({
                    "parameterType": {"type": BigQueryBackend._infer_param_type(value)},
                    "parameterValue": {"value": BigQueryBackend._to_param_value(value)},
                })
        return serialized

    @staticmethod
    def _rest_cell_to_python(cell: Dict, field_type: str) -> Any:
        value = cell.get("v")
        if value is None:
            return None
        ftype = (field_type or "").upper()
        if ftype in ("INTEGER", "INT64"):
            return int(value)
        if ftype in ("FLOAT", "FLOAT64"):
            return float(value)
        if ftype in ("BOOLEAN", "BOOL"):
            return str(value).lower() == "true"
        if ftype == "BYTES":
            import base64
            return base64.b64decode(value)
        return value

    def _rest_rows(self, body: Dict) -> List[Dict]:
        fields = (body.get("schema") or {}).get("fields") or []
        rows = []
        for raw in body.get("rows") or []:
            cells = raw.get("f") or []
            row = {}
            for i, field in enumerate(fields):
                cell = cells[i] if i < len(cells) else {}
                row[field.get("name")] = BigQueryBackend._rest_cell_to_python(cell, (field or {}).get("type"))
            rows.append(row)
        return rows

    _REST_SESSION = None  # shared requests.Session for the emulator fast path

    @classmethod
    def _rest_session(cls):
        if cls._REST_SESSION is None:
            import requests

            cls._REST_SESSION = requests.Session()
        return cls._REST_SESSION

    def _execute_via_rest(self, sql: str, params: Optional[Tuple], is_select: bool,
                          column_adapters: Optional[Dict], column_mapping: Optional[Dict]) -> QueryResult:
        import time as _time

        # Access through the class explicitly: this method is also invoked
        # with an AsyncBigQueryBackend instance (see async fast path).
        session = BigQueryBackend._rest_session()
        endpoint = str(self.config.api_endpoint).rstrip("/")
        project = getattr(self.config, "project", None) or "test"
        url = f"{endpoint}/bigquery/v2/projects/{project}/queries"
        request = {"query": sql, "useLegacySql": False, "timeoutMs": 30000, "maxResults": 10000}
        if params:
            # Apply the backend's default type adapters to parameters (the
            # same role ``prepare_parameters`` plays in the DB-API pipeline):
            # e.g. list/dict values become JSON strings, matching the string
            # columns the emulator actually stores them in.
            suggestions = self.get_default_adapter_suggestions()
            converted = []
            for value in params:
                suggestion = suggestions.get(type(value))
                if suggestion:
                    adapter, db_type = suggestion
                    value = adapter.to_database(value, db_type)
                converted.append(value)
            params = tuple(converted)
        serialized = BigQueryBackend._params_to_rest(params)
        if serialized is not None:
            request["queryParameters"] = serialized
            request["parameterMode"] = "POSITIONAL"

        start = _time.perf_counter()
        response = session.post(url, json=request, timeout=(10, 120))
        duration = _time.perf_counter() - start
        body = response.json()
        if response.status_code != 200 or body.get("error"):
            error_info = body.get("error") or {}
            message = error_info.get("message") or response.text
            BigQueryBackend._raise_http_error(response.status_code, message)

        result_data = None
        affected_rows = 0
        if is_select:
            adapters = column_adapters or {}
            mapping = column_mapping or {}
            rows = [
                self._remap_row_columns(self._adapt_row_types(row, adapters), mapping)
                for row in BigQueryBackend._rest_rows(self, body)
            ]
            # Follow pagination if the emulator ever splits results.
            page_token = body.get("pageToken")
            job_ref = body.get("jobReference") or {}
            job_id = job_ref.get("jobId")
            while page_token and job_id:
                job_project = job_ref.get("projectId", project)
                page_url = f"{endpoint}/bigquery/v2/projects/{job_project}/queries/{job_id}"
                page = session.get(page_url, params={"pageToken": page_token, "maxResults": 10000},
                                   timeout=(10, 120))
                pbody = page.json()
                if page.status_code != 200:
                    message = (pbody.get("error") or {}).get("message") or page.text
                    BigQueryBackend._raise_http_error(page.status_code, message)
                rows.extend(
                    self._remap_row_columns(self._adapt_row_types(row, adapters), mapping)
                    for row in BigQueryBackend._rest_rows(self, pbody)
                )
                page_token = pbody.get("pageToken")
            result_data = rows
            affected_rows = len(rows)
        else:
            num = body.get("numDmlAffectedRows")
            affected_rows = int(num) if num is not None else 0
        return QueryResult(data=result_data, affected_rows=affected_rows, duration=duration)

    @staticmethod
    def _raise_http_error(status: int, message: str):
        """Map an emulator HTTP error response onto the google exception types
        that :meth:`_classify_error` understands."""
        from google.api_core import exceptions as gexc

        if status == 400:
            raise gexc.BadRequest(message)
        if status == 404:
            raise gexc.NotFound(message)
        if status == 409:
            raise gexc.AlreadyExists(message)
        if status >= 500:
            raise gexc.InternalServerError(message)
        raise gexc.GoogleAPIError(f"HTTP {status}: {message}")

    # -- Client-side PK generation -------------------------------------------------
    # BigQuery has neither AUTO_INCREMENT/IDENTITY columns nor a RETURNING
    # clause, so there is no server-side way to learn the key of a newly
    # inserted row. Following the same "client-side id" strategy used by
    # backends without key generation (e.g. ClickHouse in the core dialect
    # docs), the backend fills a ``None`` single-column primary key with
    # ``MAX(pk) + 1`` before executing the INSERT and reports the generated
    # value through ``QueryResult.last_insert_id``. This is best-effort and
    # only intended for single-writer workloads.

    def _next_pk_value(self, table: str, schema_name: Optional[str], pk_column: str) -> int:
        from rhosocial.activerecord.backend.options import ExecutionOptions
        from rhosocial.activerecord.backend.schema import StatementType

        key = (schema_name, table, pk_column)
        qualified = f"`{schema_name}`.`{table}`" if schema_name else f"`{table}`"
        sql = f"SELECT COALESCE(MAX(`{pk_column}`), 0) + 1 AS next_id FROM {qualified}"
        result = self.execute(sql, options=ExecutionOptions(stmt_type=StatementType.DQL))
        row = result.data[0]
        value = row.get("next_id") if isinstance(row, dict) else row[0]
        # Stay monotonic across deletes: MAX(pk)+1 reuses the id of a just
        # deleted single row, which breaks ActiveRecord semantics like
        # "save after delete must produce a new id".
        value = max(int(value), self._pk_counters.get(key, 0) + 1)
        self._pk_counters[key] = value
        return value

    def insert(self, options) -> QueryResult:
        from dataclasses import replace

        pk = getattr(options, 'primary_key', None)
        data = options.data
        if pk and isinstance(pk, str) and data.get(pk) is None:
            new_id = self._next_pk_value(options.table, options.schema_name, pk)
            options = replace(options, data={**data, pk: new_id})
            # ``data`` on the options copy now holds the generated id, but the
            # model layer keeps its own prepared dict (with the pk still None),
            # so it will pick the value up from ``last_insert_id``.
            result = super().insert(options)
            result.last_insert_id = new_id
        else:
            result = super().insert(options)
        if result.affected_rows == 0 and self._is_emulator_mode():
            # The emulator never reports DML row counts; a successful INSERT
            # statement inserted all of its rows by definition.
            result.affected_rows = 1
        return result

    def bulk_insert(self, options) -> QueryResult:
        from dataclasses import replace

        pk = getattr(options, 'primary_key', None)
        if pk and isinstance(pk, str) and options.rows:
            columns = list(options.columns or [])
            if pk not in columns:
                # The model layer omits unset (None) fields from the column
                # list entirely; append the pk column and generate ids for
                # every row. The model layer then assigns ``last_insert_id
                # + j`` back onto the records, which matches the sequential
                # ids generated here.
                start = self._next_pk_value(options.table, options.schema_name, pk)
                count = len(options.rows)
                self._pk_counters[(options.schema_name, options.table, pk)] = start + count - 1
                new_rows = [list(row) + [start + i] for i, row in enumerate(options.rows)]
                options = replace(options, columns=columns + [pk], rows=new_rows)
                result = super().bulk_insert(options)
                result.last_insert_id = start
            else:
                idx = columns.index(pk)
                missing = [i for i, row in enumerate(options.rows)
                           if idx < len(row) and row[idx] is None]
                if missing:
                    start = self._next_pk_value(options.table, options.schema_name, pk)
                    self._pk_counters[(options.schema_name, options.table, pk)] = start + len(missing) - 1
                    new_rows = [list(row) for row in options.rows]
                    for offset, row_idx in enumerate(missing):
                        new_rows[row_idx][idx] = start + offset
                    options = replace(options, rows=new_rows)
                    result = super().bulk_insert(options)
                    result.last_insert_id = start
                else:
                    result = super().bulk_insert(options)
        else:
            result = super().bulk_insert(options)
        if result.affected_rows == 0 and self._is_emulator_mode():
            result.affected_rows = len(options.rows)
        return result

    def bulk_update(self, options) -> QueryResult:
        # Generate the CASE-WHEN bulk UPDATE with an explicit ``ELSE <col>``
        # per assignment: without it the expression yields NULL on unmatched
        # rows, and the BigQuery analyzer rejects an untyped NULL CASE result
        # ("Value of type INT64 cannot be assigned to ..."). Reusing the
        # column itself is also the safe semantics.
        from rhosocial.activerecord.backend.base.operations import _is_sql_expression
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
        result = self.execute(sql, params, options=exec_options)
        if options.auto_commit:
            self._handle_auto_commit_if_needed()
        if result.affected_rows == 0 and self._is_emulator_mode():
            # The emulator reports no DML row count; the statement touched
            # exactly the rows whose pk was in the batch.
            result.affected_rows = len(getattr(options, "pk_values", None) or [])
        return result

    # -- Emulator DML row-count fallback -----------------------------------------
    # goccy/bigquery-emulator never populates ``numDmlAffectedRows``. When the
    # configured endpoint points at an emulator (``api_endpoint`` set), the
    # backend compensates for UPDATE/DELETE by running the same WHERE clause
    # as a ``SELECT COUNT(*)`` probe before the mutation.

    def _is_emulator_mode(self) -> bool:
        return bool(getattr(self.config, 'api_endpoint', None))

    def _count_matching(self, table: str, schema_name: Optional[str], where) -> Optional[int]:
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
        result = self.execute(sql, params, options=ExecutionOptions(stmt_type=StatementType.DQL))
        if not result.data:
            return None
        row = result.data[0]
        value = row.get("n") if isinstance(row, dict) else row[0]
        return int(value)

    def update(self, options) -> QueryResult:
        matched = None
        if self._is_emulator_mode():
            matched = self._count_matching(options.table, options.schema_name, options.where)
        result = super().update(options)
        if result.affected_rows == 0 and matched:
            result.affected_rows = matched
        return result

    def delete(self, options) -> QueryResult:
        matched = None
        if self._is_emulator_mode():
            matched = self._count_matching(options.table, options.schema_name, options.where)
        result = super().delete(options)
        if result.affected_rows == 0 and matched:
            result.affected_rows = matched
        return result

    def get_default_adapter_suggestions(self) -> Dict:
        from decimal import Decimal
        from datetime import datetime
        suggestions = {}
        # (python type, preferred driver-side types in priority order)
        # list/dict prefer the JSON string transport: the vast majority of
        # ActiveRecord models store JSON in plain string/JSON columns, and the
        # emulator-backed testbed does not exercise native ARRAY<STRUCT>
        # bindings. Native transports remain available via explicit adapters.
        type_mappings = [
            (list, [str, list]),   # JSON strings, then ARRAY parameters
            (dict, [str, dict]),   # JSON strings, then STRUCT parameters
            (Decimal, [Decimal, str, float, int]),  # BIGNUMERIC
            (datetime, [str]),     # TIMESTAMP
        ]
        for py_type, db_types in type_mappings:
            for db_type in db_types:
                adapter = self.adapter_registry.get_adapter(py_type, db_type)
                if adapter is not None:
                    suggestions[py_type] = (adapter, db_type)
                    break
        return suggestions

    def _register_bigquery_adapters(self):
        from .adapters import (
            BigQueryStructAdapter, BigQueryArrayAdapter,
            BigQueryJSONAdapter, BigQueryDecimalAdapter,
            BigQueryTimestampAdapter,
        )
        for adapter in [
            BigQueryStructAdapter(), BigQueryArrayAdapter(),
            BigQueryJSONAdapter(), BigQueryDecimalAdapter(),
            BigQueryTimestampAdapter(),
        ]:
            for py_type, driver_types in adapter.supported_types.items():
                for driver_type in driver_types:
                    self.adapter_registry.register(adapter, py_type, driver_type, allow_override=True)
