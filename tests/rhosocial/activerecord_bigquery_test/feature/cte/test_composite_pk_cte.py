# tests/rhosocial/activerecord_bigquery_test/feature/cte/test_composite_pk_cte.py
"""
Bridge file for composite PK CTE query tests from the testsuite.
"""
import pytest
try:
    from rhosocial.activerecord.testsuite.feature.cte.test_composite_pk_cte import *  # noqa: F403
except ImportError:
    pytest.skip("composite_pk testsuite not available", allow_module_level=True)
