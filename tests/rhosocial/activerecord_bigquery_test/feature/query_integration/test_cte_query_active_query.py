# tests/rhosocial/activerecord_bigquery_test/feature/query_integration/test_cte_query_active_query.py
"""
Bridge file for CTEQuery + ActiveQuery combination tests from the testsuite.
"""
import pytest
try:
    from rhosocial.activerecord.testsuite.feature.query_integration.test_cte_query_active_query import *  # noqa: F403
except ImportError:
    pytest.skip("CTEQuery + ActiveQuery testsuite not available", allow_module_level=True)
