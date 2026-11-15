# tests/support/bigquery.py
"""The BigQuery backend's test scenarios.

BigQuery has two namespaces above a table: a project (catalog) and a dataset
(schema).  The scenario file holds the project and connection parameters only;
the logical dataset name comes from the test directory and is injected here.

Scenarios are read from the YAML named by ``BIGQUERY_SCENARIOS_CONFIG_PATH`` --
the variable the CI workflow exports -- falling back to the committed file.
``dataset``/``database`` keys in that file are dropped: a scenario names a
server (project plus endpoint), never the logical dataset.

Dataset provisioning goes through the driver's dataset API rather than SQL:
GoogleSQL's ``DROP SCHEMA`` is unsupported by the goccy emulator, and its
``CREATE SCHEMA`` is accepted without registering the dataset, so a table
created immediately afterwards fails with "dataset not found".  ``create_dataset``
/ ``delete_dataset`` are the one surface both the emulator and the real service
implement the same way.

There is no maintenance database: a BigQuery client addresses the project, and
dataset administration needs no dataset of its own.  A server-level connection
therefore carries no dataset at all, and this scenario declares no
``maintenance_database``.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse, urlunparse

import yaml

from rhosocial.activerecord.backend.impl.bigquery.backend import BigQueryBackend
from rhosocial.activerecord.backend.impl.bigquery.backend.async_backend import (
    AsyncBigQueryBackend,
)
from rhosocial.activerecord.backend.impl.bigquery.config import (
    BigQueryConnectionConfig,
)

CONFIG_PATH = Path(
    os.environ.get("BIGQUERY_SCENARIOS_CONFIG_PATH")
    or Path(__file__).resolve().parents[1] / "config" / "bigquery_scenarios.yaml"
)

# The scenario file describes a project (and endpoint), never a dataset: the
# logical name is derived from the test directory.  ``dataset``/``database``
# keys, if present, are dropped, and ``enabled`` is a scenario toggle rather
# than a connection parameter.
SERVER_ONLY_KEYS = ("database", "dataset", "enabled")


def _apply_emulator_port_override(server_map: Dict[str, Dict[str, Any]]) -> None:
    """Point every emulator scenario at this shard's container.

    CI runs several emulators on distinct host ports (one per parallel
    testsuite shard) and tells each pytest process which port is its own
    through ``BIGQUERY_EMULATOR_PORT``.  Port 9050 is the committed default.
    """
    port = os.environ.get("BIGQUERY_EMULATOR_PORT")
    if not port:
        return
    for server in server_map.values():
        endpoint = server.get("api_endpoint")
        if not endpoint:
            continue
        parts = urlparse(endpoint)
        if parts.port is not None:
            server["api_endpoint"] = urlunparse(
                parts._replace(netloc=f"{parts.hostname}:{port}")
            )


def _apply_active_filter(server_map: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Keep only the scenarios named by the active-scenario variable, if set.

    ``BIGQUERY_ACTIVE_SCENARIOS`` is what the workflow exports; the shared
    ``TESTSUITE_ACTIVE_SCENARIOS`` spelling is accepted as the same request.
    Order is preserved so scenario parameter ids stay stable.
    """
    filter_str = (
        os.environ.get("BIGQUERY_ACTIVE_SCENARIOS")
        or os.environ.get("TESTSUITE_ACTIVE_SCENARIOS")
    )
    if not filter_str:
        return server_map
    allowed = {name.strip() for name in filter_str.split(",") if name.strip()}
    if not allowed:
        return server_map
    selected = {
        name: server for name, server in server_map.items() if name in allowed
    }
    if not selected:
        raise ValueError(
            "Active-scenario filter matched none of the configured scenarios: "
            + ", ".join(sorted(allowed))
        )
    return selected


def _load_scenarios(path: Path = CONFIG_PATH) -> Dict[str, Dict[str, Any]]:
    """Load one server-parameter dict per scenario from the YAML file."""
    with open(path, "r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    entries = data.get("scenarios")
    if not entries:
        raise ValueError(f"{path} defines no scenarios")
    server_map = {
        name: {
            key: value
            for key, value in entry.items()
            if key not in SERVER_ONLY_KEYS
        }
        for name, entry in entries.items()
    }
    _apply_emulator_port_override(server_map)
    return _apply_active_filter(server_map)


SCENARIO_MAP = _load_scenarios()
SCENARIOS = tuple(SCENARIO_MAP)


@dataclass(frozen=True)
class BigQueryScenario:
    """One BigQuery test scenario: a project plus the backend classes."""

    name: str
    server: Dict[str, Any]
    backend_class: Any = BigQueryBackend
    async_backend_class: Any = AsyncBigQueryBackend

    @property
    def project(self) -> str:
        """The project this scenario's datasets live in."""
        return self.server.get("project") or "test"

    def make_config(self, database: Optional[str]) -> BigQueryConnectionConfig:
        """Return the connection configuration for this dataset on this project.

        ``None`` is a project-level connection: BigQuery needs no maintenance
        dataset to create, drop or list datasets.
        """
        return BigQueryConnectionConfig(**self.server, dataset=database)

    def _client(self):
        """Return the driver client for this scenario, with no dataset default.

        Dataset administration is not a query, so it is not reached through
        ``backend.execute``.  The backend still owns authentication selection,
        which is why the client is taken from a connected backend rather than
        built here a second time.
        """
        backend = self.backend_class(
            connection_config=BigQueryConnectionConfig(**self.server)
        )
        backend.connect()
        # ``BigQueryBackend`` keeps the driver client private and exposes no
        # dataset-administration method of its own.
        return backend._client

    def reset_database(self, database: str) -> None:
        """Drop and recreate ``database`` (a dataset) in this scenario's project."""
        # Imported here so collecting tests never requires the driver.
        from google.cloud.bigquery import Dataset, DatasetReference

        client = self._client()
        reference = DatasetReference(self.project, database)
        client.delete_dataset(reference, delete_contents=True, not_found_ok=True)
        dataset = Dataset(reference)
        location = self.server.get("location")
        if location:
            dataset.location = location
        client.create_dataset(dataset, exists_ok=True)


def scenario(name: str) -> BigQueryScenario:
    """Return the scenario called ``name``."""
    try:
        server = SCENARIO_MAP[name]
    except KeyError:
        raise KeyError(f"Unknown BigQuery scenario: {name}") from None
    return BigQueryScenario(name, server)


def get_enabled_scenarios():
    """Return the scenarios this backend enables, as a name -> server map."""
    return {name: dict(server) for name, server in SCENARIO_MAP.items()}


def get_scenario(name: str):
    """Return ``(backend_class, config)`` for a benchmark dataset."""
    current = scenario(name)
    current.reset_database("test_benchmark")
    return current.backend_class, current.make_config("test_benchmark")


def get_scenario_raw(name: str):
    """Return ``(backend_class, config)`` for a server-level connection.

    The configuration carries no dataset, because BigQuery has no maintenance
    database to connect to.  Falls back to the first configured scenario when
    CI enables only one.
    """
    resolved = name if name in SCENARIO_MAP else next(iter(SCENARIO_MAP), None)
    if resolved is None:
        raise KeyError("No %s scenario configured" % name)
    current = scenario(resolved)
    return current.backend_class, current.make_config(None)
