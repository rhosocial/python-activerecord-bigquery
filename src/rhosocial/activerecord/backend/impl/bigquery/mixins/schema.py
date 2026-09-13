# src/rhosocial/activerecord/backend/impl/bigquery/mixins/schema.py
"""BigQuery schema (dataset) DDL mixin."""
from typing import Any, Tuple


class BigQuerySchemaMixin:
    """BigQuery schema (dataset) DDL support.

    BigQuery qualifies tables with dataset namespaces, but the runtime DDL
    surface has no CREATE SCHEMA/DROP SCHEMA statement: datasets are
    created via the management API (bq mk / datasets.insert), not SQL.
    """

    def supports_schema(self) -> bool:
        return True

    def supports_schema_if_not_exists(self) -> bool:
        return False

    def supports_schema_if_exists(self) -> bool:
        return False

    def format_create_schema_statement(self, expr: Any) -> Tuple[str, tuple]:
        if expr.if_not_exists or expr.authorization:
            raise ValueError(
                "BigQuery CREATE SCHEMA supports neither IF NOT EXISTS nor "
                f"AUTHORIZATION (dataset {expr.schema_name!r}); datasets are "
                "created via the management API."
            )
        return f"CREATE SCHEMA {self.format_identifier(expr.schema_name)}", ()

    def format_drop_schema_statement(self, expr: Any) -> Tuple[str, tuple]:
        if expr.if_exists or expr.cascade:
            raise ValueError(
                "BigQuery DROP SCHEMA supports neither IF EXISTS nor CASCADE "
                f"(dataset {expr.schema_name!r}); datasets are deleted via "
                "the management API."
            )
        return f"DROP SCHEMA {self.format_identifier(expr.schema_name)}", ()


__all__ = ['BigQuerySchemaMixin']
