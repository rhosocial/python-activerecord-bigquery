# src/rhosocial/activerecord/backend/impl/bigquery/mixins/__init__.py
"""BigQuery dialect-specific mixin implementations."""

from .types import BigQueryTypeSupportMixin
from .namespace import BigQueryNamespaceMixin
from .dql import BigQueryDQLMixin
from .schema import BigQuerySchemaMixin
from .ddl import BigQueryDDLColumnMixin
from .capabilities import BigQueryCapabilityMixin
from .column_type import BigQueryColumnTypeMixin
from .identity_column import BigQueryIdentityColumnMixin
from .identifier import BigQueryIdentifierMixin
from .materialized_view import BigQueryMaterializedViewMixin
from .transaction import BigQueryTransactionMixin
from .trim import BigQueryTrimMixin


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
    'BigQueryTypeSupportMixin',
    'BigQueryNamespaceMixin',
    'BigQueryDQLMixin',
    'BigQuerySchemaMixin',
    'BigQueryDDLColumnMixin',
    'BigQueryCapabilityMixin',
    'BigQueryColumnTypeMixin',
    'BigQueryIdentityColumnMixin',
    'BigQueryIdentifierMixin',
    'BigQueryMaterializedViewMixin',
    'BigQueryTransactionMixin',
    'BigQueryTrimMixin',
    'BigQueryStructMixin',
    'BigQueryArrayMixin',
    'BigQueryJSONMixin',
    'BigQueryGeographyMixin',
]
