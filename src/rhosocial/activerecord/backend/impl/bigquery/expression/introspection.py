# src/rhosocial/activerecord/backend/impl/bigquery/expression/introspection.py
"""BigQuery introspection statements, as expression nodes.

BigQuery answers metadata questions from its ``INFORMATION_SCHEMA`` views
rather than from a DB-API catalog, so the questions are ordinary ``SELECT``
statements over views the project owns. Each class below is one question: it
collects the parameters (which dataset, which project, which table) and
declares the dialect entry that renders it. The dialect mixin
(:class:`~...mixins.introspection.BigQueryIntrospectionMixin`) owns the
spelling -- the backtick quoting, the ``project.dataset`` qualifier, the
bind markers -- and assembles the statement from core expression nodes
(:class:`~rhosocial.activerecord.backend.expression.core.Column`,
:class:`~rhosocial.activerecord.backend.expression.predicates.InPredicate`,
:class:`~rhosocial.activerecord.backend.expression.predicates.LogicalPredicate`,
:class:`~rhosocial.activerecord.backend.expression.query_parts.OrderByClause`
...). Nothing in this module writes SQL text.

**Dataset and schema are the same level here.** BigQuery names relations
``project.dataset.table`` and has no schema under a dataset, so:

* ``schema`` carries the **dataset** (or a ``project.dataset`` pair, when the
  project is not the connection's default);
* ``catalog`` carries the **project** to qualify the dataset with, or
  ``None`` for "the connection's default project", which the docs spell as
  ``dataset.INFORMATION_SCHEMA.view``.

The documented spellings, all read 2026-10-24 (UTC):

* ``mydataset.INFORMATION_SCHEMA.TABLES`` -- dataset qualifier only
* ``myproject.mydataset.INFORMATION_SCHEMA.TABLES`` -- project and dataset
* ``myproject.\\`region-us\\`.INFORMATION_SCHEMA.TABLES`` -- region qualifier,
  which only ``SCHEMATA`` accepts
* ``\\`project_id\\`.dataset.INFORMATION_SCHEMA.view`` -- the escape form for a
  project ID that needs quoting, for example
  ``\\`bigquery-public-data\\`.census_bureau_usa.INFORMATION_SCHEMA.TABLES``

https://cloud.google.com/bigquery/docs/information-schema-intro
https://cloud.google.com/bigquery/docs/information-schema-tables

Which view answers which question:

======================  ==========================================
Question                View
======================  ==========================================
database info           ``@@project_id`` (documented system variable)
tables                  ``INFORMATION_SCHEMA.TABLES``
columns                 ``INFORMATION_SCHEMA.COLUMNS``
primary keys            ``INFORMATION_SCHEMA.TABLE_CONSTRAINTS``
                        joined to ``KEY_COLUMN_USAGE``
views                   ``INFORMATION_SCHEMA.VIEWS``
datasets                ``INFORMATION_SCHEMA.SCHEMATA``
table options           ``INFORMATION_SCHEMA.TABLE_OPTIONS``
partitions              ``INFORMATION_SCHEMA.PARTITIONS``
======================  ==========================================

No BigQuery instance was available while writing this module. The statement
shapes follow the pages cited beside each class below.
"""

from typing import TYPE_CHECKING, Optional

from rhosocial.activerecord.backend.expression.introspection import (
    IntrospectionExpression,
)

if TYPE_CHECKING:  # pragma: no cover
    from ..dialect import BigQueryDialect


__all__ = [
    "BigQueryDatabaseInfoQueryStatement",
    "BigQueryTableListQueryStatement",
    "BigQueryColumnInfoQueryStatement",
    "BigQueryIndexInfoQueryStatement",
    "BigQueryViewListQueryStatement",
    "BigQueryViewInfoQueryStatement",
    "BigQueryDatasetListQueryStatement",
    "BigQueryTableOptionsQueryStatement",
    "BigQueryPartitionListQueryStatement",
]


class BigQueryDatabaseInfoQueryStatement(IntrospectionExpression):
    """``SELECT @@project_id AS catalog_name``.

    The only database fact BigQuery answers over SQL is which project the
    query runs in: ``@@project_id`` is a documented read-only system
    variable, and there is no server version to read. The backend's own
    feature level is reported separately by the introspector, which parses
    the row.

    https://cloud.google.com/bigquery/docs/reference/system-variables
    """

    def __init__(self, dialect: "BigQueryDialect", schema: Optional[str] = None):
        """Initialize the statement.

        Args:
            dialect: The BigQuery dialect that renders this statement.
            schema: Unused -- the question is project-level. Present so the
                class matches the shape of the other introspection
                statements and a caller can pass one harmlessly.
        """
        super().__init__(dialect, schema)

    @property
    def format_method(self) -> str:
        """The dialect formatting method that renders this expression."""
        return "format_bigquery_database_info_query_statement"


