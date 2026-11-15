# tests/rhosocial/activerecord_bigquery_test/feature/basic/conftest.py
"""Fixtures shared by the basic topic.

``basic`` holds subdirectories, never test files, so this conftest re-exports
the shared topic's fixture definitions and declares no directory contract; the
minimal test sets live in ``nopk/`` and ``readonly/``.
"""
from rhosocial.activerecord.testsuite.feature.basic.conftest import *  # noqa: F403
