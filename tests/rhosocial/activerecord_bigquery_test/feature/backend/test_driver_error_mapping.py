# tests/rhosocial/activerecord_bigquery_test/feature/backend/test_driver_error_mapping.py
"""BigQuery driver exceptions map onto the semantic error taxonomy.

The tests synthesize ``google.api_core.exceptions`` instances and call the
backend's error translator directly, so no BigQuery service or emulator is
needed. Both the synchronous and the asynchronous backend are exercised
because they share the translation in ``backend.py``.
"""

import builtins

import pytest

gexc = pytest.importorskip("google.api_core.exceptions")

from rhosocial.activerecord.backend.errors import (  # noqa: E402
    ConnectionError,
    DataError,
    DatabaseError,
    DeadlockError,
    InfrastructureError,
    IntegrityError,
    LockError,
    OperationalError,
    QueryError,
)
from rhosocial.activerecord.backend.impl.bigquery.backend import (  # noqa: E402
    AsyncBigQueryBackend,
    BigQueryBackend,
)


@pytest.fixture(params=[BigQueryBackend, AsyncBigQueryBackend], ids=["sync", "async"])
def backend(request):
    """An unconnected backend of either flavour."""
    return request.param(project="test", dataset="test_dataset")


def _translated(backend, error):
    with pytest.raises(DatabaseError) as info:
        backend._handle_error(error)
    return info.value


def _assert_diagnostics(error, status):
    assert error.operation == "execute"
    assert error.backend == "bigquery"
    if status is not None:
        assert error.driver_code == status
        assert type(error.driver_code) is int


def test_bad_request_already_exists_maps_to_integrity(backend):
    translated = _translated(
        backend, gexc.BadRequest("Already Exists: Table test.test_dataset.orders")
    )
    assert isinstance(translated, IntegrityError)
    assert isinstance(translated, DataError)
    assert translated.retryable is False
    _assert_diagnostics(translated, 400)


def test_conflict_already_exists_maps_to_integrity(backend):
    translated = _translated(
        backend, gexc.AlreadyExists("Table test.test_dataset.orders already exists")
    )
    assert isinstance(translated, IntegrityError)
    assert isinstance(translated, DataError)
    _assert_diagnostics(translated, 409)


def test_bad_request_duplicate_key_maps_to_integrity(backend):
    translated = _translated(
        backend, gexc.BadRequest("Duplicate primary key for row 3")
    )
    assert isinstance(translated, IntegrityError)
    _assert_diagnostics(translated, 400)


def test_not_found_maps_to_query_error(backend):
    translated = _translated(
        backend, gexc.NotFound("Not found: Table test.test_dataset.orders")
    )
    assert isinstance(translated, QueryError)
    assert translated.retryable is False
    _assert_diagnostics(translated, 404)


def test_forbidden_maps_to_database_error_without_retry(backend):
    translated = _translated(backend, gexc.Forbidden("Access Denied: Project test"))
    assert isinstance(translated, DatabaseError)
    assert not isinstance(translated, InfrastructureError)
    assert translated.transient is False
    assert translated.retryable is False
    _assert_diagnostics(translated, 403)


def test_unauthorized_maps_to_database_error_without_retry(backend):
    translated = _translated(backend, gexc.Unauthorized("Invalid credentials"))
    assert isinstance(translated, DatabaseError)
    assert not isinstance(translated, InfrastructureError)
    assert translated.retryable is False
    _assert_diagnostics(translated, 401)


def test_rate_limit_is_a_transient_operational_error(backend):
    translated = _translated(backend, gexc.TooManyRequests("Exceeded rate limits"))
    assert isinstance(translated, OperationalError)
    assert isinstance(translated, InfrastructureError)
    assert translated.transient is True
    assert translated.retryable is True
    _assert_diagnostics(translated, 429)


def test_resource_exhausted_is_a_transient_operational_error(backend):
    translated = _translated(backend, gexc.ResourceExhausted("Quota exceeded"))
    assert isinstance(translated, OperationalError)
    assert translated.transient is True
    assert translated.retryable is True
    _assert_diagnostics(translated, 429)


