# tests/rhosocial/activerecord_bigquery_test/feature/backend/protocol/test_introspection_protocol_families.py
"""Guard: the four introspection families replaced one protocol.

Core's ``a013d5d4`` split the single ``IntrospectionSupport`` protocol into
four families -- structure, operational statistics, data profiling and DDL
extraction -- each with an async twin, and deleted
``supports_partition_info``. The old name must not survive here as an alias,
and this dialect's duplicate partition switch must not survive either: the
surviving switch is ``supports_partition_metadata_introspection`` in
``mixins/partition.py``, which also answered ``True``, so deleting the
duplicate changed no behaviour.
"""

import re
from pathlib import Path

import pytest
from rhosocial.activerecord.backend.dialect import protocols as dialect_protocols
from rhosocial.activerecord.backend.dialect.protocols.introspect import (
    data_profile,
    ddl_extraction,
    operational_stats,
    structure,
)
from rhosocial.activerecord.backend.introspection.types import PartitionState

from rhosocial.activerecord.backend import dialect as dialect_module
from rhosocial.activerecord.backend.impl.bigquery.cli import introspect as introspect_cli
from rhosocial.activerecord.backend.impl.bigquery.config import (
    BigQueryConnectionConfig,
)
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect
from rhosocial.activerecord.backend.impl.bigquery.introspection import (
    BigQueryIntrospector,
)

#: sync protocol name -> the module core declares it in.
FAMILY_MODULES = {
    "StructureIntrospectionSupport": structure,
    "AsyncStructureIntrospectionSupport": structure,
    "OperationalStatsIntrospectionSupport": operational_stats,
    "AsyncOperationalStatsIntrospectionSupport": operational_stats,
    "DataProfileIntrospectionSupport": data_profile,
    "AsyncDataProfileIntrospectionSupport": data_profile,
    "DdlExtractionIntrospectionSupport": ddl_extraction,
    "AsyncDdlExtractionIntrospectionSupport": ddl_extraction,
}

#: The retired names, asserted absent rather than assumed gone.
RETIRED_NAMES = ("IntrospectionSupport", "AsyncIntrospectionSupport")


class _BackendStandIn:
    """The attributes BigQueryIntrospector reads off a backend."""

    def __init__(self) -> None:
        self.dialect = BigQueryDialect()
        self.config = BigQueryConnectionConfig(project="my-project", dataset="my_dataset")
        self._version = (3, 0, 0)


class _RecordingExecutor:
    """Answers nothing; the guard never executes a statement."""

    def execute(self, sql, params=()):
        return []


@pytest.fixture
def dialect() -> BigQueryDialect:
    return BigQueryDialect()


@pytest.fixture
def introspector() -> BigQueryIntrospector:
    return BigQueryIntrospector(_BackendStandIn(), _RecordingExecutor())


class TestTheDuplicatePartitionProbeIsGone:
    """One partition metadata switch survives; the duplicate is deleted."""

    def test_the_dialect_has_no_duplicate_probe(self, dialect):
        assert hasattr(dialect, "supports_partition_info") is False
        assert getattr(dialect, "supports_partition_info", None) is None

    def test_the_inspector_has_no_duplicate_probe(self, introspector):
        assert hasattr(introspector, "supports_partition_info") is False

    def test_the_metadata_probe_is_callable_and_true(self, dialect):
        assert callable(dialect.supports_partition_metadata_introspection)
        assert dialect.supports_partition_metadata_introspection() is True

    def test_the_metadata_probe_is_declared_by_the_partition_mixin(self, dialect):
        """The surviving answer comes from ``mixins/partition.py``, not a default."""
        from rhosocial.activerecord.backend.impl.bigquery.mixins.partition import (
            BigQueryPartitionMixin,
        )

        assert "supports_partition_metadata_introspection" in vars(BigQueryPartitionMixin)
        assert "supports_partition_info" not in vars(BigQueryPartitionMixin)


