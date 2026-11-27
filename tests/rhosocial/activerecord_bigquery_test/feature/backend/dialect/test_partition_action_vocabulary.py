# tests/rhosocial/activerecord_bigquery_test/feature/backend/dialect/test_partition_action_vocabulary.py
"""Every partition action is declared, and every one answers False.

BigQuery has no partition-action statements: a partition is a property of the
table, derived from the row's partition column, so nothing can be added,
dropped, split, merged, swapped, moved, analysed or removed by name. The
capability surface still declares each action, because "the engine has no such
statement" is a definite answer a caller can act on; leaving the name out would
be indistinguishable from an implementation gap.

The vocabulary is listed here rather than imported from another repository: a
backend guards its own tree, and the list is the contract it is guarding.
"""

import pytest

from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect

PARTITION_ACTIONS = (
    "supports_add_partition",
    "supports_drop_partition",
    "supports_truncate_partition",
    "supports_attach_partition",
    "supports_detach_partition",
    "supports_split_partition",
    "supports_merge_partition",
    "supports_exchange_partition",
    "supports_reorganize_partition",
    "supports_coalesce_partition",
    "supports_move_partition",
    "supports_analyze_partition",
    "supports_check_partition",
    "supports_optimize_partition",
    "supports_rebuild_partition",
    "supports_repair_partition",
    "supports_remove_partitioning",
)


@pytest.fixture()
def dialect():
    return BigQueryDialect()


@pytest.mark.parametrize("name", PARTITION_ACTIONS)
def test_every_action_is_declared_and_false(dialect, name):
    switch = getattr(dialect, name, None)
    assert callable(switch), f"{name} is missing from the partition vocabulary"
    assert switch() is False, f"{name} must answer False on BigQuery"


def test_the_vocabulary_is_the_whole_action_family():
    """Guards against a short list passing by accident."""
    assert len(PARTITION_ACTIONS) == len(set(PARTITION_ACTIONS)) == 17
