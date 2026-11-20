# tests/rhosocial/activerecord_bigquery_test/feature/query/basic/test_composite_pk_query_async.py
"""
Bridge file for composite PK async ActiveQuery tests from the testsuite.
"""
import pytest
try:
    from rhosocial.activerecord.testsuite.feature.query.basic.test_composite_pk_query_async import *  # noqa: F403
except ImportError:
    pytest.skip("composite_pk testsuite not available", allow_module_level=True)