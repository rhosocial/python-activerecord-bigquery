"""Config tests for BigQuery backend."""


def test_config_init():
    from rhosocial.activerecord.backend.impl.bigquery import BigQueryConnectionConfig
    config = BigQueryConnectionConfig(project="my-project", dataset="my_dataset")
    assert config.project == "my-project"
    assert config.dataset == "my_dataset"
