# tests/rhosocial/activerecord_bigquery_test/feature/backend/dialect/test_dialect_artifact_registry.py
"""The dialect publishes the kinds its own backend can read, and only those.

An expression artifact is data: it carries kinds, not a dialect. A read needs a
name authority, and ownership decides which one:

* core assembles core's kinds (:func:`core_registry`);
* this backend assembles its own kinds on top of core's, by composition
  (``registry_for_packages(<this package>, base=core_registry())``), which is
  what :func:`backend_registry` returns;
* the dialect hands that table to every reader as
  ``BigQueryDialect.artifact_registry()``, frozen and cached.

So a BigQuery-proprietary kind resolves through this dialect, a kind belonging
to another owner is refused by name, and core's table does not carry BigQuery's
kinds. Everything here is construction and reflection: no connection.
"""

import pytest

from rhosocial.activerecord.backend.expression.core import Column
from rhosocial.activerecord.backend.expression.registry import (
    RegistryError,
    RegistryReason,
)
from rhosocial.activerecord.backend.expression.serialization import (
    core_registry,
    deserialize,
    serialize,
)
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect
from rhosocial.activerecord.backend.impl.bigquery.expression import (
    BigQueryPartitionDecoratedTable,
)
from rhosocial.activerecord.backend.impl.bigquery.registry import backend_registry

#: A kind this backend does not own, named rather than imported: the answer is
#: a name refusal, so the other backend need not be installed to ask.
FOREIGN_KIND = "sqlite_vacuum_statement"


def test_the_registry_is_the_dialects_own_composition():
    """One cached, frozen table: core's kinds plus this backend's."""
    registry = backend_registry()
    assert registry is BigQueryDialect().artifact_registry()
    assert registry is BigQueryDialect().artifact_registry(), "the table is not cached"
    assert registry.is_frozen

    kinds = registry.node_kinds()
    assert "column" in kinds, "core's kinds are the base of the composition"
    assert BigQueryPartitionDecoratedTable.kind() in kinds
    assert not [
        kind for kind in kinds if kind.startswith("sqlite_")
    ], "the backend's registry carries another backend's kinds"


def test_a_bigquery_proprietary_kind_resolves_through_the_dialect():
    """The dialect is the name authority for the kinds its backend owns.

    A read with the dialect and no explicit registry selects
    ``dialect.artifact_registry()``, so a proprietary node comes back as
    itself -- no global registration, no per-test setup.
    """
    dialect = BigQueryDialect()
    kind = BigQueryPartitionDecoratedTable.kind()
    assert dialect.artifact_registry().resolve_node(kind) is BigQueryPartitionDecoratedTable

    original = BigQueryPartitionDecoratedTable(dialect, "events", "20260101")
    restored = deserialize(serialize(original), dialect)
    assert isinstance(restored, BigQueryPartitionDecoratedTable)
    assert restored.to_sql() == original.to_sql()


def test_a_foreign_kind_is_refused_by_name():
    """Another owner's kind is not in this table, so it is refused, not guessed."""
    registry = BigQueryDialect().artifact_registry()
    with pytest.raises(RegistryError) as caught:
        registry.resolve_node(FOREIGN_KIND)
    assert caught.value.reason is RegistryReason.KIND_NOT_REGISTERED
    assert FOREIGN_KIND in str(caught.value)


def test_the_published_registry_is_frozen():
    """A reader cannot widen the table every other reader resolves through."""
    registry = BigQueryDialect().artifact_registry()
    with pytest.raises(RegistryError) as caught:
        registry.register_node(BigQueryPartitionDecoratedTable)
    assert caught.value.reason is RegistryReason.REGISTRY_FROZEN
    assert BigQueryPartitionDecoratedTable.kind() in str(caught.value)


def test_core_registry_does_not_carry_this_backends_kinds():
    """Ownership is symmetric: core composes no backend, and no backend leaks in."""
    kind = BigQueryPartitionDecoratedTable.kind()
    core = core_registry()
    assert kind not in core.node_kinds()
    with pytest.raises(RegistryError) as caught:
        core.resolve_node(kind)
    assert caught.value.reason is RegistryReason.KIND_NOT_REGISTERED
    assert core.resolve_node("column") is Column
