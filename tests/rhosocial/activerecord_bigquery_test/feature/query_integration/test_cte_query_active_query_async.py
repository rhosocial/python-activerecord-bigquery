# tests/rhosocial/activerecord_bigquery_test/feature/query_integration/test_cte_query_active_query_async.py
"""
Bridge file for async CTEQuery + ActiveQuery combination tests from the testsuite.
"""
import pytest
try:
    from rhosocial.activerecord.testsuite.feature.query_integration.test_cte_query_active_query_async import *  # noqa: F403
except ImportError:
    pytest.skip("async CTEQuery + ActiveQuery testsuite not available", allow_module_level=True)
