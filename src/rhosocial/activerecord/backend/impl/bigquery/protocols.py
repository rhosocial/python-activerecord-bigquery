"""BigQuery-specific protocol definitions."""
from typing import Any, Protocol, runtime_checkable, Tuple


@runtime_checkable
class BigQueryStructSupport(Protocol):
    def supports_struct(self) -> bool: ...


@runtime_checkable
class BigQueryArraySupport(Protocol):
    def supports_array(self) -> bool: ...


@runtime_checkable
class BigQueryJSONSupport(Protocol):
    def supports_json(self) -> bool: ...


@runtime_checkable
class BigQueryGeographySupport(Protocol):
    def supports_geography(self) -> bool: ...


@runtime_checkable
class BigQueryMaterializedViewSupport(Protocol):
    """BigQuery MATERIALIZED VIEW support.

    GoogleSQL syntax::

        CREATE [ OR REPLACE ] MATERIALIZED VIEW [ IF NOT EXISTS ] mv_name
            [PARTITION BY partition_expression]
            [CLUSTER BY clustering_column_list]
            [OPTIONS(materialized_view_option_list)]
            AS query_expression

        ALTER MATERIALIZED VIEW [IF EXISTS] mv_name SET OPTIONS(...)
        DROP MATERIALIZED VIEW [IF EXISTS] mv_name
        CREATE MATERIALIZED VIEW replica [OPTIONS(...)] AS REPLICA OF source

    There is no ``REFRESH MATERIALIZED VIEW`` statement: refresh is scheduled
    through ``OPTIONS(enable_refresh=…, refresh_interval_minutes=…)``.
    """

    def supports_materialized_view(self) -> bool:
        """BigQuery has native materialized views."""
        ...

    def supports_refresh_materialized_view(self) -> bool:
        """Always ``False``: refresh is option-driven, not a statement."""
        ...

    def supports_materialized_view_options(self) -> bool:
        """Whether ``OPTIONS(...)`` configuration is supported."""
        ...

    def supports_materialized_view_replica(self) -> bool:
        """Whether ``CREATE MATERIALIZED VIEW ... AS REPLICA OF`` is supported."""
        ...

    def format_create_materialized_view_statement(self, expr: Any) -> Tuple[str, tuple]:
        """Format ``CREATE [OR REPLACE] MATERIALIZED VIEW [IF NOT EXISTS]``."""
        ...

    def format_drop_materialized_view_statement(self, expr: Any) -> Tuple[str, tuple]:
        """Format ``DROP MATERIALIZED VIEW [IF EXISTS]``."""
        ...

    def format_alter_materialized_view_set_options_statement(self, expr: Any) -> Tuple[str, tuple]:
        """Format ``ALTER MATERIALIZED VIEW [IF EXISTS] ... SET OPTIONS(...)``."""
        ...

    def format_create_materialized_view_replica_statement(self, expr: Any) -> Tuple[str, tuple]:
        """Format ``CREATE MATERIALIZED VIEW replica ... AS REPLICA OF source``."""
        ...