class TestTheCliFamilyMapPointsAtTheSurvivingProbe:
    """``partitions`` is gated by the one probe that still exists."""

    def test_the_map_names_the_metadata_probe(self):
        switch = introspect_cli._TYPE_CAPABILITIES["partitions"]
        assert switch == "supports_partition_metadata_introspection"
        assert switch != "supports_partition_info"

    def test_the_named_switch_resolves_on_the_dialect(self, dialect):
        switch = introspect_cli._TYPE_CAPABILITIES["partitions"]
        probe = getattr(dialect, switch, None)
        assert callable(probe)
        assert probe() is True

    def test_the_capability_gate_lets_partitions_through(self, dialect, monkeypatch):
        """The gate is what a refused CLI type exits on, so it must not refuse."""
        import argparse

        args = argparse.Namespace(command="partitions", name="orders")

        class _Backend:
            pass

        _Backend.dialect = dialect
        introspect_cli._require_capability(_Backend(), args)


class _UnpartitionedTableExecutor:
    """Answers the catalog for one existing table with no partition signal."""

    def execute(self, sql, params=()):
        if "PARTITIONS" in sql:
            # An unpartitioned table's single catalogue row: "no partitions".
            return [{"table_name": "orders", "partition_id": None, "total_rows": 3}]
        if "TABLES" in sql:
            return [{"table_name": "orders", "table_type": "BASE TABLE"}]
        return []


class TestPartitioningIsAlwaysAPartitionState:
    """``TableState.partitioning`` is never ``None``; empty state instead.

    Core's ``1f177724`` made the field non-optional and made
    ``PartitionState.scheme = None`` the single neutral answer for "not
    partitioned". These guards pin both halves: no source or test may pass or
    test a ``None`` partitioning, and the runtime answer really is a
    ``PartitionState`` rather than a ``None`` object.
    """

    PARTITIONING_NONE_PATTERNS = (
        re.compile(r"\bpartitioning\s*=\s*None\b"),
        re.compile(r"\bpartitioning\s+is\s+None\b"),
    )

    def test_no_source_or_test_passes_or_tests_none_partitioning(self):
        root = Path(__file__).resolve().parents[6]
        offenders = []
        for tree in ("src", "tests"):
            for path in (root / tree).rglob("*.py"):
                text = path.read_text(encoding="utf-8", errors="replace")
                for pattern in self.PARTITIONING_NONE_PATTERNS:
                    if pattern.search(text):
                        offenders.append(f"{path.relative_to(root)}: {pattern.pattern}")

        assert not offenders, "None-partitioning spellings remain:\n" + "\n".join(
            f"  - {offender}" for offender in offenders
        )

    def test_an_unpartitioned_table_answers_a_partition_state(self):
        introspector = BigQueryIntrospector(_BackendStandIn(), _UnpartitionedTableExecutor())

        state = introspector.get_partition_state("orders", "my_dataset")

        assert isinstance(state, PartitionState)
        assert state.scheme is None
        assert state.bounds == ()


class TestTheFourFamiliesAreImportableAndTheOldNamesAreNot:
    """Each family lives in its own core module; the single name is gone."""

    @pytest.mark.parametrize(
        "name,module",
        list(FAMILY_MODULES.items()),
        ids=list(FAMILY_MODULES),
    )
    def test_the_family_is_importable_from_its_declaring_module(self, name, module):
        protocol = getattr(module, name)
        assert protocol is getattr(dialect_protocols, name)
        assert protocol.__module__ == module.__name__

    @pytest.mark.parametrize("name", RETIRED_NAMES)
    def test_the_old_single_names_are_not_exported(self, name):
        assert not hasattr(dialect_protocols, name)
        assert not hasattr(dialect_module, name)

    def test_the_legacy_names_are_absent_from_this_repositorys_src(self):
        """A rename of the family classes must not reintroduce the old name."""
        root = Path(__file__).resolve().parents[6] / "src"
        patterns = {label: re.compile(rf"\b{label}\b") for label in RETIRED_NAMES}
        patterns["supports_partition_info"] = re.compile(r"\bsupports_partition_info\b")
        offenders = []
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            for label, pattern in patterns.items():
                if pattern.search(text):
                    offenders.append(f"{path.relative_to(root)}: {label}")

        assert not offenders, "legacy introspection names remain in src:\n" + "\n".join(
            f"  - {offender}" for offender in offenders
        )
