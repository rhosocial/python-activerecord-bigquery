# tests/rhosocial/activerecord_bigquery_test/feature/backend/core/test_get_type_adapters.py
"""DB-free tests for the BigQuery backends' type adapter inventory.

No BigQuery endpoint is contacted: the inventory is built from the adapter
registry both backends fill in ``__init__``, so bare, unconnected instances are
enough to exercise it.
"""

from typing import Tuple

import pytest

from rhosocial.activerecord.backend.impl.bigquery.adapters import (
    BigQueryArrayAdapter,
    BigQueryStructAdapter,
)
from rhosocial.activerecord.backend.impl.bigquery.backend.async_backend import (
    AsyncBigQueryBackend,
)
from rhosocial.activerecord.backend.impl.bigquery.backend.backend import (
    BigQueryBackend,
)
from rhosocial.activerecord.backend.type_adapter import (
    SQLTypeAdapter,
    TypeAdapterCatalogProtocol,
)


def _class_key(adapter: SQLTypeAdapter) -> Tuple[str, str]:
    """Identify an adapter by class, not by instance."""
    adapter_cls = type(adapter)
    return (adapter_cls.__module__, adapter_cls.__qualname__)


@pytest.fixture(
    params=[BigQueryBackend, AsyncBigQueryBackend],
    ids=["sync", "async"],
)
def backend(request):
    """An unconnected backend of the requested flavour."""
    return request.param(project="demo", dataset="demo")


def test_backend_implements_the_catalog_protocol(backend):
    assert isinstance(backend, TypeAdapterCatalogProtocol)


def test_inventory_is_a_non_empty_list_of_adapters(backend):
    adapters = backend.get_type_adapters()

    assert isinstance(adapters, list)
    assert adapters, "BigQuery registers adapters, so the inventory is not empty"
    assert all(isinstance(adapter, SQLTypeAdapter) for adapter in adapters)


def test_inventory_is_unique_by_adapter_class(backend):
    keys = [_class_key(adapter) for adapter in backend.get_type_adapters()]

    assert len(keys) == len(set(keys)), "an adapter class must appear only once"
    assert keys == sorted(keys), "the inventory is sorted by (module, qualname)"


def test_inventory_order_is_deterministic_and_fresh(backend):
    first = backend.get_type_adapters()
    second = backend.get_type_adapters()

    assert first is not second, "every call must return a new list"
    assert [_class_key(adapter) for adapter in second] == [
        _class_key(adapter) for adapter in first
    ]

    first.append(object())  # must not leak into the backend's state
    assert [_class_key(adapter) for adapter in backend.get_type_adapters()] == [
        _class_key(adapter) for adapter in second
    ]


def test_inventory_includes_the_bigquery_specific_adapters(backend):
    adapters = backend.get_type_adapters()

    assert any(isinstance(adapter, BigQueryArrayAdapter) for adapter in adapters)
    assert any(isinstance(adapter, BigQueryStructAdapter) for adapter in adapters)


def test_default_adapter_suggestions_is_unchanged(backend):
    assert callable(backend.get_default_adapter_suggestions)
    assert backend.get_default_adapter_suggestions()
