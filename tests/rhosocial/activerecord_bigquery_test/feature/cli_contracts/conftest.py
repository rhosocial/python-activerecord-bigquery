# tests/rhosocial/activerecord_bigquery_test/feature/cli_contracts/conftest.py
"""Bridge the shared ``feature/cli`` contracts with a dedicated database.

The testsuite ``feature/cli`` conftest hardcodes the database name ``test_cli``.
Override the database name here with a unique one so this directory's parallel
subset stays isolated and does not collide with other CLI test directories.
"""
from rhosocial.activerecord.testsuite.feature.cli.conftest import *  # noqa: F401,F403
import pytest


@pytest.fixture(scope="session")
def database_config(backend_scenario):
    name = "test_cli_contracts"
    return backend_scenario, backend_scenario.make_config(name), name
