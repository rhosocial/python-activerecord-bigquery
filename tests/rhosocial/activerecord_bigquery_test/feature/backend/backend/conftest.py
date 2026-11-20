# tests/rhosocial/activerecord_bigquery_test/feature/backend/backend/conftest.py
"""Declaration for the backend's lifecycle and scenario wiring tests.

These tests build the backend, read its configuration, and load the emulator
scenario.  They run against the shared emulator endpoint, so the directory is
one parallel subset: serial per scenario, isolated from other scenarios.
"""
from rhosocial.activerecord.testsuite.pytest_plugin import Declaration

DECLARATION = Declaration(
    uses_database=True,
    parallel=True,
    purpose="BigQuery backend lifecycle, configuration and emulator scenario wiring.",
    passes_means="the backend builds, configures and dispatches as documented",
    fails_means="backend construction or scenario configuration is wrong",
)
