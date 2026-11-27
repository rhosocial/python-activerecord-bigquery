# src/rhosocial/activerecord/backend/impl/bigquery/mixins/partition_suggestions.py
"""BigQuery's eight partition-lifecycle suggestions.

BigQuery's partitioning is declared once at CREATE time through the table-level
``PARTITION BY`` / ``CLUSTER BY`` clause; there is no partition-level DDL (no
ADD/DROP/MERGE/SPLIT/ATTACH partition statement) and no in-place scheme change.
So only the ``build`` and ``table_drop`` intents have a real mechanism:

* ``build`` → the proprietary ``BigQueryTablePartitionByClause`` this backend
  owns, assembled from the plan's partition expression and clustering columns.
* ``table_drop`` → ``DROP TABLE`` (dropping the table is the only way to remove
  the partitioning declaration).
* every other intent → the explicit ``False`` state, which a caller reports as
  "this backend has no mechanism" rather than treating it as "no action".
"""

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from rhosocial.activerecord.backend.expression.objects import Table
from rhosocial.activerecord.backend.suggestion.definitions import (
    PartitionAddSuggestion,
    PartitionBuildSuggestion,
    PartitionDropSuggestion,
    PartitionMergeSuggestion,
    PartitionRetentionSuggestion,
    PartitionSplitSuggestion,
    PartitionTableAlterSuggestion,
    PartitionTableDropSuggestion,
)

if TYPE_CHECKING:  # pragma: no cover
    from rhosocial.activerecord.backend.expression.statements import PartitionByClause


__all__ = [
    "BigQueryPartitionBuildSuggestionMixin",
    "BigQueryPartitionAddSuggestionMixin",
    "BigQueryPartitionDropSuggestionMixin",
    "BigQueryPartitionRetentionSuggestionMixin",
    "BigQueryPartitionTableDropSuggestionMixin",
    "BigQueryPartitionTableAlterSuggestionMixin",
    "BigQueryPartitionSplitSuggestionMixin",
    "BigQueryPartitionMergeSuggestionMixin",
]


def _get(plan: Any, name: str, default: Any = None) -> Any:
    """Read one field from a mapping-shaped or attribute-shaped plan."""
    if plan is None:
        return default
    if isinstance(plan, Mapping):
        return plan.get(name, default)
    # An attribute-shaped plan is a plain object with declared fields; read
    # its storage directly rather than probing it by a computed name.
    return vars(plan).get(name, default)


class BigQueryPartitionBuildSuggestionMixin:
    """Suggest the table-level PARTITION BY / CLUSTER BY clause at CREATE time."""

    def suggest_partition_build(
        self, strategy: "PartitionByClause", plan: object
    ) -> PartitionBuildSuggestion:
        from ..expression.partition import BigQueryTablePartitionByClause

        partition_expression = _get(plan, "partition_expression")
        cluster_by = _get(plan, "cluster_by")
        if partition_expression is None and not cluster_by:
            return PartitionBuildSuggestion(False)
        clause = BigQueryTablePartitionByClause(
            self, partition_expression, cluster_by
        )
        return PartitionBuildSuggestion((clause,))


class BigQueryPartitionTableDropSuggestionMixin:
    """Suggest dropping the whole table (the only way to remove the declaration)."""

    def suggest_partition_table_drop(
        self, strategy: "PartitionByClause", plan: object
    ) -> PartitionTableDropSuggestion:
        from rhosocial.activerecord.backend.expression.statements import (
            DropTableStatement,
        )

        target = _get(plan, "table")
        if isinstance(target, Table):
            table = target
        elif isinstance(target, str) and target.strip():
            table = Table(self, target)
        else:
            return PartitionTableDropSuggestion(False)
        return PartitionTableDropSuggestion((DropTableStatement(self, table),))


class BigQueryPartitionAddSuggestionMixin:
    """BigQuery has no ADD PARTITION statement."""

    def suggest_partition_add(
        self, strategy: "PartitionByClause", plan: object
    ) -> PartitionAddSuggestion:
        return PartitionAddSuggestion(False)


class BigQueryPartitionDropSuggestionMixin:
    """BigQuery has no DROP PARTITION statement."""

    def suggest_partition_drop(
        self, strategy: "PartitionByClause", plan: object
    ) -> PartitionDropSuggestion:
        return PartitionDropSuggestion(False)


class BigQueryPartitionRetentionSuggestionMixin:
    """BigQuery has no partition-level retention DDL."""

    def suggest_partition_retention(
        self, strategy: "PartitionByClause", plan: object
    ) -> PartitionRetentionSuggestion:
        return PartitionRetentionSuggestion(False)


class BigQueryPartitionTableAlterSuggestionMixin:
    """Changing the partitioning scheme requires a table rebuild."""

    def suggest_partition_table_alter(
        self, strategy: "PartitionByClause", plan: object
    ) -> PartitionTableAlterSuggestion:
        return PartitionTableAlterSuggestion(False)


class BigQueryPartitionSplitSuggestionMixin:
    """BigQuery has no SPLIT PARTITION statement."""

    def suggest_partition_split(
        self, strategy: "PartitionByClause", plan: object
    ) -> PartitionSplitSuggestion:
        return PartitionSplitSuggestion(False)


class BigQueryPartitionMergeSuggestionMixin:
    """BigQuery has no MERGE PARTITIONS statement."""

    def suggest_partition_merge(
        self, strategy: "PartitionByClause", plan: object
    ) -> PartitionMergeSuggestion:
        return PartitionMergeSuggestion(False)
