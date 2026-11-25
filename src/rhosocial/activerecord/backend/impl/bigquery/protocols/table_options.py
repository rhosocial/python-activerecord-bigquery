# src/rhosocial/activerecord/backend/impl/bigquery/protocols/table_options.py
"""BigQuery table-option DDL protocol."""

from typing import Any, Protocol, runtime_checkable, Tuple


@runtime_checkable
class BigQueryTableOptionsSupport(Protocol):
    """``ALTER TABLE ... SET OPTIONS`` / ``UNSET OPTIONS``.

    GoogleSQL syntax::

        ALTER TABLE [ IF EXISTS ] table_name SET OPTIONS ( table_set_options_list )
        ALTER TABLE [ IF EXISTS ] table_name UNSET OPTIONS ( option_name, ... )

    ``table_name`` is a core ``Table`` object -- dataset in ``schema_name`` and
    project in ``catalog_name`` -- so both statements render their target
    through the shared qualified-name renderer.
    """

    def supports_alter_table_options(self) -> bool:
        """Whether ``ALTER TABLE ... SET OPTIONS`` is available."""
        ...

    def supports_alter_table_unset_options(self) -> bool:
        """Whether ``ALTER TABLE ... UNSET OPTIONS`` is available."""
        ...

    def format_bigquery_alter_table_set_options_statement(
        self, expr: Any
    ) -> Tuple[str, tuple]:
        """Format ``ALTER TABLE [IF EXISTS] ... SET OPTIONS(...)``."""
        ...

    def format_bigquery_alter_table_unset_options_statement(
        self, expr: Any
    ) -> Tuple[str, tuple]:
        """Format ``ALTER TABLE [IF EXISTS] ... UNSET OPTIONS(...)``."""
        ...
