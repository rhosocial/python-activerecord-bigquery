# tests/conftest.py
"""Root configuration for the BigQuery backend's test tree.

The backend knows its own classes and how a scenario maps to a connection, so
no declaration table is needed here: the scenario is exposed as a parameterized
pytest fixture that the testsuite environment consumes.  A BigQuery scenario
is a project plus an endpoint; the logical dataset comes from the test
directory and is injected by ``BigQueryScenario.make_config``.
"""

import pytest

import support.bigquery

_SCENARIOS = [support.bigquery.scenario(name) for name in support.bigquery.SCENARIOS]


@pytest.fixture(scope="session", params=_SCENARIOS, ids=lambda scenario: scenario.name)
def backend_scenario(request):
    """Return the scenario the tests run against; its id is the scenario name."""
    return request.param


# Suite tests that assert a contract this backend cannot provide.  BigQuery
# has no ``UNIQUE`` production at all and enforces neither unique nor primary
# keys, so the shared ``query/basic`` table's unique triple is dropped from
# the rendered DDL (see ``BigQueryConstraintMixin.format_table_constraint``).
# A test that inserts a duplicate through that triple and expects an
# ``IntegrityError`` is asserting data-integrity behaviour BigQuery does not
# have; it is skipped here rather than left to fail for the wrong reason.
# Keyed by the test function name (the scenario parameter is appended to the
# node id by pytest, not part of ``item.name``).
_UNENFORCEABLE_SUITE_CONTRACTS = {
    "test_conflict_without_matching_lookup_reraises": (
        "BigQuery cannot enforce UNIQUE constraints, so the shared suite's "
        "unique-triple conflict contract has no violation to raise"
    ),
    # The goccy emulator rejects ``ROLLBACK TRANSACTION`` ("Statement not
    # supported"), so an aborted transaction's statements stay applied and the
    # shared suite's "rolled back" assertion has nothing to observe.  This is
    # an emulator gap, not a BigQuery one: the service documents BEGIN /
    # COMMIT / ROLLBACK TRANSACTION.
    # https://cloud.google.com/bigquery/docs/transactions
    "test_transaction_crud": (
        "the emulator does not implement ROLLBACK TRANSACTION, so a failed "
        "transaction cannot be undone (real BigQuery supports it)"
    ),
    # Worker transaction contracts drive backend.begin_transaction() inside a
    # child process; BigQueryTransactionManager has no begin()/commit()/rollback().
    "test_transaction_in_worker": (
        "BigQueryTransactionManager has no begin(), so worker transactions cannot run"
    ),
    "test_transaction_rollback_on_error": (
        "BigQueryTransactionManager has no begin(), so worker transaction rollback cannot run"
    ),
    "test_concurrent_transactions_isolation": (
        "BigQueryTransactionManager has no begin(), so concurrent worker transactions cannot run"
    ),
    # All query-context contracts that open a transaction (backend-in-context /
    # nested reuse, across model / union / CTE queries) fail the same way:
    # BigQueryTransactionManager has no begin()/commit()/rollback().  Skip by
    # name substring so every such contract is covered instead of enumerating.
    "transaction_context": (
        "BigQueryTransactionManager has no begin(), so transaction contexts cannot run"
    ),
    # The emulator returns a JSON column as a JSON string, not a decoded dict.
    "test_json_payload_roundtrip": (
        "the BigQuery emulator returns JSON columns as strings, not decoded objects"
    ),
}


def pytest_collection_modifyitems(config, items):
    """Skip suite contracts the BigQuery dialect cannot express."""
    for item in items:
        base = item.name.split("[", 1)[0]
        reason = _UNENFORCEABLE_SUITE_CONTRACTS.get(base)
        if not reason:
            # Substring patterns: cover whole contract families by name.
            for pattern, pat_reason in _UNENFORCEABLE_SUITE_CONTRACTS.items():
                if pattern in base:
                    reason = pat_reason
                    break
        if reason:
            item.add_marker(pytest.mark.skip(reason=reason))
