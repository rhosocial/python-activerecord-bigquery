# src/rhosocial/activerecord/backend/impl/bigquery/protocols/schema.py
"""BigQuery schema (``dataset``) capability protocol."""

from typing import Any, Protocol, runtime_checkable, Tuple


@runtime_checkable
class BigQuerySchemaSupport(Protocol):
    """BigQuery's inner namespace, which BigQuery calls a dataset.

    A dataset holds the tables, views and materialized views, and it is
    written ``dataset.table`` or ``project.dataset.table``. In this backend the
    ``schema_name`` slot carries the dataset; the outer ``catalog_name`` slot
    carries the project. Both slots are *named* by core's
    :class:`~rhosocial.activerecord.backend.dialect.protocols.NamespaceSupport`,
    which is the one protocol for that question.

    This one is a different question -- does the engine have schemas at all, and
    can it ``CREATE SCHEMA`` / ``DROP SCHEMA`` -- so it is not an overlap with
    that. BigQuery answers it ``True`` and implements both statements. An engine
    may answer the naming question and the DDL question differently, which is
    why they are separate names rather than one switch read two ways.
    """

    def supports_schema(self) -> bool:
        """Whether BigQuery models named namespaces at all."""
        ...  # pragma: no cover

    def supports_create_schema(self) -> bool:
        """Whether ``CREATE SCHEMA`` (GoogleSQL: ``CREATE SCHEMA``) works."""
        ...  # pragma: no cover

    def supports_drop_schema(self) -> bool:
        """Whether ``DROP SCHEMA`` works."""
        ...  # pragma: no cover

    def supports_schema_if_not_exists(self) -> bool:
        """Whether ``CREATE SCHEMA IF NOT EXISTS`` works."""
        ...  # pragma: no cover

    def supports_schema_if_exists(self) -> bool:
        """Whether ``DROP SCHEMA IF EXISTS`` works."""
        ...  # pragma: no cover

    def supports_schema_cascade(self) -> bool:
        """Whether ``DROP SCHEMA CASCADE`` works. BigQuery has no CASCADE."""
        ...  # pragma: no cover

    def supports_schema_authorization(self) -> bool:
        """Whether ``CREATE SCHEMA AUTHORIZATION`` works."""
        ...  # pragma: no cover

    def format_create_schema_statement(self, expr: Any) -> Tuple[str, tuple]:
        """Format ``CREATE SCHEMA`` for the dataset *expr* names."""
        ...  # pragma: no cover

    def format_drop_schema_statement(self, expr: Any) -> Tuple[str, tuple]:
        """Format ``DROP SCHEMA`` for the dataset *expr* names."""
        ...  # pragma: no cover