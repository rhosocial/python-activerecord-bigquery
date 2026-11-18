# tests/rhosocial/activerecord_bigquery_test/feature/backend/core/conftest.py
"""Shared setup for this directory's live-endpoint probes.

The live files here talk to the emulator directly rather than through the
testsuite environment, so they own their own connections.  The dataset is still
the directory's: derived from the path and reset once per (scenario, dataset),
so a probe never reads tables another directory owns.
"""
from rhosocial.activerecord.testsuite.pytest_plugin import Declaration
import os

import pytest

from rhosocial.activerecord.testsuite.pytest_plugin.declarations import database_name

DECLARATION = Declaration(
    parallel=True,
    purpose="Live-endpoint probes against the emulator on this directory's dataset.",
    passes_means="the emulator answers the probe against a clean directory-owned dataset",
    fails_means="a probe reads another directory's data or a live assertion is wrong",
)

PREPARED_DATASETS = set()


@pytest.fixture(name="live_dataset")
def live_dataset(request):
    """Return ``(scenario, dataset)`` for this directory, dataset prepared."""
    scenarios = pytest.importorskip(
        "support.bigquery",
        reason="the scenario loader is imported with PYTHONPATH=tests",
    )
    enabled = scenarios.get_enabled_scenarios()
    name = "bigquery_emulator" if "bigquery_emulator" in enabled else next(iter(enabled), None)
    if name is None:
        pytest.skip("no BigQuery scenario configured")
    current = scenarios.scenario(name)
    dataset = database_name(os.path.dirname(os.fspath(request.node.path)))
    key = (current.name, dataset)
    if key not in PREPARED_DATASETS:
        try:
            current.reset_database(dataset)
        except Exception as exc:  # noqa: BLE001 -- an unreachable endpoint is a skip
            pytest.skip(f"no reachable BigQuery endpoint: {exc}")
        PREPARED_DATASETS.add(key)
    return current, dataset
