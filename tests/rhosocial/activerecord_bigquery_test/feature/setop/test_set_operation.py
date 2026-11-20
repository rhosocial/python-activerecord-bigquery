# tests/rhosocial/activerecord_bigquery_test/feature/setop/test_set_operation.py
"""
Bridge file for sync set operation tests from the testsuite.
"""
import pytest
try:
    from rhosocial.activerecord.testsuite.feature.setop.test_set_operation import *  # noqa: F403
except ImportError:
    pytest.skip("setop testsuite not available", allow_module_level=True)
