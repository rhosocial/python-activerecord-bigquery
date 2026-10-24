# src/rhosocial/activerecord/backend/impl/bigquery/mixins/introspection.py
"""BigQueryIntrospectionMixin -- how the dialect spells metadata questions.

This mixin is the dialect half of introspection: it declares what BigQuery
can answer (``supports_*``) and renders the statement objects from
:mod:`...expression.introspection` into
``project.dataset.INFORMATION_SCHEMA.<view>`` queries. The backend half --
executing them and parsing the rows -- lives in
:mod:`...introspection.introspector`.

Nothing here writes SQL text. Every ``format_*`` assembles a core
:class:`~rhosocial.activerecord.backend.expression.statements.dql.QueryStatement`
from expression nodes -- a
:class:`~rhosocial.activerecord.backend.expression.sources.NamedRelationRef`
over a
:class:`~rhosocial.activerecord.backend.expression.objects.Table` for the
``FROM``, :class:`~rhosocial.activerecord.backend.expression.core.Column`
for the projection and the predicates, and renders it through core's own
``format_query_statement``. The backtick quoting, the qualifier order and
the bind marker are therefore this dialect's answer and nobody else's: a
project ID with a hyphen is quoted the same way a table name is, by
:meth:`~rhosocial.activerecord.backend.dialect.base.SQLDialectBase.format_identifier`.

Position in ``BigQueryDialect``'s base list is load-bearing: this class
subclasses core's ``IntrospectionMixin``, so C3 linearisation gives the
first name priority and it must sit *before* the core mixin it overrides.
"""

from typing import TYPE_CHECKING, Any, List, Optional, Tuple

from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError
from rhosocial.activerecord.backend.dialect.mixins import IntrospectionMixin
from rhosocial.activerecord.backend.expression.core import Column, Literal
from rhosocial.activerecord.backend.expression.objects import Table
from rhosocial.activerecord.backend.expression.predicates import (
    ComparisonPredicate,
    InPredicate,
    LogicalPredicate,
)
from rhosocial.activerecord.backend.expression.query_parts import (
    JoinClause,
    OrderByClause,
)
from rhosocial.activerecord.backend.expression.sources import NamedRelationRef
from rhosocial.activerecord.backend.expression.statements.dql import QueryStatement
from rhosocial.activerecord.backend.introspection.types import IntrospectionScope

from ..expression.introspection import (
    BigQueryColumnInfoQueryStatement,
    BigQueryDatabaseInfoQueryStatement,
    BigQueryIndexInfoQueryStatement,
    BigQueryTableListQueryStatement,
    BigQueryViewInfoQueryStatement,
    BigQueryViewListQueryStatement,
)

if TYPE_CHECKING:  # pragma: no cover
    from rhosocial.activerecord.backend.expression.introspection import (
        ColumnInfoQueryStatement,
        DatabaseInfoQueryStatement,
        ForeignKeyQueryStatement,
        IndexInfoQueryStatement,
        TableInfoQueryStatement,
        TableListQueryStatement,
        TriggerInfoQueryStatement,
        TriggerListQueryStatement,
        ViewInfoQueryStatement,
        ViewListQueryStatement,
    )

    from ..expression.introspection import (
        BigQueryColumnInfoQueryStatement,
        BigQueryDatabaseInfoQueryStatement,
        BigQueryDatasetListQueryStatement,
        BigQueryIndexInfoQueryStatement,
        BigQueryPartitionListQueryStatement,
        BigQueryTableListQueryStatement,
        BigQueryTableOptionsQueryStatement,
        BigQueryViewInfoQueryStatement,
        BigQueryViewListQueryStatement,
    )

#: The ``table_type`` spellings core's ``TableType`` expands onto. The catalog
#: documents six: ``BASE TABLE``, ``CLONE``, ``SNAPSHOT``, ``VIEW``,
#: ``MATERIALIZED VIEW`` and ``EXTERNAL`` -- no system tables and no temporary
#: tables, which is why those two keys are absent here rather than mapped.
#: https://cloud.google.com/bigquery/docs/information-schema-tables
_BASE_TABLE_TYPES = ("BASE TABLE", "CLONE", "SNAPSHOT")
_VIEW_TYPES = ("VIEW", "MATERIALIZED VIEW")


