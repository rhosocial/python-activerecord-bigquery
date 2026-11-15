# tests/rhosocial/activerecord_bigquery_test/feature/logging/conftest.py
"""The logging tests are unit-level: this directory needs no database.

The shared suite has no ``logging`` fixture group, so there is nothing to
import and no ``prepare`` / ``teardown`` group to declare.  The cases here
build a backend (synchronous and asynchronous) and drive it through
in-process fakes: they never request the testsuite ``environment`` fixture,
never construct a real ``google.cloud.bigquery`` client and never reach the
emulator.  A ``database`` / ``schema`` pair would only force a connection
these tests do not use, so the directory keeps no L2 fixtures.
"""
