# tests/rhosocial/activerecord_bigquery_test/feature/logging/test_execution_logging_unit.py
"""DB-free unit tests for BigQuery execution logging.

The tests in this module never construct ``google.cloud.bigquery.Client``, never
reach the network and never need the emulator: the emulator REST fast path and
the client job path are replaced with in-process fakes. Both the synchronous and
the asynchronous backend must report the canonical
``rhosocial.activerecord.backend.bigquery`` logger, and both execution paths must
emit the shared DEBUG SQL record and the INFO result summary.
"""

import logging
import sys
import types

import pytest

from rhosocial.activerecord.backend.errors import DatabaseError
from rhosocial.activerecord.backend.expression import (
    Column, ComparisonPredicate, Literal,
)
from rhosocial.activerecord.backend.impl.bigquery.async_transaction import (
    AsyncBigQueryTransactionManager,
)
from rhosocial.activerecord.backend.impl.bigquery.backend.async_backend import (
    AsyncBigQueryBackend,
)
from rhosocial.activerecord.backend.impl.bigquery.backend.backend import (
    BigQueryBackend,
    ExecutionSummaryCursor,
    log_result_summary,
)
from rhosocial.activerecord.backend.impl.bigquery.transaction import (
    BigQueryTransactionManager,
)
from rhosocial.activerecord.backend.options import ExecutionOptions, LogContext
from rhosocial.activerecord.backend.result import QueryResult
from rhosocial.activerecord.backend.schema import StatementType

CANONICAL_LOGGER = "rhosocial.activerecord.backend.bigquery"
TRANSACTION_LOGGER = "rhosocial.activerecord.transaction"


class _FakeClient:
    """Minimal stand-in for the google client used by the non-emulator path."""

    def __init__(self, error=None):
        self._error = error

    def query(self, sql, job_config=None):
        if self._error is not None:
            raise self._error
        raise AssertionError("these tests do not exercise a successful job path")


class _FailingConnection:
    """Connection whose statements always fail (BEGIN and ROLLBACK)."""

    def __init__(self):
        self.calls = []

    def execute(self, sql):
        self.calls.append(sql)
        raise RuntimeError(f"{sql} failed")


class _FailingAsyncConnection:
    """Async twin of :class:`_FailingConnection`."""

    def __init__(self):
        self.calls = []

    async def execute(self, sql):
        self.calls.append(sql)
        raise RuntimeError(f"{sql} failed")


def _fake_rest(result):
    """Build a replacement for ``BigQueryBackend._execute_via_rest``."""

    def _rest(self, sql, params, is_select, column_adapters, column_mapping):
        return result

    return _rest


def _install_fake_google(monkeypatch):
    """Install just enough of the google namespace for ``connect()``.

    The real packages are not needed (and in some environments fail to import),
    so every module imported by ``connect()`` is replaced with a fake.
    """

    google = types.ModuleType("google")
    cloud = types.ModuleType("google.cloud")
    bigquery = types.ModuleType("google.cloud.bigquery")
    auth = types.ModuleType("google.auth")
    credentials = types.ModuleType("google.auth.credentials")
    api_core = types.ModuleType("google.api_core")
    client_options = types.ModuleType("google.api_core.client_options")

    class _FakeBigQueryClient:
        def __init__(self, *args, **kwargs):
            self.init_kwargs = kwargs

    bigquery.Client = _FakeBigQueryClient
    cloud.bigquery = bigquery
    google.cloud = cloud
    credentials.AnonymousCredentials = object
    auth.credentials = credentials
    google.auth = auth
    client_options.ClientOptions = lambda **kwargs: kwargs
    api_core.client_options = client_options
    google.api_core = api_core

    for name, module in {
        "google": google,
        "google.cloud": cloud,
        "google.cloud.bigquery": bigquery,
        "google.auth": auth,
        "google.auth.credentials": credentials,
        "google.api_core": api_core,
        "google.api_core.client_options": client_options,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)


def _records_with_event(caplog, event):
    return [
        record for record in caplog.records
        if getattr(record, "event", None) == event
    ]


def test_backends_use_the_canonical_logger():
    backend = BigQueryBackend(project="project", dataset="dataset")
    assert backend._get_logger_name() == CANONICAL_LOGGER
    assert backend.logger.name == CANONICAL_LOGGER
    assert isinstance(backend.transaction_manager, BigQueryTransactionManager)

    async_backend = AsyncBigQueryBackend(project="project", dataset="dataset")
    assert async_backend._get_logger_name() == CANONICAL_LOGGER
    assert async_backend.logger.name == CANONICAL_LOGGER
    assert isinstance(
        async_backend.transaction_manager, AsyncBigQueryTransactionManager
    )

    cursor = ExecutionSummaryCursor(3)
    assert cursor.rowcount == 3


