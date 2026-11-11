# tests/rhosocial/activerecord_bigquery_test/feature/backend/test_execute_error_contract.py
"""BigQuery execute phases follow the framework error contract.

These tests never reach BigQuery: the client, the query job and the service
replies are in-process fakes, so no project, dataset or emulator is needed.
They pin the phases that the execute pipeline must distinguish:

* framework errors entering ``_handle_error`` keep their type;
* connection acquisition always surfaces ``ConnectionError`` (transient only
  for transport failures);
* driver 429/503/504 replies stay ``OperationalError(transient=True)`` and
  authentication refusals stay non-retryable;
* ``job.errors`` without a driver exception is classified by its message;
* ``execute`` never returns ``None`` when the handler fails to raise.

Both the synchronous and the asynchronous backend are covered because they
share the translation in ``backend/backend.py``.
"""

import pytest

gexc = pytest.importorskip("google.api_core.exceptions")

from rhosocial.activerecord.backend.errors import (  # noqa: E402
    ConnectionError,
    DatabaseError,
    IntegrityError,
    OperationalError,
    QueryError,
    TypeConversionError,
)
from rhosocial.activerecord.backend.impl.bigquery.backend import (  # noqa: E402
    AsyncBigQueryBackend,
    BigQueryBackend,
)


class _FakeJob:
    """Minimal query job covering the fields ``execute`` reads."""

    def __init__(self, errors=None, exception=None):
        self.errors = errors or []
        self._exception = exception
        self.num_dml_affected_rows = 0
        self.started = None
        self.ended = None

    def exception(self):
        return self._exception


class _FakeClient:
    """Client stand-in: either raises on ``query`` or returns a fake job."""

    def __init__(self, job=None, query_error=None):
        self._job = job
        self._query_error = query_error

    def query(self, sql, job_config=None):
        if self._query_error is not None:
            raise self._query_error
        return self._job


@pytest.fixture(params=[BigQueryBackend], ids=["sync"])
def sync_backend(request):
    return request.param(project="test", dataset="test_dataset")


@pytest.fixture(params=[AsyncBigQueryBackend], ids=["async"])
def async_backend(request):
    return request.param(project="test", dataset="test_dataset")


def _attach(backend, job=None, query_error=None):
    """Install a fake client and mark the backend connected."""
    backend._client = _FakeClient(job=job, query_error=query_error)
    backend._connected = True
    return backend


def _raise_from(error):
    def _factory(*args, **kwargs):
        raise error

    return _factory


def _assert_diagnostics(error, transient):
    assert error.operation == "execute"
    assert error.backend == "bigquery"
    assert error.transient is transient


