# src/rhosocial/activerecord/backend/impl/bigquery/expression/materialized_view.py

"""BigQuery materialized view DDL expressions.

GoogleSQL syntax (BigQuery Standard SQL DDL reference):

    CREATE [ OR REPLACE ] MATERIALIZED VIEW [ IF NOT EXISTS ] mv_name
        [PARTITION BY partition_expression]
        [CLUSTER BY clustering_column_list]
        [OPTIONS(materialized_view_option_list)]
        AS query_expression

    ALTER MATERIALIZED VIEW [IF EXISTS] mv_name
        SET OPTIONS(materialized_view_set_options_list)

    DROP MATERIALIZED VIEW [IF EXISTS] mv_name

    CREATE MATERIALIZED VIEW replica_name
        [OPTIONS(materialized_view_replica_option_list)]
        AS REPLICA OF source_materialized_view_name

Naming
-------
Every ``mv_name`` above is a
:class:`~rhosocial.activerecord.backend.expression.objects.MaterializedView`,
so the dataset lives in the object's ``schema_name`` slot and the project in
its ``catalog_name`` slot. Nothing here takes a bare string for a name and a
separate ``schema_name`` beside it: one object, one set of slots, and the
object's own ``format_materialized_view_object`` is the only thing that turns
any of them into SQL. A ``replica_name``/``source_view_name`` pair is two
objects because a replica usually sits in a different dataset from the view it
mirrors.

Divergence from the SQL-standard statement
------------------------------------------
* No ``TABLESPACE``, no ``WITH (storage_parameter)``, no ``WITH [NO] DATA``
  and no column-alias list — a BigQuery materialized view takes its column
  names from the query. Those fields are rejected rather than dropped.
* ``OR REPLACE`` and ``IF NOT EXISTS`` are mutually exclusive.
* **There is no ``REFRESH MATERIALIZED VIEW`` statement.** BigQuery refreshes on
  a schedule configured through ``OPTIONS(enable_refresh=…,
  refresh_interval_minutes=…)``; use
  :class:`BigQueryAlterMaterializedViewSetOptionsExpression` to change it.
* ``DROP`` has no ``CASCADE``.
"""
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from rhosocial.activerecord.backend.expression.bases import BaseExpression
from rhosocial.activerecord.backend.expression.objects import MaterializedView
from rhosocial.activerecord.backend.expression.statements.ddl_view import (
    CreateMaterializedViewExpression,
    DropMaterializedViewExpression,
)

from ..materialized_view_options import validate_materialized_view_options

if TYPE_CHECKING:  # pragma: no cover
    from ..dialect import BigQueryDialect


__all__ = [
    "BigQueryAlterMaterializedViewSetOptionsExpression",
    "BigQueryCreateMaterializedViewExpression",
    "BigQueryCreateMaterializedViewReplicaExpression",
    "BigQueryDropMaterializedViewExpression",
]


class BigQueryCreateMaterializedViewExpression(CreateMaterializedViewExpression):
    """``CREATE [OR REPLACE] MATERIALIZED VIEW [IF NOT EXISTS] ... AS query``.

    Args:
        dialect: the BigQuery dialect instance.
        view: the materialized view being created. Its ``schema_name`` is the
            dataset and its ``catalog_name`` the project; both may be ``None``
            to let the project default and leave the view unqualified.
        query: defining query expression.
        or_replace: emit ``OR REPLACE`` (mutually exclusive with ``if_not_exists``).
        if_not_exists: emit ``IF NOT EXISTS``.
        partition_by: partition expression, rendered verbatim.
        cluster_by: clustering column list.
        options: ``OPTIONS(...)`` entries, validated against
            :class:`~..materialized_view_options.BigQueryMaterializedViewOption`.

    Raises:
        ValueError: on mutually exclusive flags or an undocumented option name.
            A malformed *view* raises from ``MaterializedView`` itself, which is
            what fixes the rule that a name is never empty.
    """

    def __init__(
        self,
        dialect: "BigQueryDialect",
        view: MaterializedView,
        query: Any,
        or_replace: bool = False,
        if_not_exists: bool = False,
        partition_by: Optional[str] = None,
        cluster_by: Optional[List[str]] = None,
        options: Optional[Dict[Any, Any]] = None,
    ):
        if or_replace and if_not_exists:
            raise ValueError(
                "BigQuery rejects OR REPLACE together with IF NOT EXISTS"
            )
        if partition_by is not None and not str(partition_by).strip():
            raise ValueError("partition_by must be a non-empty expression when provided")
        if cluster_by is not None:
            if isinstance(cluster_by, str) or not cluster_by:
                raise ValueError("cluster_by must be a non-empty sequence of columns")
        if options:
            validate_materialized_view_options(options)

        super().__init__(
            dialect,
            view,
            query,
            # BigQuery has no clause for these; the formatter rejects them, so the
            # values are never silently rendered.
            column_aliases=None,
            tablespace=None,
            with_data=True,
            storage_options=None,
        )
        self.or_replace = or_replace
        self.if_not_exists = if_not_exists
        self.partition_by = partition_by
        self.cluster_by = list(cluster_by) if cluster_by else None
        self.options = dict(options) if options else {}

    @property
    def format_method(self) -> str:
        """The dialect formatting method that renders this expression."""
        return "format_create_materialized_view_statement"


