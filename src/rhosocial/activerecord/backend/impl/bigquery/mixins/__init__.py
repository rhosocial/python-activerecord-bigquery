# src/rhosocial/activerecord/backend/impl/bigquery/mixins/__init__.py
"""BigQuery dialect-specific mixin implementations."""

from .capabilities import BigQueryCapabilityMixin
from .column_type import BigQueryColumnTypeMixin
from .change_suggestions import (
    BigQueryColumnReorderSuggestionMixin,
    BigQueryPartitionSchemeChangeSuggestionMixin,
    BigQueryTableConstraintChangeSuggestionMixin,
    BigQueryTableIndexChangeSuggestionMixin,
)
from .constraint import BigQueryConstraintMixin
from .data_type_suggestions import BigQueryDataTypeSuggestionsMixin
from .ddl import BigQueryDDLColumnMixin
from .dql import BigQueryDQLMixin
from .general_suggestions import BigQueryCreateTableLayoutSuggestionMixin
from .generated_value_suggestion import BigQueryGeneratedValueSuggestionMixin
from .partition_suggestions import (
    BigQueryPartitionAddSuggestionMixin,
    BigQueryPartitionBuildSuggestionMixin,
    BigQueryPartitionDropSuggestionMixin,
    BigQueryPartitionMergeSuggestionMixin,
    BigQueryPartitionRetentionSuggestionMixin,
    BigQueryPartitionSplitSuggestionMixin,
    BigQueryPartitionTableAlterSuggestionMixin,
    BigQueryPartitionTableDropSuggestionMixin,
)
from .identifier import BigQueryIdentifierMixin
from .identity_column import BigQueryIdentityColumnMixin
from .index import BigQueryIndexMixin
from .introspection import BigQueryIntrospectionMixin
from .literal import BigQueryLiteralValueMixin
from .materialized_view import BigQueryMaterializedViewMixin
from .namespace import BigQueryNamespaceMixin
from .partition import BigQueryPartitionMixin
from .schema import BigQuerySchemaMixin
from .transaction import BigQueryTransactionMixin
from .trim import BigQueryTrimMixin
from .types import BigQueryTypeSupportMixin


class BigQueryStructMixin:
    def supports_struct(self) -> bool:
        return True


class BigQueryArrayMixin:
    def supports_array(self) -> bool:
        return True


class BigQueryJSONMixin:
    def supports_json(self) -> bool:
        return True


class BigQueryGeographyMixin:
    def supports_geography(self) -> bool:
        return True


__all__ = [
    "BigQueryTypeSupportMixin",
    "BigQueryNamespaceMixin",
    "BigQueryPartitionMixin",
    "BigQueryDQLMixin",
    "BigQuerySchemaMixin",
    "BigQueryDDLColumnMixin",
    "BigQueryConstraintMixin",
    "BigQueryCapabilityMixin",
    "BigQueryColumnTypeMixin",
    "BigQueryDataTypeSuggestionsMixin",
    "BigQueryCreateTableLayoutSuggestionMixin",
    "BigQueryColumnReorderSuggestionMixin",
    "BigQueryTableConstraintChangeSuggestionMixin",
    "BigQueryTableIndexChangeSuggestionMixin",
    "BigQueryPartitionSchemeChangeSuggestionMixin",
    "BigQueryGeneratedValueSuggestionMixin",
    "BigQueryPartitionBuildSuggestionMixin",
    "BigQueryPartitionAddSuggestionMixin",
    "BigQueryPartitionDropSuggestionMixin",
    "BigQueryPartitionRetentionSuggestionMixin",
    "BigQueryPartitionTableDropSuggestionMixin",
    "BigQueryPartitionTableAlterSuggestionMixin",
    "BigQueryPartitionSplitSuggestionMixin",
    "BigQueryPartitionMergeSuggestionMixin",
    "BigQueryIdentityColumnMixin",
    "BigQueryIdentifierMixin",
    "BigQueryIndexMixin",
    "BigQueryMaterializedViewMixin",
    "BigQueryTransactionMixin",
    "BigQueryTrimMixin",
    "BigQueryLiteralValueMixin",
    "BigQueryIntrospectionMixin",
    "BigQueryStructMixin",
    "BigQueryArrayMixin",
    "BigQueryJSONMixin",
    "BigQueryGeographyMixin",
]
