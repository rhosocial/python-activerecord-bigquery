# src/rhosocial/activerecord/backend/impl/bigquery/mixins/schema.py
"""BigQuery schema (dataset) DDL mixin."""
from __future__ import annotations

from typing import Tuple, TYPE_CHECKING

from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError

if TYPE_CHECKING:
    from rhosocial.activerecord.backend.expression.statements.ddl_schema import (
        CreateSchemaExpression,
        DropSchemaExpression,
    )

from rhosocial.activerecord.backend.expression.objects import Schema


class BigQuerySchemaMixin:
    """BigQuery schema (dataset) DDL support.

    BigQuery qualifies tables with dataset namespaces, and supports
    basic CREATE SCHEMA / DROP SCHEMA statements.
    """

    def supports_schema(self) -> bool:
        return True

    def supports_create_schema(self) -> bool:
        """BigQuery supports CREATE SCHEMA."""
        return True

    def supports_drop_schema(self) -> bool:
        """BigQuery supports DROP SCHEMA."""
        return True

    def supports_schema_if_not_exists(self) -> bool:
        """BigQuery supports CREATE SCHEMA IF NOT EXISTS."""
        return True

    def supports_schema_if_exists(self) -> bool:
        """BigQuery supports DROP SCHEMA IF EXISTS."""
        return True

    def supports_schema_cascade(self) -> bool:
        """BigQuery does not support DROP SCHEMA CASCADE."""
        return False

    def format_create_schema_statement(self, expr: CreateSchemaExpression) -> Tuple[str, tuple]:
        """Format ``CREATE SCHEMA`` (GoogleSQL: ``CREATE DATASET``).

        Raises:
            TypeError: ``expr.schema`` is not a Schema. A dataset named as a
                different kind of object would render as valid SQL.
            UnsupportedFeatureError: for clauses BigQuery does not have.
        """
        if not isinstance(expr.schema, Schema):
            raise TypeError(
                f"CreateSchemaExpression.schema must be a Schema, "
                f"got {type(expr.schema).__name__}"
            )
        if expr.if_not_exists and not self.supports_schema_if_not_exists():
            raise UnsupportedFeatureError(
                self.name, "CREATE SCHEMA IF NOT EXISTS",
                f"{self.name} does not support CREATE SCHEMA IF NOT EXISTS."
            )
        if expr.authorization:
            raise UnsupportedFeatureError(
                self.name, "CREATE SCHEMA AUTHORIZATION",
                f"{self.name} does not support CREATE SCHEMA AUTHORIZATION."
            )
        if_not_exists_part = "IF NOT EXISTS " if expr.if_not_exists else ""
        return f"CREATE SCHEMA {if_not_exists_part}{expr.schema.to_sql()[0]}", ()

    def format_drop_schema_statement(self, expr: DropSchemaExpression) -> Tuple[str, tuple]:
        """Format ``DROP SCHEMA`` (GoogleSQL: ``DROP DATASET``).

        Raises:
            TypeError: ``expr.schema`` is not a Schema.
            UnsupportedFeatureError: for clauses BigQuery does not have.
        """
        if not isinstance(expr.schema, Schema):
            raise TypeError(
                f"DropSchemaExpression.schema must be a Schema, "
                f"got {type(expr.schema).__name__}"
            )
        if expr.if_exists and not self.supports_schema_if_exists():
            raise UnsupportedFeatureError(
                self.name, "DROP SCHEMA IF EXISTS",
                f"{self.name} does not support DROP SCHEMA IF EXISTS."
            )
        if expr.cascade and not self.supports_schema_cascade():
            raise UnsupportedFeatureError(
                self.name, "DROP SCHEMA CASCADE",
                f"{self.name} does not support DROP SCHEMA CASCADE."
            )
        if_exists_part = "IF EXISTS " if expr.if_exists else ""
        cascade_part = " CASCADE" if expr.cascade else ""
        return f"DROP SCHEMA {if_exists_part}{expr.schema.to_sql()[0]}{cascade_part}", ()


__all__ = ['BigQuerySchemaMixin']