class BigQueryDropMaterializedViewExpression(DropMaterializedViewExpression):
    """``DROP MATERIALIZED VIEW [IF EXISTS] mv_name``.

    BigQuery has no ``CASCADE`` for materialized views.
    """

    def __init__(
        self,
        dialect: "BigQueryDialect",
        view: MaterializedView,
        if_exists: bool = False,
        cascade: bool = False,
    ):
        """
        Args:
            view: the materialized view to drop, carrying its own dataset.
        """
        if cascade:
            raise ValueError("BigQuery DROP MATERIALIZED VIEW has no CASCADE clause")
        super().__init__(dialect, view, if_exists=if_exists, cascade=False)

    @property
    def format_method(self) -> str:
        """The dialect formatting method that renders this expression."""
        return "format_drop_materialized_view_statement"


class BigQueryAlterMaterializedViewSetOptionsExpression(BaseExpression):
    """``ALTER MATERIALIZED VIEW [IF EXISTS] mv_name SET OPTIONS(...)``.

    This is BigQuery's only ``ALTER MATERIALIZED VIEW`` form — there is no way to
    change the defining query in place, so the view must be recreated.
    """

    def __init__(
        self,
        dialect: "BigQueryDialect",
        view: MaterializedView,
        options: Dict[Any, Any],
        if_exists: bool = False,
    ):
        """
        Args:
            view: the materialized view being reconfigured, carrying its dataset.
            options: the ``OPTIONS(...)`` entries to set.
            if_exists: emit ``IF EXISTS``.
        """
        super().__init__(dialect)
        if not isinstance(options, dict) or not options:
            raise ValueError("options must be a non-empty dict")
        validate_materialized_view_options(options)
        self.view = view
        self.options = dict(options)
        self.if_exists = if_exists

    @property
    def format_method(self) -> str:
        """The dialect formatting method that renders this expression."""
        return "format_alter_materialized_view_set_options_statement"


class BigQueryCreateMaterializedViewReplicaExpression(BaseExpression):
    """``CREATE MATERIALIZED VIEW replica_name [OPTIONS(...)] AS REPLICA OF src``."""

    #: Documented bounds for ``replication_interval_seconds``.
    MIN_REPLICATION_INTERVAL_SECONDS = 60
    MAX_REPLICATION_INTERVAL_SECONDS = 3600
    DEFAULT_REPLICATION_INTERVAL_SECONDS = 300

    def __init__(
        self,
        dialect: "BigQueryDialect",
        replica: MaterializedView,
        source_view: MaterializedView,
        replication_interval_seconds: Optional[int] = None,
    ):
        """
        Args:
            replica: The replica to create, carrying its own dataset.
            source_view: The view being replicated, carrying its own dataset.
                A replica usually lives in a different dataset from its
                source, so the two namespaces are chosen independently.

        Raises:
            ValueError: ``replication_interval_seconds`` is outside the
                documented range.
        """
        super().__init__(dialect)
        if replication_interval_seconds is not None and not (
            self.MIN_REPLICATION_INTERVAL_SECONDS
            <= replication_interval_seconds
            <= self.MAX_REPLICATION_INTERVAL_SECONDS
        ):
            raise ValueError(
                "replication_interval_seconds must be between "
                f"{self.MIN_REPLICATION_INTERVAL_SECONDS} and "
                f"{self.MAX_REPLICATION_INTERVAL_SECONDS} inclusive"
            )
        self.replica = replica
        self.source_view = source_view
        self.replication_interval_seconds = replication_interval_seconds

    @property
    def format_method(self) -> str:
        """The dialect formatting method that renders this expression."""
        return "format_create_materialized_view_replica_statement"