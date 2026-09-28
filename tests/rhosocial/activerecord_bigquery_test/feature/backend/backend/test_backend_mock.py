"""Mock backend tests for BigQuery."""


def test_backend_init():
    from rhosocial.activerecord.backend.impl.bigquery.backend import BigQueryBackend
    backend = BigQueryBackend(project="test", dataset="test")
    assert backend is not None