class BigQueryTableListQueryStatement(IntrospectionExpression):
    """The ``INFORMATION_SCHEMA.TABLES`` question, parameterised.

    Args:
        dialect: The BigQuery dialect that renders this statement.
        schema: The dataset, or a ``project.dataset`` pair. Required: every
            ``TABLES`` query carries a dataset qualifier (the region
            qualifier is not accepted for this view).
        catalog: The project to qualify the dataset with, or ``None`` for
            the connection's default project.
        include_views: Whether views and materialized views are returned.
            Documented ``table_type`` spellings are ``BASE TABLE``,
            ``CLONE``, ``SNAPSHOT``, ``VIEW``, ``MATERIALIZED VIEW`` and
            ``EXTERNAL``.
        include_system: Ignored. BigQuery's ``TABLES`` view does not list
            system tables, so there is nothing for the flag to include; it
            is accepted so the core signature keeps working.
        table_type: One core ``TableType`` spelling (``BASE_TABLE``,
            ``VIEW``, ``MATERIALIZED_VIEW``, ``EXTERNAL`` ...), or one
            catalog spelling. The dialect expands the core spellings onto
            the catalog ones.

    https://cloud.google.com/bigquery/docs/information-schema-tables
    """

    def __init__(
        self,
        dialect: "BigQueryDialect",
        schema: str,
        catalog: Optional[str] = None,
        include_views: bool = True,
        include_system: bool = False,
        table_type: Optional[str] = None,
    ):
        """Initialize the table list statement."""
        super().__init__(dialect, schema)
        self.catalog = catalog
        self.include_views = include_views
        self.include_system = include_system
        self.table_type = table_type

    @property
    def format_method(self) -> str:
        """The dialect formatting method that renders this expression."""
        return "format_bigquery_table_list_query_statement"


class BigQueryColumnInfoQueryStatement(IntrospectionExpression):
    """The ``INFORMATION_SCHEMA.COLUMNS`` question for one table.

    Pseudo columns (``_PARTITIONTIME``, ``_PARTITIONDATE``) are answered by
    the same view with ``is_hidden = 'YES'`` and a ``NULL``
    ``ordinal_position``. They are dropped by the parser rather than by a
    ``WHERE`` filter, because they are not part of the declared schema and
    the parser is where a row becomes an object.

    Args:
        dialect: The BigQuery dialect that renders this statement.
        table_name: The table whose columns are wanted.
        schema: The dataset, or a ``project.dataset`` pair. Required.
        catalog: The project to qualify the dataset with, or ``None``.

    https://cloud.google.com/bigquery/docs/information-schema-columns
    """

    def __init__(
        self,
        dialect: "BigQueryDialect",
        table_name: str,
        schema: str,
        catalog: Optional[str] = None,
    ):
        """Initialize the column list statement."""
        super().__init__(dialect, schema)
        self.table_name = table_name
        self.catalog = catalog

    @property
    def format_method(self) -> str:
        """The dialect formatting method that renders this expression."""
        return "format_bigquery_column_info_query_statement"


class BigQueryIndexInfoQueryStatement(IntrospectionExpression):
    """The primary-key question, over ``TABLE_CONSTRAINTS``.

    BigQuery has no user-created indexes. ``TABLE_CONSTRAINTS`` documents
    ``constraint_type`` as either ``PRIMARY KEY`` or ``FOREIGN KEY``, so the
    primary-key rows are the ones that answer "what is the key of this
    table"; the join to ``KEY_COLUMN_USAGE`` supplies the constrained
    columns in order. Foreign keys exist but neither view names the
    referenced relation, so the foreign-key question refuses instead.

    Args:
        dialect: The BigQuery dialect that renders this statement.
        table_name: The table whose primary key is wanted.
        schema: The dataset, or a ``project.dataset`` pair. Required.
        catalog: The project to qualify the dataset with, or ``None``.

    https://cloud.google.com/bigquery/docs/information-schema-table-constraints
    https://cloud.google.com/bigquery/docs/information-schema-key-column-usage
    """

    def __init__(
        self,
        dialect: "BigQueryDialect",
        table_name: str,
        schema: str,
        catalog: Optional[str] = None,
    ):
        """Initialize the index (primary key) statement."""
        super().__init__(dialect, schema)
        self.table_name = table_name
        self.catalog = catalog

    @property
    def format_method(self) -> str:
        """The dialect formatting method that renders this expression."""
        return "format_bigquery_index_info_query_statement"


class BigQueryViewListQueryStatement(IntrospectionExpression):
    """The ``INFORMATION_SCHEMA.VIEWS`` question.

    Args:
        dialect: The BigQuery dialect that renders this statement.
        schema: The dataset, or a ``project.dataset`` pair. Required.
        catalog: The project to qualify the dataset with, or ``None``.
        include_system: Ignored -- every row of this view is a user view.

    ``check_option`` is documented as always ``NULL`` for BigQuery; it is
    selected so the parsed object can say so rather than assume it.

    https://cloud.google.com/bigquery/docs/information-schema-views
    """

    def __init__(
        self,
        dialect: "BigQueryDialect",
        schema: str,
        catalog: Optional[str] = None,
        include_system: bool = False,
    ):
        """Initialize the view list statement."""
        super().__init__(dialect, schema)
        self.catalog = catalog
        self.include_system = include_system

    @property
    def format_method(self) -> str:
        """The dialect formatting method that renders this expression."""
        return "format_bigquery_view_list_query_statement"


