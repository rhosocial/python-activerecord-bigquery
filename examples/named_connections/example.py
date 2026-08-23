"""Example named connection for BigQuery backend."""
from rhosocial.activerecord.backend.impl.bigquery import BigQueryBackend, BigQueryConnectionConfig


if __name__ == "__main__":
    config = BigQueryConnectionConfig(
        project="my-gcp-project",
        dataset="example_dataset",
    )
    backend = BigQueryBackend(connection_config=config)
    backend.connect()
    print("Connected to BigQuery")
    backend.disconnect()
