# tests/rhosocial/activerecord_bigquery_test/feature/backend/errors/test_error_taxonomy_contract.py
"""Run the testsuite's semantic error taxonomy contract for BigQuery.

The contract only imports the core taxonomy; it needs no database and no
BigQuery driver. Importing it here gives this backend's suite the same
hierarchy/retry/diagnostics assertions every backend must satisfy.
"""

from rhosocial.activerecord.testsuite.feature.backend.errors.test_error_taxonomy import *  # noqa: F401,F403