def test_log_result_summary_covers_dml_and_dql(caplog):
    backend = BigQueryBackend(project="project", dataset="dataset")

    dml_options = ExecutionOptions(
        stmt_type=StatementType.DML,
        log_context=LogContext(operation="update", object_name="users"),
    )
    with caplog.at_level(logging.INFO, logger=CANONICAL_LOGGER):
        log_result_summary(
            backend,
            StatementType.DML,
            "UPDATE users SET name = ?",
            QueryResult(data=[{"id": 1}], affected_rows=2, duration=0.01),
            dml_options,
        )
    dml_records = _records_with_event(caplog, "dml.update")
    assert dml_records
    assert dml_records[0].activerecord["rows_affected"] == 2

    dql_options = ExecutionOptions(
        stmt_type=StatementType.DQL,
        log_context=LogContext(operation="select", object_name="users"),
    )
    with caplog.at_level(logging.INFO, logger=CANONICAL_LOGGER):
        log_result_summary(
            backend,
            StatementType.DQL,
            "SELECT * FROM users",
            QueryResult(data=[{"id": 1}, {"id": 2}], affected_rows=2, duration=0.02),
            dql_options,
        )
    dql_records = _records_with_event(caplog, "dql.select")
    assert dql_records
    assert dql_records[0].activerecord["rows_returned"] == 2


def test_sync_execute_emulator_path_logs_start_and_summary(caplog, monkeypatch):
    backend = BigQueryBackend(
        project="project", dataset="dataset", api_endpoint="http://emulator"
    )
    result = QueryResult(data=[{"id": 1}], affected_rows=1, duration=0.01)
    monkeypatch.setattr(BigQueryBackend, "_execute_via_rest", _fake_rest(result))

    with caplog.at_level(logging.DEBUG, logger=CANONICAL_LOGGER):
        returned = backend.execute("SELECT 1")

    assert returned is result
    assert any(
        record.levelno == logging.DEBUG
        and "Executing SQL: SELECT 1" in record.getMessage()
        for record in caplog.records
    )
    summary = _records_with_event(caplog, "dql.select")
    assert summary
    assert summary[0].activerecord["rows_returned"] == 1


def test_sync_execute_error_logs_before_reraise(caplog, monkeypatch):
    backend = BigQueryBackend(project="project", dataset="dataset")
    backend._connected = True
    backend._client = _FakeClient(ValueError("boom"))
    monkeypatch.setattr(
        BigQueryBackend, "_classify_error", lambda self, error: "generic"
    )
    options = ExecutionOptions(
        stmt_type=StatementType.DML,
        log_context=LogContext(operation="update", object_name="users"),
    )

    with caplog.at_level(logging.DEBUG, logger=CANONICAL_LOGGER):
        with pytest.raises(DatabaseError, match="boom"):
            backend.execute("UPDATE users SET name = ?", None, options=options)

    failures = [
        record for record in caplog.records
        if record.getMessage().startswith("Query failed")
    ]
    assert failures
    assert failures[0].activerecord["error_type"] == "ValueError"


def test_sync_next_pk_value_uses_log_context(monkeypatch):
    backend = BigQueryBackend(project="project", dataset="dataset")
    captured = {}

    def fake_execute(sql, params=None, options=None, **kwargs):
        captured["sql"] = sql
        captured["options"] = options
        return QueryResult(data=[{"next_id": 3}], affected_rows=1)

    monkeypatch.setattr(backend, "execute", fake_execute)

    assert backend._next_pk_value("users", "dataset", "id") == 3
    context = captured["options"].log_context
    assert context.operation == "select"
    assert context.object_name == "users"
    assert context.schema == "dataset"
    assert "MAX" in captured["sql"].upper()


def test_sync_count_matching_uses_log_context(monkeypatch):
    backend = BigQueryBackend(project="project", dataset="dataset")
    captured = {}

    def fake_execute(sql, params=None, options=None, **kwargs):
        captured["options"] = options
        return QueryResult(data=[{"n": 3}], affected_rows=1)

    monkeypatch.setattr(backend, "execute", fake_execute)

    dialect = backend.dialect
    where = ComparisonPredicate(
        dialect, "=", Column(dialect, "id"), Literal(dialect, 7)
    )
    assert backend._count_matching("users", "dataset", where) == 3
    assert captured["options"].log_context.operation == "count"
    assert backend._count_matching("users", "dataset", None) is None


