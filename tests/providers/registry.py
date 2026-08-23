"""Test provider registry for BigQuery backend."""
from rhosocial.activerecord.backend.impl.bigquery import BigQueryBackend, BigQueryConnectionConfig

PROVIDER_NAME = "bigquery"


def get_backend_config():
    return BigQueryConnectionConfig(
        project="test-project",
        dataset="test_dataset",
    )
