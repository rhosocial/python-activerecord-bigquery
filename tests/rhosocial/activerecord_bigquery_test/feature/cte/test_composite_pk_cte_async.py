# tests/rhosocial/activerecord_bigquery_test/feature/cte/test_composite_pk_cte_async.py
"""
Bridge file for composite PK async CTE query tests from the testsuite.
"""
import pytest
try:
    from rhosocial.activerecord.testsuite.feature.cte.test_composite_pk_cte_async import *  # noqa: F403
except ImportError:
    pytest.skip("composite_pk testsuite not available", allow_module_level=True)