class TestExecuteErrorContract:
    """Synchronous phase assertions."""

    def test_framework_connection_error_is_not_flattened(self, sync_backend):
        error = ConnectionError("connection lost")
        with pytest.raises(ConnectionError) as info:
            sync_backend._handle_error(error)
        assert info.value is error

    def test_framework_type_conversion_error_is_not_flattened(self, sync_backend):
        error = TypeConversionError("cannot adapt value")
        with pytest.raises(TypeConversionError) as info:
            sync_backend._handle_error(error)
        assert info.value is error

    @pytest.mark.parametrize(
        "status,driver_error",
        [
            (429, gexc.TooManyRequests),
            (503, gexc.ServiceUnavailable),
            (504, gexc.GatewayTimeout),
        ],
    )
    def test_transient_service_reply_stays_operational_error(
        self, sync_backend, status, driver_error
    ):
        backend = _attach(
            sync_backend, query_error=driver_error("service unavailable")
        )
        with pytest.raises(OperationalError) as info:
            backend.execute("INSERT INTO test_dataset.orders VALUES (1)")
        assert info.value.transient is True
        assert info.value.retryable is True
        assert info.value.driver_code == status

    def test_forbidden_is_non_retryable_database_error(self, sync_backend):
        backend = _attach(
            sync_backend, query_error=gexc.Forbidden("Access Denied")
        )
        with pytest.raises(DatabaseError) as info:
            backend.execute("INSERT INTO test_dataset.orders VALUES (1)")
        assert not isinstance(info.value, OperationalError)
        assert info.value.transient is False
        assert info.value.retryable is False
        assert info.value.driver_code == 403

    def test_job_errors_query_failure_raises_query_error(self, sync_backend):
        job = _FakeJob(
            errors=[{
                "reason": "invalidQuery",
                "message": "Failed to analyze query: syntax error",
            }]
        )
        backend = _attach(sync_backend, job=job)
        with pytest.raises(QueryError):
            backend.execute("INSERT INTO test_dataset.orders VALUES (1)")

    def test_job_errors_integrity_failure_raises_integrity_error(self, sync_backend):
        job = _FakeJob(
            errors=[{"message": "Duplicate primary key for row 1"}]
        )
        backend = _attach(sync_backend, job=job)
        with pytest.raises(IntegrityError):
            backend.execute("INSERT INTO test_dataset.orders VALUES (1)")

    def test_job_errors_without_hint_keeps_diagnostics(self, sync_backend):
        job = _FakeJob(errors=[{"message": "Something went wrong"}])
        backend = _attach(sync_backend, job=job)
        with pytest.raises(DatabaseError) as info:
            backend.execute("INSERT INTO test_dataset.orders VALUES (1)")
        assert not isinstance(info.value, (QueryError, IntegrityError))
        _assert_diagnostics(info.value, transient=None)

    def test_job_errors_stays_typed_through_handle_error(self, sync_backend):
        # A framework error raised by the job path must not be re-translated.
        error = TypeConversionError("job result decode failed")
        with pytest.raises(TypeConversionError) as info:
            sync_backend._handle_error(error)
        assert info.value is error

    def test_execute_raises_when_handler_returns_none(self, sync_backend, monkeypatch):
        backend = _attach(sync_backend, query_error=RuntimeError("boom"))
        monkeypatch.setattr(backend, "_handle_error", lambda error: None)
        with pytest.raises(DatabaseError):
            backend.execute("INSERT INTO test_dataset.orders VALUES (1)")

    def test_auto_commit_hook_has_no_transaction_phase(self, sync_backend):
        # BigQuery commits each job; the base hook stays a no-op and cannot
        # raise TransactionError.
        sync_backend._handle_auto_commit_if_needed()

    def test_connect_auth_failure_is_connection_error(self, monkeypatch):
        bigquery = pytest.importorskip("google.cloud.bigquery")
        monkeypatch.setattr(
            bigquery, "Client", _raise_from(gexc.Forbidden("Access Denied"))
        )
        backend = BigQueryBackend(project="test")
        with pytest.raises(ConnectionError) as info:
            backend.connect()
        assert not isinstance(info.value, OperationalError)
        assert info.value.operation == "connect"
        assert info.value.transient is False
        assert info.value.retryable is False

    def test_connect_transport_failure_is_transient_connection_error(self, monkeypatch):
        bigquery = pytest.importorskip("google.cloud.bigquery")
        from google.auth.exceptions import TransportError

        monkeypatch.setattr(
            bigquery, "Client", _raise_from(TransportError("network down"))
        )
        backend = BigQueryBackend(project="test")
        with pytest.raises(ConnectionError) as info:
            backend.connect()
        assert info.value.operation == "connect"
        assert info.value.transient is True
        assert info.value.retryable is True


