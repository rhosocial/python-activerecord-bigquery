# tests/rhosocial/activerecord_bigquery_test/feature/query_integration/test_cte_query_set_operation.py
"""
Bridge file for CTEQuery + SetOperationQuery combination tests from the testsuite.
"""
import pytest
try:
    from rhosocial.activerecord.testsuite.feature.query_integration.test_cte_query_set_operation import *  # noqa: F403
except ImportError:
    pytest.skip("CTEQuery + SetOperationQuery testsuite not available", allow_module_level=True)
