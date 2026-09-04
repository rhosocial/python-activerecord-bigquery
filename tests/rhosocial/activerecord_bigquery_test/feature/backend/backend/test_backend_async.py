# tests/rhosocial/activerecord_bigquery_test/feature/backend/backend/test_backend_async.py
"""Async backend feature tests (twin of test_backend.py)."""


def test_async_backend_init():
    from rhosocial.activerecord.backend.impl.bigquery import AsyncBigQueryBackend
    backend = AsyncBigQueryBackend(project="test", dataset="test")
    assert backend.config.project == "test"
