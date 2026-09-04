# tests/rhosocial/activerecord_bigquery_test/feature/backend/backend/test_backend.py
"""BigQuery backend mock execution test."""


def test_backend_init_with_project():
    from rhosocial.activerecord.backend.impl.bigquery import BigQueryBackend
    backend = BigQueryBackend(project="test", dataset="test")
    assert backend.config.project == "test"