def test_service_unavailable_is_a_transient_operational_error(backend):
    translated = _translated(backend, gexc.ServiceUnavailable("Backend unavailable"))
    assert isinstance(translated, OperationalError)
    assert isinstance(translated, InfrastructureError)
    assert translated.transient is True
    assert translated.retryable is True
    _assert_diagnostics(translated, 503)


def test_deadline_exceeded_is_a_transient_operational_error(backend):
    translated = _translated(backend, gexc.DeadlineExceeded("Query timed out"))
    assert isinstance(translated, OperationalError)
    assert translated.transient is True
    assert translated.retryable is True
    _assert_diagnostics(translated, 504)


def test_gateway_timeout_is_a_transient_operational_error(backend):
    translated = _translated(backend, gexc.GatewayTimeout("Gateway timeout"))
    assert isinstance(translated, OperationalError)
    assert translated.transient is True
    _assert_diagnostics(translated, 504)


def test_internal_server_error_is_a_transient_operational_error(backend):
    translated = _translated(backend, gexc.InternalServerError("jobInternalError"))
    assert isinstance(translated, OperationalError)
    assert isinstance(translated, InfrastructureError)
    assert translated.transient is True
    assert translated.retryable is True
    _assert_diagnostics(translated, 500)


def test_internal_server_error_analysis_failure_stays_a_query_error(backend):
    translated = _translated(
        backend, gexc.InternalServerError("Failed to analyze query: syntax error")
    )
    assert isinstance(translated, QueryError)
    assert translated.retryable is False
    _assert_diagnostics(translated, 500)


def test_invalid_argument_maps_to_query_error(backend):
    translated = _translated(
        backend, gexc.InvalidArgument("Invalid table name: `bad name`")
    )
    assert isinstance(translated, QueryError)
    assert translated.retryable is False
    _assert_diagnostics(translated, 400)


def test_failed_precondition_constraint_maps_to_integrity(backend):
    translated = _translated(
        backend,
        gexc.FailedPrecondition("Cannot add row: unique constraint violated"),
    )
    assert isinstance(translated, IntegrityError)
    _assert_diagnostics(translated, 400)


def test_aborted_is_operational_and_never_a_lock_error(backend):
    translated = _translated(backend, gexc.Aborted("Transaction aborted due to conflict"))
    assert isinstance(translated, OperationalError)
    assert translated.transient is True
    assert not isinstance(translated, LockError)
    assert not isinstance(translated, DeadlockError)
    _assert_diagnostics(translated, 409)


def test_connection_failure_maps_to_connection_error(backend):
    translated = _translated(backend, builtins.ConnectionError("Connection reset by peer"))
    assert isinstance(translated, ConnectionError)
    assert isinstance(translated, InfrastructureError)
    assert translated.transient is True
    assert translated.retryable is True
    _assert_diagnostics(translated, None)


def test_generic_exception_maps_to_database_error(backend):
    translated = _translated(backend, ValueError("boom"))
    assert isinstance(translated, DatabaseError)
    assert not isinstance(
        translated,
        (DataError, InfrastructureError, IntegrityError, QueryError),
    )
    assert translated.retryable is False
    _assert_diagnostics(translated, None)


def test_status_wins_over_message_text(backend):
    # A 404 reply whose text mentions a duplicate stays a query error: the
    # class/status decides, the message only refines an unplaced reply.
    translated = _translated(
        backend, gexc.NotFound("Duplicate table name is not the issue")
    )
    assert isinstance(translated, QueryError)
    _assert_diagnostics(translated, 404)


@pytest.mark.parametrize(
    "status,expected_class",
    [
        (401, gexc.Unauthorized),
        (403, gexc.Forbidden),
        (429, gexc.TooManyRequests),
        (503, gexc.ServiceUnavailable),
        (504, gexc.GatewayTimeout),
    ],
)
def test_emulator_http_error_keeps_status_specific_class(status, expected_class):
    # The emulator REST fast path has to raise a class whose ``code`` is the
    # real HTTP status, otherwise 429/503/504 lose their transient mapping.
    with pytest.raises(expected_class):
        BigQueryBackend._raise_http_error(status, "emulator error")