class BigQueryIntrospectionMixin(IntrospectionMixin):
    """BigQuery's answers to the core introspection questions.

    ``supports_*`` declares them, ``format_*`` renders them. Two questions
    have no answer at all and say so instead of guessing: foreign keys
    (the catalog reports *that* one exists without naming the referenced
    relation) and triggers (BigQuery has none).
    """

    def supports_dataset_introspection(self) -> bool:
        """BigQuery answers for its datasets from ``INFORMATION_SCHEMA.SCHEMATA``.

        The capability for the ``introspect datasets`` family. A dataset
        is BigQuery's namespace level above a table -- there is no
        schema under it, so this is the only namespace switch."""
        return True

    # ------------------------------------------------------------------ #
    # Capability declaration
    # ------------------------------------------------------------------ #

    def supports_introspection(self) -> bool:
        """BigQuery answers metadata questions from INFORMATION_SCHEMA."""
        return True

    def supports_database_info(self) -> bool:
        """``@@project_id`` is the documented system variable."""
        return True

    def supports_table_introspection(self) -> bool:
        """``INFORMATION_SCHEMA.TABLES`` is dataset-scoped."""
        return True

    def supports_column_introspection(self) -> bool:
        """``INFORMATION_SCHEMA.COLUMNS`` is dataset-scoped."""
        return True

    def supports_index_introspection(self) -> bool:
        """No physical indexes exist; PRIMARY KEY constraints stand in."""
        return True

    def supports_foreign_key_introspection(self) -> bool:
        """Declined: the catalog never names the referenced relation.

        ``TABLE_CONSTRAINTS`` reports that a foreign key exists and
        ``KEY_COLUMN_USAGE`` reports its columns, but neither view names
        the referenced table or its columns, and BigQuery has no
        ``REFERENTIAL_CONSTRAINTS`` view. Reporting a foreign key whose
        ``referenced_table`` is empty would be a worse answer than none.
        """
        return False

    def supports_view_introspection(self) -> bool:
        """``INFORMATION_SCHEMA.VIEWS`` is dataset-scoped."""
        return True

    def supports_trigger_introspection(self) -> bool:
        """BigQuery has no triggers, so there is no trigger catalog view."""
        return False

    def supports_partition_info(self) -> bool:
        """``INFORMATION_SCHEMA.PARTITIONS`` and ``TABLE_OPTIONS`` answer."""
        return True

    def get_supported_introspection_scopes(self) -> List[IntrospectionScope]:
        """The scopes this dialect can answer, less the two it declines."""
        return [
            IntrospectionScope.DATABASE,
            IntrospectionScope.SCHEMA,
            IntrospectionScope.TABLE,
            IntrospectionScope.COLUMN,
            IntrospectionScope.INDEX,
            IntrospectionScope.VIEW,
        ]

    # ------------------------------------------------------------------ #
    # Spelling helpers
    # ------------------------------------------------------------------ #

    def _information_schema_relation(
        self,
        view: str,
        catalog: Optional[str],
        schema: Optional[str],
    ) -> Table:
        """Name ``[project.]dataset.INFORMATION_SCHEMA.<view>`` as a table.

        The three slots map onto BigQuery's four-level path: the project in
        the object's ``catalog_name``, the dataset in its ``schema_name``,
        and ``INFORMATION_SCHEMA.<view>`` in the name slot rendered
        unquoted -- ``INFORMATION_SCHEMA`` is a keyword path element rather
        than an identifier a caller chose. A ``None`` project leaves the
        qualifier out, which the documents spell as the default project.

        Args:
            view: The view name, e.g. ``"TABLES"``.
            catalog: The project, or ``None`` for the default.
            schema: The dataset, or ``None`` for the region/project scope
                that ``SCHEMATA`` uses.

        Returns:
            The ``Table`` object. Render it with ``to_sql()``.
        """
        return Table(
            self,
            f"INFORMATION_SCHEMA.{view}",
            catalog_name=catalog,
            schema_name=schema,
            catalog_need_quote=True,
            schema_need_quote=True,
            name_need_quote=False,
        )

    def _information_schema_source(
        self,
        view: str,
        catalog: Optional[str],
        schema: Optional[str],
        alias: Optional[str] = None,
    ) -> NamedRelationRef:
        """The ``FROM`` source over :meth:`_information_schema_relation`."""
        return NamedRelationRef(
            self,
            self._information_schema_relation(view, catalog, schema),
            alias=alias,
        )

    def _region_qualifier(self, location: Optional[str]) -> Optional[str]:
        """The ``region-REGION`` qualifier a configured location spells.

        The documented spelling takes the region name with a ``region-``
        prefix (``region-us``, ``region-europe-north1``). A location that
        already carries the prefix is used as it stands, and no location at
        all means no qualifier, which reads the US multi-region.
        """
        if not location:
            return None
        raw = str(location).strip()
        if not raw:
            return None
        return raw if raw.startswith("region-") else f"region-{raw}"

    def _columns(self, *names: str) -> List[Column]:
        """One bare column reference per catalog column name."""
        return [Column(self, name) for name in names]

    def _order_by_first(self, column_name: str) -> OrderByClause:
        """``ORDER BY`` the one column every one of these orders by."""
        return OrderByClause(self, expressions=[Column(self, column_name)])

    def _no_catalog_spelling_predicate(self):
        """A predicate that matches nothing, for a filter with no values.

        Asked for a table type the catalog never lists (system tables,
        temporary tables), the honest answer is an empty result rather than
        an unfiltered one, and the way to say it in SQL is a comparison
        that cannot hold. The two constants are inlined literals, not bind
        parameters: they belong to the statement rather than to the caller.
        """
        return ComparisonPredicate(
            self,
            ComparisonPredicate.coerce_operator("="),
            Literal(self, 1, inline=True),
            Literal(self, 2, inline=True),
        )

    def _expand_table_type(self, table_type: Optional[str]) -> Tuple[str, ...]:
        """The catalog spellings one requested table type means.

        A core ``TableType`` spelling is expanded onto the catalog's:
        ``BASE_TABLE`` covers base tables, clones and snapshots, and
        ``VIEW`` covers views and materialized views. A catalog spelling
        is passed through unchanged, and a spelling this backend does not
        know resolves to nothing -- which the caller renders as the
        no-match predicate rather than guessing.
        """
        if not table_type:
            return ()
        raw = str(table_type).strip().upper().replace("_", " ")
        if raw in ("BASE TABLE", "BASE"):
            return _BASE_TABLE_TYPES
        if raw == "VIEW":
            return _VIEW_TYPES
        if raw in ("SYSTEM TABLE", "TEMPORARY"):
            return ()
        return (raw,)

    # ------------------------------------------------------------------ #
    # Query formatting
    # ------------------------------------------------------------------ #

    def format_bigquery_database_info_query_statement(
        self, expr: "BigQueryDatabaseInfoQueryStatement"
    ) -> Tuple[str, tuple]:
        """``SELECT @@project_id AS catalog_name``.

        The projection is a column reference written unquoted -- the system
        variable is a keyword, not an identifier -- aliased so the parser
        reads one column name whatever case the driver reports.
        """
        del expr  # The question carries no parameters.
        query = QueryStatement(
            self,
            select=[
                Column(
                    self,
                    "@@project_id",
                    alias="catalog_name",
                    name_need_quote=False,
                    alias_need_quote=False,
                )
            ],
        )
        return self.format_query_statement(query)

    def format_bigquery_table_list_query_statement(
        self, expr: "BigQueryTableListQueryStatement"
    ) -> Tuple[str, tuple]:
        """Render the ``TABLES`` question.

        One of three filters, in this order of authority: an explicit
        ``table_type`` (an ``IN`` over the spellings that type means), then
        ``include_views=False`` (``NOT IN`` the two view spellings), then
        nothing. The ``table_type`` values are bind parameters, like every
        other value in the tree.
        """
        condition = None
        if expr.table_type:
            values = self._expand_table_type(expr.table_type)
            condition = (
                InPredicate(
                    self,
                    Column(self, "table_type"),
                    Literal(self, list(values)),
                )
                if values
                else self._no_catalog_spelling_predicate()
            )
        elif not expr.include_views:
            condition = LogicalPredicate(
                self,
                "NOT",
                InPredicate(
                    self,
                    Column(self, "table_type"),
                    Literal(self, list(_VIEW_TYPES)),
                ),
            )
        query = QueryStatement(
            self,
            select=self._columns(
                "table_catalog",
                "table_schema",
                "table_name",
                "table_type",
                "is_insertable_into",
                "is_typed",
                "creation_time",
                "ddl",
                "default_collation_name",
            ),
            from_=self._information_schema_source("TABLES", expr.catalog, expr.schema),
            where=condition,
            order_by=self._order_by_first("table_name"),
        )
        return self.format_query_statement(query)

    def format_bigquery_column_info_query_statement(
        self, expr: "BigQueryColumnInfoQueryStatement"
    ) -> Tuple[str, tuple]:
        """Render the ``COLUMNS`` question for one table.

        The table name is a bind parameter. ``is_hidden`` is selected so
        the parser can drop pseudo columns, whose ``ordinal_position`` the
        documents say is ``NULL``.
        """
        query = QueryStatement(
            self,
            select=self._columns(
                "table_catalog",
                "table_schema",
                "table_name",
                "column_name",
                "ordinal_position",
                "is_nullable",
                "data_type",
                "is_generated",
                "generation_expression",
                "is_stored",
                "is_hidden",
                "is_system_defined",
                "is_partitioning_column",
                "clustering_ordinal_position",
                "collation_name",
                "column_default",
                "rounding_mode",
                "is_identity",
                "identity_generation",
                "identity_start",
                "identity_increment",
                "identity_maximum",
                "identity_minimum",
                "identity_cycle",
            ),
            from_=self._information_schema_source("COLUMNS", expr.catalog, expr.schema),
            where=ComparisonPredicate(
                self,
                ComparisonPredicate.coerce_operator("="),
                Column(self, "table_name"),
                Literal(self, expr.table_name),
            ),
            order_by=self._order_by_first("ordinal_position"),
        )
        return self.format_query_statement(query)

    def format_bigquery_index_info_query_statement(
        self, expr: "BigQueryIndexInfoQueryStatement"
    ) -> Tuple[str, tuple]:
        """Render the primary-key question as a join over two views.

        ``TABLE_CONSTRAINTS`` filtered to ``PRIMARY KEY`` is joined to
        ``KEY_COLUMN_USAGE`` on the constraint name and the table name --
        the two columns both views carry -- so the constrained columns come
        back in ``ordinal_position`` order. The constraint type is a bind
        parameter filtering a documented value, not an identifier.
        """
        left = self._information_schema_source(
            "TABLE_CONSTRAINTS", expr.catalog, expr.schema, alias="tc"
        )
        right = self._information_schema_source(
            "KEY_COLUMN_USAGE", expr.catalog, expr.schema, alias="kcu"
        )
        same_constraint = ComparisonPredicate(
            self,
            ComparisonPredicate.coerce_operator("="),
            Column(self, "constraint_name", table="tc"),
            Column(self, "constraint_name", table="kcu"),
        )
        same_table = ComparisonPredicate(
            self,
            ComparisonPredicate.coerce_operator("="),
            Column(self, "table_name", table="tc"),
            Column(self, "table_name", table="kcu"),
        )
        query = QueryStatement(
            self,
            select=[
                # Qualified so the two views' same-named columns stay apart.
                # No alias: the catalog column name is already the result
                # name the parser reads.
                Column(self, "constraint_name", table="tc"),
                Column(self, "constraint_type", table="tc"),
                Column(self, "column_name", table="kcu"),
                Column(self, "ordinal_position", table="kcu"),
            ],
            from_=JoinClause(
                self,
                left_table=left,
                right_table=right,
                join_type="JOIN",
                condition=LogicalPredicate(self, "AND", same_constraint, same_table),
            ),
            where=LogicalPredicate(
                self,
                "AND",
                ComparisonPredicate(
                    self,
                    ComparisonPredicate.coerce_operator("="),
                    Column(self, "table_name", table="tc"),
                    Literal(self, expr.table_name),
                ),
                ComparisonPredicate(
                    self,
                    ComparisonPredicate.coerce_operator("="),
                    Column(self, "constraint_type", table="tc"),
                    Literal(self, "PRIMARY KEY"),
                ),
            ),
            order_by=OrderByClause(
                self,
                expressions=[
                    (Column(self, "constraint_name", table="tc"), "ASC"),
                    (Column(self, "ordinal_position", table="kcu"), "ASC"),
                ],
            ),
        )
        return self.format_query_statement(query)

    def format_bigquery_foreign_key_query_statement(self, expr: Any) -> Tuple[str, tuple]:
        """Refuse: the catalog never names the referenced relation.

        Kept as a formatter that raises rather than removed, so a caller
        that reaches for it gets the reason instead of a silent empty
        result. The public ``list_foreign_keys()`` returns an empty list and
        never calls this.
        """
        del expr
        raise UnsupportedFeatureError(
            self.name,
            "foreign key introspection",
            "BigQuery's INFORMATION_SCHEMA reports that a foreign key "
            "exists (TABLE_CONSTRAINTS.constraint_type = 'FOREIGN KEY') and "
            "reports its columns (KEY_COLUMN_USAGE), but neither view names "
            "the referenced table or its columns, and there is no "
            "REFERENTIAL_CONSTRAINTS view. list_foreign_keys() therefore "
            "returns an empty list rather than inventing the other side.",
        )

    def format_bigquery_view_list_query_statement(
        self, expr: "BigQueryViewListQueryStatement"
    ) -> Tuple[str, tuple]:
        """Render the ``VIEWS`` question.

        ``include_system`` is ignored: every row of this view is a user
        view, so there is no system row for the flag to add or remove. It
        stays on the statement (the artifact keeps it) rather than being
        deleted from it.
        """
        _ = expr.include_system
        query = QueryStatement(
            self,
            select=self._columns(
                "table_catalog",
                "table_schema",
                "table_name",
                "view_definition",
                "check_option",
                "use_standard_sql",
            ),
            from_=self._information_schema_source("VIEWS", expr.catalog, expr.schema),
            order_by=self._order_by_first("table_name"),
        )
        return self.format_query_statement(query)

    def format_bigquery_view_info_query_statement(
        self, expr: "BigQueryViewInfoQueryStatement"
    ) -> Tuple[str, tuple]:
        """Render one view's ``VIEWS`` question."""
        query = QueryStatement(
            self,
            select=self._columns(
                "table_catalog",
                "table_schema",
                "table_name",
                "view_definition",
                "check_option",
                "use_standard_sql",
            ),
            from_=self._information_schema_source("VIEWS", expr.catalog, expr.schema),
            where=ComparisonPredicate(
                self,
                ComparisonPredicate.coerce_operator("="),
                Column(self, "table_name"),
                Literal(self, expr.view_name),
            ),
        )
        return self.format_query_statement(query)

    def format_bigquery_dataset_list_query_statement(
        self, expr: "BigQueryDatasetListQueryStatement"
    ) -> Tuple[str, tuple]:
        """Render the ``SCHEMATA`` question.

        The only view answered at project level: the project goes in the
        catalog slot and the region qualifier -- when one is configured --
        in the schema slot, which is why this is the one statement whose
        ``schema`` is a region rather than a dataset.

        https://cloud.google.com/bigquery/docs/information-schema-datasets-schemata
        """
        query = QueryStatement(
            self,
            select=self._columns(
                "catalog_name",
                "schema_name",
                "schema_owner",
                "creation_time",
                "last_modified_time",
                "location",
                "ddl",
                "default_collation_name",
                "sync_status",
            ),
            from_=self._information_schema_source(
                "SCHEMATA",
                expr.catalog,
                self._region_qualifier(expr.location),
            ),
            order_by=self._order_by_first("schema_name"),
        )
        return self.format_query_statement(query)

    def format_bigquery_table_options_query_statement(
        self, expr: "BigQueryTableOptionsQueryStatement"
    ) -> Tuple[str, tuple]:
        """Render the ``TABLE_OPTIONS`` question.

        One row per option, so the projection carries ``option_type``
        beside ``option_value``: ``labels`` is an ``ARRAY<STRUCT>`` and
        collapsing the rows would lose which option carried which shape.

        https://cloud.google.com/bigquery/docs/information-schema-table-options
        """
        query = QueryStatement(
            self,
            select=self._columns(
                "table_catalog",
                "table_schema",
                "table_name",
                "option_name",
                "option_type",
                "option_value",
            ),
            from_=self._information_schema_source("TABLE_OPTIONS", expr.catalog, expr.schema),
            where=ComparisonPredicate(
                self,
                ComparisonPredicate.coerce_operator("="),
                Column(self, "table_name"),
                Literal(self, expr.table_name),
            ),
            order_by=self._order_by_first("option_name"),
        )
        return self.format_query_statement(query)

    def format_bigquery_partition_list_query_statement(
        self, expr: "BigQueryPartitionListQueryStatement"
    ) -> Tuple[str, tuple]:
        """Render the ``PARTITIONS`` question.

        A dataset qualifier only -- this view takes no region qualifier,
        unlike ``SCHEMATA``.

        https://cloud.google.com/bigquery/docs/information-schema-partitions
        """
        query = QueryStatement(
            self,
            select=self._columns(
                "table_catalog",
                "table_schema",
                "table_name",
                "partition_id",
                "total_rows",
                "total_logical_bytes",
                "total_billable_bytes",
                "last_modified_time",
                "storage_tier",
            ),
            from_=self._information_schema_source("PARTITIONS", expr.catalog, expr.schema),
            where=ComparisonPredicate(
                self,
                ComparisonPredicate.coerce_operator("="),
                Column(self, "table_name"),
                Literal(self, expr.table_name),
            ),
            order_by=self._order_by_first("partition_id"),
        )
        return self.format_query_statement(query)

    # ------------------------------------------------------------------ #
    # The core statement names, answered the BigQuery way
    # ------------------------------------------------------------------ #
    #
    # Core's ``IntrospectorMixin`` builds a core-named statement per question
    # and renders it through ``format_<name>_query_statement``. This dialect
    # declares every question it can answer (the ``supports_*`` probes above),
    # so the core entries have to reach a BigQuery answer rather than core's
    # ``NotImplementedError`` -- a capability declared and not answerable is
    # worse than a capability declined. Each entry below is an adapter: it
    # reads the core statement's parameters and renders through the
    # BigQuery-named entry above, so the spelling is written once.
    #
    # A core statement carries a dataset in its ``schema`` slot and no way to
    # say which *project* qualifies it. Every dataset-scoped BigQuery view
    # needs one, so an adapter with no schema refuses -- by name -- instead of
    # rendering a query the server would reject. The BigQuery statements add
    # the ``catalog`` slot for exactly this, and the introspector resolves
    # both.

    def _core_schema_or_refuse(self, schema: Optional[str], view: str) -> str:
        """The dataset a core statement's schema slot carries.

        Args:
            schema: The core statement's ``schema`` parameter.
            view: The view the question reads, named in the refusal.

        Returns:
            The dataset ID.

        Raises:
            UnsupportedFeatureError: The core statement carries no dataset.
        """
        dataset = (schema or "").strip().strip("`")
        if not dataset:
            raise UnsupportedFeatureError(
                self.name,
                f"a dataset-less INFORMATION_SCHEMA.{view} query",
                "BigQuery's INFORMATION_SCHEMA views are dataset-scoped (or "
                "project-and-region scoped, for SCHEMATA), so the generic "
                "statement needs a schema. Construct the BigQuery statement "
                "from rhosocial.activerecord.backend.impl.bigquery.expression."
                ".introspection -- it carries the project too -- or let the "
                "backend's introspector resolve it.",
            )
        return dataset

    def format_database_info_query_statement(
        self, expr: "DatabaseInfoQueryStatement"
    ) -> Tuple[str, tuple]:
        """The core spelling of the database-info question.

        The question is project-level, so it needs no dataset: the core
        statement's parameters are none and the BigQuery answer is the
        documented system variable.
        """
        del expr
        return self.format_bigquery_database_info_query_statement(
            BigQueryDatabaseInfoQueryStatement(self)
        )

    def format_table_list_query_statement(
        self, expr: "TableListQueryStatement"
    ) -> Tuple[str, tuple]:
        """The core spelling of the table-list question."""
        bigquery_expr = BigQueryTableListQueryStatement(
            self,
            schema=self._core_schema_or_refuse(expr.schema, "TABLES"),
            include_views=expr.include_views,
            include_system=expr.include_system,
            table_type=expr.table_type,
        )
        return self.format_bigquery_table_list_query_statement(bigquery_expr)

    def format_table_info_query_statement(
        self, expr: "TableInfoQueryStatement"
    ) -> Tuple[str, tuple]:
        """The core spelling of the single-table question.

        Answered as the ``TABLES`` query filtered to the one name, which is
        the metadata BigQuery has about a table. The columns, the primary
        key and the foreign keys of that table are separate questions the
        introspector composes -- no single view carries all of them.
        """
        query = QueryStatement(
            self,
            select=self._columns(
                "table_catalog",
                "table_schema",
                "table_name",
                "table_type",
                "is_insertable_into",
                "is_typed",
                "creation_time",
                "ddl",
                "default_collation_name",
            ),
            from_=self._information_schema_source(
                "TABLES", None, self._core_schema_or_refuse(expr.schema, "TABLES")
            ),
            where=ComparisonPredicate(
                self,
                ComparisonPredicate.coerce_operator("="),
                Column(self, "table_name"),
                Literal(self, expr.table_name),
            ),
        )
        return self.format_query_statement(query)

    def format_column_info_query_statement(
        self, expr: "ColumnInfoQueryStatement"
    ) -> Tuple[str, tuple]:
        """The core spelling of the column question."""
        bigquery_expr = BigQueryColumnInfoQueryStatement(
            self,
            table_name=expr.table_name,
            schema=self._core_schema_or_refuse(expr.schema, "COLUMNS"),
        )
        return self.format_bigquery_column_info_query_statement(bigquery_expr)

    def format_index_info_query_statement(
        self, expr: "IndexInfoQueryStatement"
    ) -> Tuple[str, tuple]:
        """The core spelling of the index (primary key) question."""
        bigquery_expr = BigQueryIndexInfoQueryStatement(
            self,
            table_name=expr.table_name,
            schema=self._core_schema_or_refuse(expr.schema, "TABLE_CONSTRAINTS"),
        )
        return self.format_bigquery_index_info_query_statement(bigquery_expr)

    def format_foreign_key_query_statement(
        self, expr: "ForeignKeyQueryStatement"
    ) -> Tuple[str, tuple]:
        """Refuse: the catalog never names the referenced relation.

        The ``supports_*`` probe above already declines, so core's own entry
        would refuse; it is implemented here to say *why*, and to say it the
        same way whether the caller reached core's entry or the BigQuery one.
        """
        del expr
        raise UnsupportedFeatureError(
            self.name,
            "foreign key introspection",
            "BigQuery's INFORMATION_SCHEMA reports that a foreign key "
            "exists (TABLE_CONSTRAINTS.constraint_type = 'FOREIGN KEY') and "
            "reports its columns (KEY_COLUMN_USAGE), but neither view names "
            "the referenced table or its columns, and there is no "
            "REFERENTIAL_CONSTRAINTS view. list_foreign_keys() therefore "
            "returns an empty list rather than inventing the other side.",
        )

    def format_view_list_query_statement(self, expr: "ViewListQueryStatement") -> Tuple[str, tuple]:
        """The core spelling of the view-list question."""
        bigquery_expr = BigQueryViewListQueryStatement(
            self,
            schema=self._core_schema_or_refuse(expr.schema, "VIEWS"),
            include_system=expr.include_system,
        )
        return self.format_bigquery_view_list_query_statement(bigquery_expr)

    def format_view_info_query_statement(self, expr: "ViewInfoQueryStatement") -> Tuple[str, tuple]:
        """The core spelling of the single-view question."""
        bigquery_expr = BigQueryViewInfoQueryStatement(
            self,
            view_name=expr.view_name,
            schema=self._core_schema_or_refuse(expr.schema, "VIEWS"),
        )
        return self.format_bigquery_view_info_query_statement(bigquery_expr)

    def format_trigger_list_query_statement(
        self, expr: "TriggerListQueryStatement"
    ) -> Tuple[str, tuple]:
        """Refuse: BigQuery has no triggers, so there is no catalog view."""
        del expr
        raise UnsupportedFeatureError(
            self.name,
            "trigger introspection",
            "BigQuery has no triggers, so there is no catalog view to query. "
            "list_triggers() returns an empty list.",
        )

    def format_trigger_info_query_statement(
        self, expr: "TriggerInfoQueryStatement"
    ) -> Tuple[str, tuple]:
        """Refuse: BigQuery has no triggers, so there is no catalog view."""
        del expr
        raise UnsupportedFeatureError(
            self.name,
            "trigger introspection",
            "BigQuery has no triggers, so there is no catalog view to query. "
            "get_trigger_info() answers None.",
        )


__all__ = ["BigQueryIntrospectionMixin"]
