# src/rhosocial/activerecord/backend/impl/bigquery/mixins/__init__.py
"""BigQuery dialect-specific mixin implementations."""

from .capabilities import BigQueryCapabilityMixin
from .column_type import BigQueryColumnTypeMixin
from .constraint import BigQueryConstraintMixin
from .ddl import BigQueryDDLColumnMixin
from .dql import BigQueryDQLMixin
from .identifier import BigQueryIdentifierMixin
from .identity_column import BigQueryIdentityColumnMixin
from .introspection import BigQueryIntrospectionMixin
from .literal import BigQueryLiteralValueMixin
from .materialized_view import BigQueryMaterializedViewMixin
from .namespace import BigQueryNamespaceMixin
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
    "BigQueryDQLMixin",
    "BigQuerySchemaMixin",
    "BigQueryDDLColumnMixin",
    "BigQueryConstraintMixin",
    "BigQueryCapabilityMixin",
    "BigQueryColumnTypeMixin",
    "BigQueryIdentityColumnMixin",
    "BigQueryIdentifierMixin",
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
