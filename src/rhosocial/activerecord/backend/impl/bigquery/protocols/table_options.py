# src/rhosocial/activerecord/backend/impl/bigquery/protocols/table_options.py
"""BigQuery table-option DDL protocol."""

from typing import Any, Protocol, runtime_checkable, Tuple


@runtime_checkable
class BigQueryTableOptionsSupport(Protocol):
    """``ALTER TABLE ... SET OPTIONS``.

    GoogleSQL syntax::

        ALTER TABLE [ IF EXISTS ] table_name SET OPTIONS ( table_set_options_list )

    ``table_name`` is a core ``Table`` object -- dataset in ``schema_name`` and
    project in ``catalog_name`` -- so the statement renders its target through
    the shared qualified-name renderer. There is no ``UNSET OPTIONS`` statement
    in the official reference; clearing is ``SET OPTIONS(option_name = NULL)``.
    """

    def supports_alter_table_options(self) -> bool:
        """Whether ``ALTER TABLE ... SET OPTIONS`` is available."""
        ...

    def format_bigquery_alter_table_set_options_statement(
        self, expr: Any
    ) -> Tuple[str, tuple]:
        """Format ``ALTER TABLE [IF EXISTS] ... SET OPTIONS(...)``."""
        ...
