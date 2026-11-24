# tests/rhosocial/activerecord_bigquery_test/feature/backend/ddl/test_bigquery_partition_suggestions.py
"""BigQuery's eight partition-lifecycle suggestions.

BigQuery declares partitioning once at CREATE time and has no partition-level
DDL, so only ``build`` (the table-level PARTITION BY/CLUSTER BY clause) and
``table_drop`` (DROP TABLE) have a real mechanism. The other six report the
explicit ``False`` state instead of silence.
"""

import pytest

from rhosocial.activerecord.backend.expression.statements import DropTableStatement
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect
from rhosocial.activerecord.backend.impl.bigquery.expression import (
    BigQueryTablePartitionByClause,
)
from rhosocial.activerecord.backend.suggestion.protocols import (
    PartitionAddSuggestionSupport,
    PartitionBuildSuggestionSupport,
    PartitionDropSuggestionSupport,
    PartitionMergeSuggestionSupport,
    PartitionRetentionSuggestionSupport,
    PartitionSplitSuggestionSupport,
    PartitionTableAlterSuggestionSupport,
    PartitionTableDropSuggestionSupport,
)


@pytest.fixture
def dialect():
    return BigQueryDialect()


UNSUPPORTED = [
    ("add", "suggest_partition_add", PartitionAddSuggestionSupport),
    ("drop", "suggest_partition_drop", PartitionDropSuggestionSupport),
    ("retention", "suggest_partition_retention", PartitionRetentionSuggestionSupport),
    ("table_alter", "suggest_partition_table_alter", PartitionTableAlterSuggestionSupport),
    ("split", "suggest_partition_split", PartitionSplitSuggestionSupport),
    ("merge", "suggest_partition_merge", PartitionMergeSuggestionSupport),
]


def test_every_protocol_is_satisfied(dialect):
    for protocol in (
        PartitionBuildSuggestionSupport,
        PartitionAddSuggestionSupport,
        PartitionDropSuggestionSupport,
        PartitionRetentionSuggestionSupport,
        PartitionTableDropSuggestionSupport,
        PartitionTableAlterSuggestionSupport,
        PartitionSplitSuggestionSupport,
        PartitionMergeSuggestionSupport,
    ):
        assert isinstance(dialect, protocol)


def test_build_suggests_the_proprietary_partition_clause(dialect):
    suggestion = dialect.suggest_partition_build(
        None, {"partition_expression": "DATE(ts)", "cluster_by": ["a", "b"]}
    )
    assert len(suggestion.operations) == 1
    assert isinstance(suggestion.operations[0], BigQueryTablePartitionByClause)
    assert suggestion.operations[0].to_sql()[0] == " PARTITION BY DATE(ts) CLUSTER BY a, b"


def test_build_without_plan_data_is_declined(dialect):
    assert dialect.suggest_partition_build(None, {}).operations is False


def test_table_drop_suggests_drop_table(dialect):
    suggestion = dialect.suggest_partition_table_drop(None, {"table": "events"})
    assert len(suggestion.operations) == 1
    assert isinstance(suggestion.operations[0], DropTableStatement)
    assert suggestion.operations[0].to_sql()[0] == "DROP TABLE `events`"


def test_table_drop_without_a_table_is_declined(dialect):
    assert dialect.suggest_partition_table_drop(None, {}).operations is False


@pytest.mark.parametrize("intent,method,protocol", UNSUPPORTED, ids=[u[0] for u in UNSUPPORTED])
def test_unsupported_intents_are_explicit(dialect, intent, method, protocol):
    assert isinstance(dialect, protocol)
    assert getattr(dialect, method)(None, None).operations is False


@pytest.mark.parametrize("intent,method,protocol", UNSUPPORTED, ids=[u[0] for u in UNSUPPORTED])
def test_no_intent_is_silently_no_action(dialect, intent, method, protocol):
    assert getattr(dialect, method)(None, None).operations is not None
