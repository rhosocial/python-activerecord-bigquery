# tests/rhosocial/activerecord_bigquery_test/feature/backend/conftest.py
"""Root declaration for this backend's own feature tests.

Only this backend's subjects live below here: they are kept alongside the
testsuite's shared ``feature/basic`` group because each backend owns the
specials its dialect cannot share.  The declaration here is deliberately
``parallel=False`` -- the pure-render subjects (``dialect/``, ``expression/``,
``types/`` and the like) only build and inspect SQL and must stay free to run
in unlimited parallel.  A subject that opens a connection or owns a dataset
declares ``parallel=True`` in its own conftest instead, so the directory is
serialised per scenario while rendering-only work is not held back.
"""
from rhosocial.activerecord.testsuite.pytest_plugin import Declaration

DECLARATION = Declaration(
    parallel=False,
    purpose="BigQuery backend's own feature tests: dialect specials and scenario wiring.",
    passes_means="a backend-specific contract renders or dispatches as documented",
    fails_means="a BigQuery-only behaviour drifts from the contract its dialect declares",
)
