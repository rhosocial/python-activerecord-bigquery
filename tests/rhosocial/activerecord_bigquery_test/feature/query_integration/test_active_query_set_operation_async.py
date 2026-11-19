# tests/rhosocial/activerecord_bigquery_test/feature/query_integration/test_active_query_set_operation_async.py
"""
Bridge file for async ActiveQuery + SetOperationQuery combination tests from the testsuite.
"""
import pytest
try:
    from rhosocial.activerecord.testsuite.feature.query_integration.test_active_query_set_operation_async import *  # noqa: F403
except ImportError:
    pytest.skip("async ActiveQuery + SetOperationQuery testsuite not available", allow_module_level=True)