class TestAsyncExecuteErrorContract:
    """Asynchronous phase assertions (same names as the sync class)."""

    @pytest.mark.asyncio
    async def test_framework_connection_error_is_not_flattened(self, async_backend):
        error = ConnectionError("connection lost")
        with pytest.raises(ConnectionError) as info:
            async_backend._handle_error(error)
        assert info.value is error

    @pytest.mark.asyncio
    async def test_framework_type_conversion_error_is_not_flattened(self, async_backend):
        error = TypeConversionError("cannot adapt value")
        with pytest.raises(TypeConversionError) as info:
            async_backend._handle_error(error)
        assert info.value is error

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "status,driver_error",
        [
            (429, gexc.TooManyRequests),
            (503, gexc.ServiceUnavailable),
            (504, gexc.GatewayTimeout),
        ],
    )
    async def test_transient_service_reply_stays_operational_error(
        self, async_backend, status, driver_error
    ):
        backend = _attach(
            async_backend, query_error=driver_error("service unavailable")
        )
        with pytest.raises(OperationalError) as info:
            await backend.execute("INSERT INTO test_dataset.orders VALUES (1)")
        assert info.value.transient is True
        assert info.value.retryable is True
        assert info.value.driver_code == status

    @pytest.mark.asyncio
    async def test_forbidden_is_non_retryable_database_error(self, async_backend):
        backend = _attach(
            async_backend, query_error=gexc.Forbidden("Access Denied")
        )
        with pytest.raises(DatabaseError) as info:
            await backend.execute("INSERT INTO test_dataset.orders VALUES (1)")
        assert not isinstance(info.value, OperationalError)
        assert info.value.transient is False
        assert info.value.retryable is False
        assert info.value.driver_code == 403

    @pytest.mark.asyncio
    async def test_job_errors_query_failure_raises_query_error(self, async_backend):
        job = _FakeJob(
            errors=[{
                "reason": "invalidQuery",
                "message": "Failed to analyze query: syntax error",
            }]
        )
        backend = _attach(async_backend, job=job)
        with pytest.raises(QueryError):
            await backend.execute("INSERT INTO test_dataset.orders VALUES (1)")

    @pytest.mark.asyncio
    async def test_job_errors_integrity_failure_raises_integrity_error(
        self, async_backend
    ):
        job = _FakeJob(
            errors=[{"message": "Duplicate primary key for row 1"}]
        )
        backend = _attach(async_backend, job=job)
        with pytest.raises(IntegrityError):
            await backend.execute("INSERT INTO test_dataset.orders VALUES (1)")

    @pytest.mark.asyncio
    async def test_job_errors_without_hint_keeps_diagnostics(self, async_backend):
        job = _FakeJob(errors=[{"message": "Something went wrong"}])
        backend = _attach(async_backend, job=job)
        with pytest.raises(DatabaseError) as info:
            await backend.execute("INSERT INTO test_dataset.orders VALUES (1)")
        assert not isinstance(info.value, (QueryError, IntegrityError))
        _assert_diagnostics(info.value, transient=None)

    @pytest.mark.asyncio
    async def test_job_errors_stays_typed_through_handle_error(self, async_backend):
        error = TypeConversionError("job result decode failed")
        with pytest.raises(TypeConversionError) as info:
            async_backend._handle_error(error)
        assert info.value is error

    @pytest.mark.asyncio
    async def test_execute_raises_when_handler_returns_none(
        self, async_backend, monkeypatch
    ):
        backend = _attach(async_backend, query_error=RuntimeError("boom"))
        monkeypatch.setattr(backend, "_handle_error", lambda error: None)
        with pytest.raises(DatabaseError):
            await backend.execute("INSERT INTO test_dataset.orders VALUES (1)")

    @pytest.mark.asyncio
    async def test_auto_commit_hook_has_no_transaction_phase(self, async_backend):
        await async_backend._handle_auto_commit_if_needed()

    @pytest.mark.asyncio
    async def test_connect_auth_failure_is_connection_error(self, monkeypatch):
        bigquery = pytest.importorskip("google.cloud.bigquery")
        monkeypatch.setattr(
            bigquery, "Client", _raise_from(gexc.Forbidden("Access Denied"))
        )
        backend = AsyncBigQueryBackend(project="test")
        with pytest.raises(ConnectionError) as info:
            await backend.connect()
        assert not isinstance(info.value, OperationalError)
        assert info.value.operation == "connect"
        assert info.value.transient is False
        assert info.value.retryable is False

    @pytest.mark.asyncio
    async def test_connect_transport_failure_is_transient_connection_error(
        self, monkeypatch
    ):
        bigquery = pytest.importorskip("google.cloud.bigquery")
        from google.auth.exceptions import TransportError

        monkeypatch.setattr(
            bigquery, "Client", _raise_from(TransportError("network down"))
        )
        backend = AsyncBigQueryBackend(project="test")
        with pytest.raises(ConnectionError) as info:
            await backend.connect()
        assert info.value.operation == "connect"
        assert info.value.transient is True
        assert info.value.retryable is True
