# tests/rhosocial/activerecord_bigquery_test/feature/backend/introspection/conftest.py
"""Declaration for the backend's introspection tests.

SQL generation, parsing and the CLI surface are checked against the emulator's
answers here.  The directory owns one dataset, so its tests share that dataset
serially per scenario and are grouped as one parallel subset.
"""
from rhosocial.activerecord.testsuite.pytest_plugin import Declaration

DECLARATION = Declaration(
    uses_database=True,
    parallel=True,
    purpose="BigQuery introspection SQL, answer parsing and the CLI report surface.",
    passes_means="introspection answers are parsed and reported as documented",
    fails_means="an introspection answer is misread or a CLI report is wrong",
)
