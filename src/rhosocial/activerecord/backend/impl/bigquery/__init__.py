"""BigQuery backend implementation for the Python ORM.

This module provides:
- BigQuery synchronous backend with connection management and query execution
- BigQuery asynchronous backend with native async support
- BigQuery-specific connection configuration
- Type mapping and value conversion
- Transaction management (sync and async)
- BigQuery dialect and expression handling
- BigQuery-specific type helpers (STRUCT, ARRAY, JSON)
- BigQuery-specific type adapters

Architecture:
- BigQueryBackend: Synchronous implementation using google-cloud-bigquery
- AsyncBigQueryBackend: Native asynchronous implementation
- Independent from ORM frameworks - uses only native drivers
"""

from .backend import BigQueryBackend
from .async_backend import AsyncBigQueryBackend
from .config import BigQueryConnectionConfig
from .dialect import BigQueryDialect
from .transaction import BigQueryTransactionManager
from .async_transaction import AsyncBigQueryTransactionManager
from .materialized_view_options import (  # noqa: F401
    BigQueryMaterializedViewOption,
    BigQueryMaterializedViewOptionValueType,
)
from .expression.materialized_view import (
    BigQueryAlterMaterializedViewSetOptionsExpression,
    BigQueryCreateMaterializedViewExpression,
    BigQueryCreateMaterializedViewReplicaExpression,
    BigQueryDropMaterializedViewExpression,
)
from .types import BigQueryStruct, BigQueryArray, BigQueryJSON
from .adapters import (
    BigQueryStructAdapter,
    BigQueryArrayAdapter,
    BigQueryJSONAdapter,
    BigQueryDecimalAdapter,
    BigQueryTimestampAdapter,
)
from .protocols import (
    BigQueryStructSupport,
    BigQueryArraySupport,
    BigQueryJSONSupport,
    BigQueryGeographySupport,
    BigQueryMaterializedViewSupport,
)
from .mixins import (
    BigQueryStructMixin,
    BigQueryArrayMixin,
    BigQueryJSONMixin,
    BigQueryGeographyMixin,
)

__all__ = [
    "BigQueryBackend",
    "AsyncBigQueryBackend",
    "BigQueryConnectionConfig",
    "BigQueryDialect",
    "BigQueryTransactionManager",
    "AsyncBigQueryTransactionManager",
    # Materialized views
    "BigQueryMaterializedViewOption",
    "BigQueryMaterializedViewOptionValueType",
    "BigQueryCreateMaterializedViewExpression",
    "BigQueryDropMaterializedViewExpression",
    "BigQueryAlterMaterializedViewSetOptionsExpression",
    "BigQueryCreateMaterializedViewReplicaExpression",
    "BigQueryStruct",
    "BigQueryArray",
    "BigQueryJSON",
    "BigQueryStructAdapter",
    "BigQueryArrayAdapter",
    "BigQueryJSONAdapter",
    "BigQueryDecimalAdapter",
    "BigQueryTimestampAdapter",
    "BigQueryStructSupport",
    "BigQueryArraySupport",
    "BigQueryJSONSupport",
    "BigQueryGeographySupport",
    "BigQueryMaterializedViewSupport",
    "BigQueryStructMixin",
    "BigQueryArrayMixin",
    "BigQueryJSONMixin",
    "BigQueryGeographyMixin",
]