def test_sync_connect_logs_without_google_client(caplog, monkeypatch):
    _install_fake_google(monkeypatch)
    backend = BigQueryBackend(project="project", dataset="dataset")

    with caplog.at_level(logging.DEBUG, logger=CANONICAL_LOGGER):
        backend.connect()

    assert backend._connected is True
    assert backend._client is not None
    assert any(
        record.getMessage() == "Connected to BigQuery"
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_async_execute_emulator_path_logs_start_and_summary(caplog, monkeypatch):
    backend = AsyncBigQueryBackend(
        project="project", dataset="dataset", api_endpoint="http://emulator"
    )
    result = QueryResult(data=[{"id": 1}], affected_rows=1, duration=0.01)
    monkeypatch.setattr(BigQueryBackend, "_execute_via_rest", _fake_rest(result))

    with caplog.at_level(logging.DEBUG, logger=CANONICAL_LOGGER):
        returned = await backend.execute("SELECT 1")

    assert returned is result
    assert any(
        record.levelno == logging.DEBUG
        and "Executing SQL: SELECT 1" in record.getMessage()
        for record in caplog.records
    )
    summary = _records_with_event(caplog, "dql.select")
    assert summary
    assert summary[0].activerecord["rows_returned"] == 1


@pytest.mark.asyncio
async def test_async_execute_error_logs_before_reraise(caplog, monkeypatch):
    backend = AsyncBigQueryBackend(project="project", dataset="dataset")
    backend._connected = True
    backend._client = _FakeClient(ValueError("boom"))
    monkeypatch.setattr(
        AsyncBigQueryBackend, "_classify_error", lambda self, error: "generic"
    )
    options = ExecutionOptions(
        stmt_type=StatementType.DML,
        log_context=LogContext(operation="update", object_name="users"),
    )

    with caplog.at_level(logging.DEBUG, logger=CANONICAL_LOGGER):
        with pytest.raises(DatabaseError, match="boom"):
            await backend.execute("UPDATE users SET name = ?", None, options=options)

    failures = [
        record for record in caplog.records
        if record.getMessage().startswith("Query failed")
    ]
    assert failures
    assert failures[0].activerecord["error_type"] == "ValueError"


@pytest.mark.asyncio
async def test_async_next_pk_value_uses_log_context(monkeypatch):
    backend = AsyncBigQueryBackend(project="project", dataset="dataset")
    captured = {}

    async def fake_execute(sql, params=None, options=None, **kwargs):
        captured["options"] = options
        return QueryResult(data=[{"next_id": 4}], affected_rows=1)

    monkeypatch.setattr(backend, "execute", fake_execute)

    assert await backend._next_pk_value("users", "dataset", "id") == 4
    context = captured["options"].log_context
    assert context.operation == "select"
    assert context.object_name == "users"
    assert context.schema == "dataset"


@pytest.mark.asyncio
async def test_async_count_matching_uses_log_context(monkeypatch):
    backend = AsyncBigQueryBackend(project="project", dataset="dataset")
    captured = {}

    async def fake_execute(sql, params=None, options=None, **kwargs):
        captured["options"] = options
        return QueryResult(data=[{"n": 5}], affected_rows=1)

    monkeypatch.setattr(backend, "execute", fake_execute)

    dialect = backend.dialect
    where = ComparisonPredicate(
        dialect, "=", Column(dialect, "id"), Literal(dialect, 9)
    )
    assert await backend._count_matching("users", "dataset", where) == 5
    assert captured["options"].log_context.operation == "count"
    assert await backend._count_matching("users", "dataset", None) is None


@pytest.mark.asyncio
async def test_async_connect_logs_without_google_client(caplog, monkeypatch):
    _install_fake_google(monkeypatch)
    backend = AsyncBigQueryBackend(project="project", dataset="dataset")

    with caplog.at_level(logging.DEBUG, logger=CANONICAL_LOGGER):
        await backend.connect()

    assert backend._connected is True
    assert backend._client is not None
    assert any(
        record.getMessage() == "Connected to BigQuery"
        for record in caplog.records
    )


def test_sync_transaction_logs_rollback_failure(caplog):
    manager = BigQueryTransactionManager(_FailingConnection())

    with caplog.at_level(logging.WARNING, logger=TRANSACTION_LOGGER):
        with pytest.raises(RuntimeError, match="BEGIN TRANSACTION failed"):
            with manager.transaction():
                pass

    assert any(
        "Failed to roll back BigQuery transaction" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_async_transaction_logs_rollback_failure(caplog):
    manager = AsyncBigQueryTransactionManager(_FailingAsyncConnection())

    with caplog.at_level(logging.WARNING, logger=TRANSACTION_LOGGER):
        with pytest.raises(RuntimeError, match="BEGIN TRANSACTION failed"):
            async with manager.transaction():
                pass

    assert any(
        "Failed to roll back BigQuery transaction" in record.getMessage()
        for record in caplog.records
    )
