# tests/rhosocial/activerecord_bigquery_test/feature/backend/ddl/conftest.py
"""Declaration for the backend's DDL-rendering tests.

Create/alter-table and identity-clause rendering is checked here against the
emulator's supported surface.  The directory owns one dataset and is therefore
one parallel subset: tests share it serially per scenario.
"""
from rhosocial.activerecord.testsuite.pytest_plugin import Declaration

DECLARATION = Declaration(
    uses_database=True,
    parallel=True,
    purpose="BigQuery DDL rendering: create/alter table and identity-clause conformance.",
    passes_means="the rendered DDL matches the documented BigQuery spelling",
    fails_means="a DDL clause renders an unsupported spelling or silently drops a request",
)
