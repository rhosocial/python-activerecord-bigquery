"""Integration tests using BigQuery emulator."""
import pytest
import os

os.environ.setdefault("BIGQUERY_SCENARIOS_CONFIG_PATH", "tests/config/bigquery_scenarios.yaml")
os.environ.setdefault("BIGQUERY_ACTIVE_SCENARIOS", "bigquery_emulator")


def test_integration_scenarios_loaded():
    from tests.providers.scenarios import SCENARIO_MAP, get_scenario
    assert "bigquery_emulator" in SCENARIO_MAP


def test_integration_config_has_endpoint():
    from tests.providers.scenarios import get_scenario_raw
    backend_class, config = get_scenario_raw("bigquery_emulator")
    assert config.api_endpoint == "http://localhost:9050"
    assert config.use_anonymous_credentials is True
