"""Async backend feature tests."""


def test_async_backend_init():
    from rhosocial.activerecord.backend.impl.bigquery import AsyncBigQueryBackend
    backend = AsyncBigQueryBackend(project="test", dataset="test")
    assert backend.config.project == "test"
