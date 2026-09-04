# tests/rhosocial/activerecord_bigquery_test/feature/backend/transactions/test_transaction_backend.py
"""Transaction backend tests."""


def test_transaction_manager_exists():
    from rhosocial.activerecord.backend.impl.bigquery import BigQueryBackend
    backend = BigQueryBackend(project="test", dataset="test")
    assert backend.transaction_manager is not None


def test_savepoint_context():
    from rhosocial.activerecord.backend.impl.bigquery.transaction import BigQueryTransactionManager
    from rhosocial.activerecord.backend.impl.bigquery import BigQueryBackend
    backend = BigQueryBackend(project="test", dataset="test")
    manager = BigQueryTransactionManager(backend)
    with manager.savepoint("sp1"):
        pass  # savepoint yields successfully
