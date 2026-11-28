# tests/rhosocial/activerecord_bigquery_test/feature/backend/core/test_special_registry_injection.py
"""Regression: special constructors live on an explicit registry, never on import.

The round-trip matrix used to call ``register_specials()`` at import time against
a module global, so which entries existed depended on whether this consumer or
the matrix was collected first. Now a registry is built by the caller and passed
to every adapter explicitly. This module is the synthetic second consumer used
to prove both collection orders work in one pytest process.
"""

import importlib

import pytest

from rhosocial.activerecord.backend.expression.core import Literal
from rhosocial.activerecord_bigquery_test.feature.backend import expression_roundtrip_harness as harness
from rhosocial.activerecord_bigquery_test.feature.backend.core import (
    test_expression_roundtrip_all as matrix,
)

MATRIX_MODULE = (
    "rhosocial.activerecord_bigquery_test.feature.backend.core."
    "test_expression_roundtrip_all"
)


def test_registry_keys_are_stable_across_module_import():
    """A registry created before and after importing the matrix has the same keys."""
    before = set(harness.SpecialConstructorRegistry().entries)
    module = importlib.import_module(MATRIX_MODULE)
    after = set(harness.SpecialConstructorRegistry().entries)
    assert after == before

    # Even after the matrix's registrations run, a fresh registry is unchanged.
    module.register_specials(harness.SpecialConstructorRegistry())
    assert set(harness.SpecialConstructorRegistry().entries) == before


def test_register_specials_is_scoped_to_one_registry():
    """The matrix's specials exist only on the registry handed to it."""
    registry = harness.SpecialConstructorRegistry()
    assert "operators.ArithmeticOperation" not in registry.entries
    assert not any(key.startswith("declared.") for key in registry.entries)

    matrix.register_specials(registry)
    assert "operators.ArithmeticOperation" in registry.entries
    assert sum(key.startswith("declared.") for key in registry.entries) == 10

    other = harness.SpecialConstructorRegistry()
    assert set(other.entries) == set(harness.SpecialConstructorRegistry().entries)
    assert "operators.ArithmeticOperation" not in other.entries


def test_adapters_require_an_explicit_registry():
    """Neither module-level adapter may fall back to a hidden global."""
    with pytest.raises(TypeError, match="registry"):
        harness.make_instance(Literal, None)
    with pytest.raises(TypeError, match="registry"):
        harness.register_special_constructor(fqn_suffix="suffix.Sentinel", factory=lambda d: None)


def test_explicit_registry_is_honoured_by_make_instance():
    """The adapter delegates construction to the registry it was given."""
    from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect

    registry = harness.SpecialConstructorRegistry()
    matrix.register_specials(registry)
    instance, source = harness.make_instance(Literal, BigQueryDialect(), registry)
    assert source == "special"
    assert instance is not None
