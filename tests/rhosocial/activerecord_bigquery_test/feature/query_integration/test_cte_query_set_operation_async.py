# tests/rhosocial/activerecord_bigquery_test/feature/query_integration/test_cte_query_set_operation_async.py
"""
Bridge file for async CTEQuery + SetOperationQuery combination tests from the testsuite.
"""
import pytest
try:
    from rhosocial.activerecord.testsuite.feature.query_integration.test_cte_query_set_operation_async import *  # noqa: F403
except ImportError:
    pytest.skip("async CTEQuery + SetOperationQuery testsuite not available", allow_module_level=True)