class BigQueryViewInfoQueryStatement(IntrospectionExpression):
    """One view's ``INFORMATION_SCHEMA.VIEWS`` question.

    Args:
        dialect: The BigQuery dialect that renders this statement.
        view_name: The view being asked about.
        schema: The dataset, or a ``project.dataset`` pair. Required.
        catalog: The project to qualify the dataset with, or ``None``.

    https://cloud.google.com/bigquery/docs/information-schema-views
    """

    def __init__(
        self,
        dialect: "BigQueryDialect",
        view_name: str,
        schema: str,
        catalog: Optional[str] = None,
    ):
        """Initialize the single view statement."""
        super().__init__(dialect, schema)
        self.view_name = view_name
        self.catalog = catalog

    @property
    def format_method(self) -> str:
        """The dialect formatting method that renders this expression."""
        return "format_bigquery_view_info_query_statement"


class BigQueryDatasetListQueryStatement(IntrospectionExpression):
    """The ``INFORMATION_SCHEMA.SCHEMATA`` question (datasets).

    This is the one view that answers at project level rather than dataset
    level, and the only one that accepts a region qualifier. The documented
    scope table:

    * ``[PROJECT_ID.]INFORMATION_SCHEMA.SCHEMATA`` -- the US region;
    * ``[PROJECT_ID.]`region-REGION`.INFORMATION_SCHEMA.SCHEMATA`` -- one
      region, spelled ``region-us``, ``region-europe-north1``, ...

    Args:
        dialect: The BigQuery dialect that renders this statement.
        catalog: The project whose datasets are listed, or ``None`` for
            "the query-executing project".
        location: A dataset location (``US``, ``eu``, ``us-central1`` ...).
            The dialect prefixes ``region-`` when the value is not already
            a region qualifier; ``None`` reads the US multi-region, which
            is the documented default.

    https://cloud.google.com/bigquery/docs/information-schema-datasets-schemata
    """

    def __init__(
        self,
        dialect: "BigQueryDialect",
        catalog: Optional[str] = None,
        location: Optional[str] = None,
    ):
        """Initialize the dataset list statement."""
        super().__init__(dialect, None)
        self.catalog = catalog
        self.location = location

    @property
    def format_method(self) -> str:
        """The dialect formatting method that renders this expression."""
        return "format_bigquery_dataset_list_query_statement"


class BigQueryTableOptionsQueryStatement(IntrospectionExpression):
    """The ``INFORMATION_SCHEMA.TABLE_OPTIONS`` question for one table.

    Options arrive as one row per option -- ``description``,
    ``expiration_timestamp``, ``labels``, ``partition_expiration_days``,
    ``require_partition_filter``, ``refresh_interval_minutes``, and the
    external-table ones -- so the same option name can appear more than
    once with a different ``option_type`` (``labels`` is an
    ``ARRAY<STRUCT<STRING, STRING>>``). They are kept as rows rather than
    folded into a dict for that reason.

    Args:
        dialect: The BigQuery dialect that renders this statement.
        table_name: The table whose options are wanted.
        schema: The dataset, or a ``project.dataset`` pair. Required.
        catalog: The project to qualify the dataset with, or ``None``.

    https://cloud.google.com/bigquery/docs/information-schema-table-options
    """

    def __init__(
        self,
        dialect: "BigQueryDialect",
        table_name: str,
        schema: str,
        catalog: Optional[str] = None,
    ):
        """Initialize the table options statement."""
        super().__init__(dialect, schema)
        self.table_name = table_name
        self.catalog = catalog

    @property
    def format_method(self) -> str:
        """The dialect formatting method that renders this expression."""
        return "format_bigquery_table_options_query_statement"


class BigQueryPartitionListQueryStatement(IntrospectionExpression):
    """The ``INFORMATION_SCHEMA.PARTITIONS`` question for one table.

    ``partition_id`` is ``NULL`` for an unpartitioned table and
    ``__NULL__`` for the partition holding rows whose partitioning key is
    ``NULL``. Unlike ``SCHEMATA`` this view takes a dataset qualifier only,
    never a region qualifier.

    Args:
        dialect: The BigQuery dialect that renders this statement.
        table_name: The table whose partitions are wanted.
        schema: The dataset, or a ``project.dataset`` pair. Required.
        catalog: The project to qualify the dataset with, or ``None``.

    https://cloud.google.com/bigquery/docs/information-schema-partitions
    """

    def __init__(
        self,
        dialect: "BigQueryDialect",
        table_name: str,
        schema: str,
        catalog: Optional[str] = None,
    ):
        """Initialize the partition list statement."""
        super().__init__(dialect, schema)
        self.table_name = table_name
        self.catalog = catalog

    @property
    def format_method(self) -> str:
        """The dialect formatting method that renders this expression."""
        return "format_bigquery_partition_list_query_statement"
