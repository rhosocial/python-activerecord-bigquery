"""Adapter tests for BigQuery backend."""


def test_struct_adapter():
    from rhosocial.activerecord.backend.impl.bigquery.adapters import BigQueryStructAdapter
    adapter = BigQueryStructAdapter()
    assert adapter.to_database({"a": 1}, dict) == {"a": 1}
