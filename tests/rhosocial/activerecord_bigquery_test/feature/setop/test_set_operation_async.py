# tests/rhosocial/activerecord_bigquery_test/feature/setop/test_set_operation_async.py
"""
Bridge file for async set operation tests from the testsuite.
"""
import pytest
try:
    from rhosocial.activerecord.testsuite.feature.setop.test_set_operation_async import *  # noqa: F403
except ImportError:
    pytest.skip("setop testsuite not available", allow_module_level=True)
