# src/rhosocial/activerecord/backend/impl/bigquery/expression/__init__.py
"""BigQuery-specific DDL expressions."""

from .materialized_view import (
    BigQueryAlterMaterializedViewSetOptionsExpression,
    BigQueryCreateMaterializedViewExpression,
    BigQueryCreateMaterializedViewReplicaExpression,
    BigQueryDropMaterializedViewExpression,
)

__all__ = [
    "BigQueryAlterMaterializedViewSetOptionsExpression",
    "BigQueryCreateMaterializedViewExpression",
    "BigQueryCreateMaterializedViewReplicaExpression",
    "BigQueryDropMaterializedViewExpression",
]
