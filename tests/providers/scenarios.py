# tests/providers/scenarios.py
"""BigQuery test scenario configuration."""
import os
from typing import Dict, Any, Tuple, Type

from rhosocial.activerecord.backend.impl.bigquery import BigQueryBackend
from rhosocial.activerecord.backend.impl.bigquery.config import BigQueryConnectionConfig

SCENARIO_MAP: Dict[str, Dict[str, Any]] = {}


def register_scenario(name: str, config: Dict[str, Any]):
    SCENARIO_MAP[name] = config


def get_scenario_raw(name: str) -> Tuple[Type[BigQueryBackend], BigQueryConnectionConfig]:
    if name not in SCENARIO_MAP:
        if SCENARIO_MAP:
            name = next(iter(SCENARIO_MAP))
        else:
            raise ValueError("No BigQuery scenarios registered")
    config = BigQueryConnectionConfig(**SCENARIO_MAP[name])
    return BigQueryBackend, config


def get_scenario(name: str) -> Tuple[Type[BigQueryBackend], BigQueryConnectionConfig]:
    return get_scenario_raw(name)


def get_enabled_scenarios() -> Dict[str, Any]:
    return SCENARIO_MAP


def _load_scenarios_from_config():
    import yaml
    env_path = os.getenv("BIGQUERY_SCENARIOS_CONFIG_PATH")
    if env_path and os.path.exists(env_path):
        config_path = env_path
    else:
        config_path = os.path.join(os.path.dirname(__file__), "..", "config", "bigquery_scenarios.yaml")
        if not os.path.exists(config_path):
            return
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    for scenario_name, config in data.get("scenarios", {}).items():
        register_scenario(scenario_name, config)
    _apply_emulator_port_override()
    _apply_filter()


def _apply_emulator_port_override():
    """Point the emulator scenario at an alternate port (parallel CI shards).

    When multiple emulator containers run on distinct host ports (one per
    parallel testsuite shard), each pytest process overrides ``api_endpoint``
    through ``BIGQUERY_EMULATOR_PORT`` so it talks to its own shard's
    container. Port 9050 is the default used by the committed config.
    """
    port = os.getenv("BIGQUERY_EMULATOR_PORT")
    if not port:
        return
    for config in SCENARIO_MAP.values():
        endpoint = config.get("api_endpoint")
        if not endpoint:
            continue
        from urllib.parse import urlparse, urlunparse
        parts = urlparse(endpoint)
        if parts.port is not None:
            parts = parts._replace(netloc=f"{parts.hostname}:{port}")
            config["api_endpoint"] = urlunparse(parts)


def _apply_filter():
    filter_str = os.getenv("BIGQUERY_ACTIVE_SCENARIOS") or os.getenv("TESTSUITE_ACTIVE_SCENARIOS")
    if not filter_str:
        return
    allowed = set(s.strip() for s in filter_str.split(",") if s.strip())
    if not allowed:
        return
    to_remove = [name for name in SCENARIO_MAP if name not in allowed]
    for name in to_remove:
        del SCENARIO_MAP[name]

_load_scenarios_from_config()
