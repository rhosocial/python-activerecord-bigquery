# tests/rhosocial/activerecord_bigquery_test/feature/backend/backend/test_integration_scenarios.py
"""Emulator scenario config loading tests."""
import pytest
import os

os.environ.setdefault("BIGQUERY_SCENARIOS_CONFIG_PATH", "tests/config/bigquery_scenarios.yaml")
os.environ.setdefault("BIGQUERY_ACTIVE_SCENARIOS", "bigquery_emulator")


def test_integration_scenarios_loaded():
    from support.bigquery import SCENARIO_MAP, get_scenario
    assert "bigquery_emulator" in SCENARIO_MAP


def test_integration_config_has_endpoint():
    """The scenario points at the emulator this run was given.

    CI shards the suite across emulator containers on distinct ports and tells
    each pytest process which one is its own through ``BIGQUERY_EMULATOR_PORT``;
    the committed scenario file names the default, 9050.
    """
    from support.bigquery import get_scenario_raw

    backend_class, config = get_scenario_raw("bigquery_emulator")
    port = os.environ.get("BIGQUERY_EMULATOR_PORT", "9050")
    assert config.api_endpoint == f"http://localhost:{port}"
    assert config.use_anonymous_credentials is True
