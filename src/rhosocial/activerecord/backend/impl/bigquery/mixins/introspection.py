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
from rhosocial.activerecord.backend.expression.advanced_functions import CaseExpression
from rhosocial.activerecord.backend.expression.core import (
    CastExpression,
    Column,
    FunctionCall,
    Literal,
    RowCountWildcard,
    Subquery,
)
from rhosocial.activerecord.backend.expression.functions.aggregate import (
    CountFunction,
    SumFunction,
)
from rhosocial.activerecord.backend.expression.objects import Table
from rhosocial.activerecord.backend.expression.predicates import (
    ComparisonPredicate,
    InPredicate,
    IsNullPredicate,
    LogicalPredicate,
)
from rhosocial.activerecord.backend.expression.query_parts import (
    GroupByHavingClause,
    JoinClause,
    LimitOffsetClause,
    OrderByClause,
)
from rhosocial.activerecord.backend.expression.sources import NamedRelationRef
from rhosocial.activerecord.backend.expression.statements.dql import QueryStatement
from rhosocial.activerecord.backend.expression.types.string import CharType
from rhosocial.activerecord.backend.introspection.types import IntrospectionScope

from ..expression.introspection import (
    BigQueryColumnDataProfileQueryStatement,
    BigQueryColumnInfoQueryStatement,
    BigQueryDatabaseInfoQueryStatement,
    BigQueryIndexInfoQueryStatement,
    BigQueryTableListQueryStatement,
    BigQueryViewInfoQueryStatement,
    BigQueryViewListQueryStatement,
)
from ..introspection.introspector import _VIEW_TYPES

if TYPE_CHECKING:  # pragma: no cover
    from rhosocial.activerecord.backend.expression.introspection import (
        ColumnDataProfileQueryStatement,
        ColumnInfoQueryStatement,
        ColumnValueSampleQueryStatement,
        DatabaseInfoQueryStatement,
        ForeignKeyQueryStatement,
        IndexInfoQueryStatement,
        JoinCoverageQueryStatement,
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


#: The column types the profile's aggregates cannot read. BigQuery's ``MIN`` and
#: ``MAX`` take "any orderable data type", which excludes ``ARRAY``, ``STRUCT``
#: (spelled ``RECORD`` where a nested schema is written out), ``JSON``,
#: ``GEOGRAPHY`` and ``RANGE``; ``COUNT(DISTINCT ...)`` excludes the same ones
#: plus nothing else that matters here, because the rest are groupable.
#:
#: A prefix test rather than an equality test: the catalogue reports a parameterised
#: type as one string, ``ARRAY<INT64>`` or ``STRUCT<a INT64, b STRING>``, so the
#: family name is all that is left to match on. ``RANGE`` is written
#: ``RANGE<DATE>`` by the same catalogue, so it matches the same way.
_PROFILE_OPAQUE_TYPE_PREFIXES = ("ARRAY", "STRUCT", "RECORD", "JSON", "GEOGRAPHY", "RANGE")


def _profile_aggregates_are_blind(data_type: Optional[str]) -> bool:
    """Whether the profile's aggregates cannot read a column of this type.

    Read off the declared type string the catalogue reports. A type this
    function does not recognise is treated as readable: the profile is a scan of
    the caller's table and the server is the final judge, but a name-derived
    guess that silently dropped a column's figures would be worse than a query
    that fails and says why.
    """
    if not data_type:
        return False
    return str(data_type).strip().upper().startswith(_PROFILE_OPAQUE_TYPE_PREFIXES)


class BigQueryIntrospectionMixin(IntrospectionMixin):
    """BigQuery's answers to the core introspection questions.

    ``supports_*`` declares them, ``format_*`` renders them. Three questions
    have no answer at all and say so instead of guessing: indexes (BigQuery
    has no index catalogue), foreign keys (the catalog reports *that* one
    exists without naming the referenced relation) and triggers (BigQuery
    has none). The introspector can still read a primary key from its
    constraints; that is a constraint question, not the index family.
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
        """Declined: BigQuery has no index catalogue to ask.

        BigQuery creates no user-visible indexes, and
        ``INFORMATION_SCHEMA`` documents no index view at all, so there is
        no question this dialect can answer. The primary key is a
        constraint rather than an index and stays reachable through the
        introspector's constraint read, but claiming the index family here
        would offer a CLI type that has nothing to run.
        """
        return False

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

    def supports_table_storage_introspection(self) -> bool:
        """``PARTITIONS`` answers a table's stored bytes.

        The capability for the per-table storage family: summing the
        dataset's partitions answers ``size_bytes`` for every table in one
        read. BigQuery's storage is managed byte storage -- there is no
        index to split off, so ``data_size_bytes`` and ``index_size_bytes``
        stay ``None``, which is the engine's shape rather than a gap. The
        partition-level rows (per-partition billable bytes, storage tiers)
        stay on this backend's own ``PARTITIONS`` family, finer than the
        common minimum asks for (``.claude/rules/introspection.md`` §5).
        """
        return True

    def get_supported_introspection_scopes(self) -> List[IntrospectionScope]:
        """The scopes this dialect can answer, less the three it declines."""
        return [
            IntrospectionScope.DATABASE,
            IntrospectionScope.SCHEMA,
            IntrospectionScope.TABLE,
            IntrospectionScope.COLUMN,
            IntrospectionScope.VIEW,
        ]

    # ------------------------------------------------------------------ #
    # Data profiles: the rows, not the declaration
    # ------------------------------------------------------------------ #

    def supports_column_data_profile(self) -> bool:
        """BigQuery answers a profile only by scanning the table's rows.

        There is no per-column statistics catalogue to read.
        ``INFORMATION_SCHEMA.COLUMNS`` describes what a column *declares* --
        type, nullability, default -- and no view reports what its rows hold:
        no ``null_frac``, no distinct count, no bounds. So the answer is exact
        and bought with a scan.

        **That scan is billed.** BigQuery charges by bytes read, so a profile is
        the most expensive thing this backend can be asked, and unlike every
        other introspection family its price is proportional to the table
        rather than to the schema. It is one scan, not one per column -- the
        formatter projects every column's aggregates in a single ``SELECT`` --
        but it is still a full read of the table, and it is why this sits behind
        an explicit call rather than in any automatic pass over a schema.

        ``COUNT(DISTINCT ...)`` is the exact spelling and is what the statement
        uses; ``APPROX_COUNT_DISTINCT`` would be cheaper and approximate, and a
        figure derived from a sample would have to be labelled
        ``source='sample'`` rather than ``'aggregate'`` -- the label exists so a
        caller can tell, and this backend answers exactly.
        """
        return True

    def supports_column_value_sample(self) -> bool:
        """BigQuery lists values by grouping the column, and pays for the scan.

        Nothing is precomputed, so this costs one grouped read of the table --
        the same billed bytes as the profile, plus a sort of the groups. It is a
        separate probe because it is a separate scan: a caller asking only for
        the most frequent values should not be charged for the five other
        aggregates per column the profile computes.

        A column of a type BigQuery cannot group -- ``ARRAY``, ``STRUCT``,
        ``JSON``, ``GEOGRAPHY`` -- is refused by the server. That is the
        engine's rule about the chosen column rather than a gap in this family,
        and the answer is a server error naming the column, not a shorter list
        that looks complete.
        """
        return True

    def supports_join_coverage(self) -> bool:
        """BigQuery measures overlap by counting distinct values on both sides.

        Exact, and paid for with a read of each column: one for the overlap and
        one for the denominator, twice over, because both directions are
        reported. Every one of those reads is billed, which makes this the most
        expensive measurement in the family -- two columns of two tables rather
        than one table's profile.

        Answering ``True`` is right because the probe asks whether the engine
        *can* answer, not whether it can answer cheaply: the cost belongs in the
        docstring, not in a ``False`` that would claim BigQuery cannot measure
        its own rows.
        """
        return True

    def profile_statement(
        self,
        *,
        table_name: str,
        schema: Optional[str],
        columns: List[Any],
    ) -> "BigQueryColumnDataProfileQueryStatement":
        """The profile question, told which columns its aggregates can read.

        Args:
            table_name: The table whose columns are profiled.
            schema: The dataset, or a ``project.dataset`` pair.
            columns: The table's columns as the catalogue reported them --
                :class:`~rhosocial.activerecord.backend.introspection.types.IntrospectionColumnInfo`
                values, not names, because each one's declared type decides
                whether ``MIN``/``MAX`` and ``COUNT(DISTINCT ...)`` may be asked
                of it.

        Returns:
            The statement. Render it with ``to_sql()``.
        """
        return BigQueryColumnDataProfileQueryStatement(
            self,
            table_name=table_name,
            schema=schema,
            columns=tuple(column.name for column in columns),
            opaque_columns=tuple(
                column.name
                for column in columns
                if _profile_aggregates_are_blind(
                    getattr(column, "data_type_full", None) or column.data_type
                )
            ),
        )

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
        ``VIEW`` and ``MATERIALIZED_VIEW`` keep the distinction the catalog
        draws. A catalog spelling is passed through unchanged, and a
        spelling this backend does not know resolves to nothing -- which the
        caller renders as the no-match predicate rather than guessing.
        """
        if not table_type:
            return ()
        raw = str(table_type).strip().upper().replace("_", " ")
        if raw in ("BASE TABLE", "BASE"):
            return _BASE_TABLE_TYPES
        if raw == "VIEW":
            return ("VIEW",)
        if raw == "MATERIALIZED VIEW":
            return ("MATERIALIZED VIEW",)
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

        The projection is the statement's own, and its default is the whole
        documented column list -- what a real BigQuery answers. Nothing here
        narrows it: an endpoint that lacks one of those names fails the
        question during analysis rather than answering it ``NULL``, and the
        way to survive that is to reask the narrower projection *after* the
        endpoint has said it cannot answer, which the introspector does
        (``list_columns``). Choosing the narrow list up front would mean an
        endpoint's limitation decided what every server was asked for, and
        the fourteen names it leaves out -- whether a column is generated,
        what a computed one is computed from, what an identity column's
        bounds are, which column the table clusters by -- would silently
        become "the catalog says no".
        """
        query = QueryStatement(
            self,
            select=self._columns(*expr.projection),
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
            where=(
                ComparisonPredicate(
                    self,
                    ComparisonPredicate.coerce_operator("="),
                    Column(self, "table_name"),
                    Literal(self, expr.table_name),
                )
                if expr.table_name is not None
                else None
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

    # ------------------------------------------------------------------ #
    # Data profiles: the rows themselves
    # ------------------------------------------------------------------ #

    def _user_relation(self, table_name: str, schema: Optional[str]) -> Table:
        """A user table as a ``FROM`` source, qualified by its dataset.

        Unlike the ``INFORMATION_SCHEMA`` questions this backend asks, the
        relation here is the caller's own table, so its name, its dataset and
        the project above them are all identifiers the dialect quotes. The
        schema slot carries what the caller passed: a dataset, or a
        ``project.dataset`` pair, which is split so the project lands on the
        object's ``catalog_name`` and the dataset on its ``schema_name``.

        An absent dataset is not refused here; it means the connection's default
        dataset, which is the same convention every other statement this backend
        renders for a user relation follows (see
        :class:`~...backend.qualified_names.BigQueryQualifiedNameMixin`). The
        introspector resolves the configured default before it gets here, so a
        caller that configured one gets a qualified name and one that did not
        gets the server's own answer.
        """
        dataset = (schema or "").strip().strip("`")
        project, _, name = dataset.rpartition(".")
        return Table(
            self,
            table_name,
            catalog_name=project or None,
            schema_name=name or None,
        )

    def _profile_label(self, text: Optional[str], alias: str) -> CastExpression:
        """A constant label as a named projection.

        A :class:`~...expression.core.Literal` is deliberately unaliasable -- a
        value has nothing to name -- so the constant is cast to ``STRING``,
        which is the smallest node that carries a result name. ``None`` is the
        same node holding SQL ``NULL``, which is how an absent figure is
        projected without inventing a type for it.

        ``CAST`` rather than a bare literal matters for a second reason here:
        the arms of a profile row are not a union, but ``STRING`` is also the
        type a label should have when it is compared with, or sorted beside,
        another label.
        """
        return CastExpression(
            self,
            Literal(self, text, inline=True),
            CharType(self),
            alias=alias,
        )

    def _profile_slot(self, index: int, suffix: str) -> str:
        """The result name of one slot of one column's group.

        Positional rather than column-named: a column name may contain any
        character the catalogue accepts, while these names are fixed words the
        parser reads. The column's *name* travels beside them, cast to text, so
        the answer says which column each group is about.
        """
        return f"c{index}_{suffix}"

    def _profile_column_slots(
        self, index: int, column_name: str, opaque: bool
    ) -> List[Any]:
        """The five entries one column contributes to the profile row.

        ``null_count`` is a ``SUM`` over a ``CASE`` so an empty table answers
        ``NULL`` rather than a fabricated zero -- the parser then reports no
        fraction, which is the truth about a table with no rows. The distinct
        count and the bounds are the two figures a column's declared type can
        put out of reach: for an opaque type they are projected as ``NULL``,
        because BigQuery refuses the aggregate rather than answering ``NULL``
        for it.
        """
        column = Column(self, column_name)
        slots: List[Any] = [
            self._profile_label(column_name, self._profile_slot(index, "name")),
            SumFunction(
                self,
                CaseExpression(
                    self,
                    cases=[
                        (
                            IsNullPredicate(self, column),
                            Literal(self, 1, inline=True),
                        )
                    ],
                    else_result=Literal(self, 0, inline=True),
                ),
            ).as_(self._profile_slot(index, "null_count")),
        ]
        if opaque:
            slots.extend(
                [
                    self._profile_label(None, self._profile_slot(index, "distinct_count")),
                    self._profile_label(None, self._profile_slot(index, "min")),
                    self._profile_label(None, self._profile_slot(index, "max")),
                ]
            )
        else:
            # ``MIN``/``MAX`` keep their native type in the projection and are
            # cast to ``STRING`` only to name them: a profile row is one row, so
            # the cast is not the union's type coercion -- it is the same choice
            # the label makes, and it keeps every bound renderable whatever the
            # column holds.
            slots.extend(
                [
                    CountFunction(self, column, distinct=True).as_(
                        self._profile_slot(index, "distinct_count")
                    ),
                    CastExpression(
                        self,
                        FunctionCall(self, "MIN", column),
                        CharType(self),
                        alias=self._profile_slot(index, "min"),
                    ),
                    CastExpression(
                        self,
                        FunctionCall(self, "MAX", column),
                        CharType(self),
                        alias=self._profile_slot(index, "max"),
                    ),
                ]
            )
        return slots

    def format_bigquery_column_data_profile_query_statement(
        self, expr: "BigQueryColumnDataProfileQueryStatement"
    ) -> Tuple[str, tuple]:
        """Format a per-column profile as one aggregate row.

        The BigQuery spelling of the question, and the one the class declares:
        §3 makes the entry the kind's own name, so
        :class:`BigQueryColumnDataProfileQueryStatement` names this entry while
        core's :class:`ColumnDataProfileQueryStatement` names
        ``format_column_data_profile_query_statement`` -- which is the adapter
        below, reading the same parameters off whichever statement carries
        them. Core's statement has no ``opaque_columns``, so its columns are
        all assumed readable; the BigQuery one says which are not.

        BigQuery has no statistics catalogue, so the answer is the rows
        themselves: one ``SELECT`` projecting, for every column, its name, its
        null count, its distinct count, its bounds and the table's row count,
        plus the provenance ``'aggregate'``.

        **One row, not one ``UNION ALL`` arm per column, and that is a billing
        decision as much as a spelling one.** BigQuery charges for bytes read,
        and each arm of a union that reads the same table is a read of it: a
        fifty-column table would be scanned fifty times for the same figures.
        A single projection is scanned once, so this is the cheapest exact
        answer the engine can give -- though "cheapest exact" is still a full
        scan, and the most expensive introspection this backend offers.

        The row form is also what keeps the bounds typed. A union resolves one
        common type across its arms, so ``min_value`` carrying an ``INT64`` from
        one column and a ``STRING`` from another would be a type error rather
        than a coercion; here every slot belongs to exactly one column.

        ``NULL`` for an unreadable type is a figure the engine refuses to
        measure, not one it measured as absent -- BigQuery will not compute
        ``MIN``/``MAX`` over ``ARRAY``, ``STRUCT``, ``JSON``, ``GEOGRAPHY`` or
        ``RANGE`` columns, and ``COUNT(DISTINCT ...)`` over the same. The
        statement therefore leaves those three slots ``NULL`` and still counts
        the column's nulls, because that count is answerable for every type.

        An empty column list renders the row with the table's own facts and no
        column groups; the parser reads it as an empty profile, which is the
        truth about a table with no columns and not an error.
        """
        relation = self._user_relation(expr.table_name, expr.schema)
        opaque = frozenset(getattr(expr, "opaque_columns", ()))
        select: List[Any] = []
        for index, column_name in enumerate(expr.columns, start=1):
            select.extend(
                self._profile_column_slots(index, column_name, column_name in opaque)
            )
        select.append(CountFunction(self, RowCountWildcard(self)).as_("row_count"))
        select.append(self._profile_label("aggregate", "source"))
        query = QueryStatement(
            self,
            select=select,
            from_=NamedRelationRef(self, relation),
        )
        return self.format_query_statement(query)

    def format_column_data_profile_query_statement(
        self, expr: "ColumnDataProfileQueryStatement"
    ) -> Tuple[str, tuple]:
        """The core spelling of the profile question.

        An adapter in the shape of every other core-named entry in this mixin:
        it reads the core statement's parameters and renders through the
        BigQuery-named entry above, so the projection is written once.

        ``opaque_columns`` is passed through only when the statement carries
        it. Core's statement does not -- it knows no column types -- so its
        columns are all projected as readable, which is the same assumption
        an aggregating dialect makes when a caller names no types at all.
        """
        return self.format_bigquery_column_data_profile_query_statement(
            BigQueryColumnDataProfileQueryStatement(
                self,
                table_name=expr.table_name,
                schema=expr.schema,
                columns=expr.columns,
                opaque_columns=getattr(expr, "opaque_columns", ()),
            )
        )

    def format_column_value_sample_query_statement(
        self, expr: "ColumnValueSampleQueryStatement"
    ) -> Tuple[str, tuple]:
        """Format a most-frequent-values listing with a grouped scan.

        Nothing is precomputed in BigQuery, so this costs a ``GROUP BY`` over the
        column and a sort of the groups -- the same billed scan as the profile,
        which is why the two are separate probes rather than one call that would
        make the cheap half pay for the dear one.

        ``ORDER BY COUNT(*) DESC`` is what makes the answer "the most frequent
        values" rather than "the first values"; ties break by the value so two
        runs of the same query agree. The ``LIMIT`` is a bind parameter, as it is
        everywhere else in this dialect: the caller's integer is never spliced
        into statement text.

        A column BigQuery cannot group -- ``ARRAY``, ``STRUCT``, ``JSON``,
        ``GEOGRAPHY`` -- is refused by the server. That is the engine's rule
        about the column, and the formatter cannot know the column's type
        without a catalogue read it was not given; the error names the column,
        which is a better answer than a listing that silently omits it.
        """
        relation = self._user_relation(expr.table_name, expr.schema)
        query = QueryStatement(
            self,
            select=[
                Column(self, expr.column_name).as_("value"),
                CountFunction(self, RowCountWildcard(self)).as_("count"),
            ],
            from_=NamedRelationRef(self, relation),
            group_by_having=GroupByHavingClause(
                self, group_by=[Column(self, expr.column_name)]
            ),
            order_by=OrderByClause(
                self,
                expressions=[
                    (CountFunction(self, RowCountWildcard(self)), "DESC"),
                    (Column(self, expr.column_name), "ASC"),
                ],
            ),
            limit_offset=LimitOffsetClause(self, limit=int(expr.limit)),
        )
        return self.format_query_statement(query)

    def _coverage_fraction(self, column, source, other_column, other_source):
        """One side of the overlap: the share of *column* the other side holds.

        The numerator counts the *distinct* values of *column* that also occur in
        *other_column*, by counting ``DISTINCT column`` under an ``IN`` predicate
        over the other side's non-NULL values. Distinct on both sides is what
        makes the figure a coverage of values rather than of rows -- a key
        repeated a thousand times that matches once would otherwise read as well
        covered -- and the count needs no derived table, so no alias has to be
        invented for one.

        ``IS NOT NULL`` is written on both halves rather than relied upon. In the
        numerator it is load-bearing: a value list containing NULL would never
        match, but the predicate says so where a reader can see it. In the
        divisor ``COUNT(DISTINCT ...)`` skips NULLs on its own, but the share is
        of the values that could join, and that is the fact being measured.
        ``NULLIF(..., 0)`` then makes a column with no value at all answer
        ``NULL`` rather than ``0``, which the parser reads as "no fraction": the
        difference between "nothing matched" and "nothing to match" survives to
        the caller.

        BigQuery's ``/`` over two ``INT64`` counts already answers a ``FLOAT64``,
        so there is no ``* 1.0`` here: multiplying first would add noise and
        change nothing.
        """
        overlap = QueryStatement(
            self,
            select=[CountFunction(self, column, distinct=True)],
            from_=source,
            where=LogicalPredicate(
                self,
                "AND",
                column.is_not_null(),
                InPredicate(
                    self,
                    column,
                    Subquery(
                        self,
                        QueryStatement(
                            self,
                            select=[other_column],
                            from_=other_source,
                            where=other_column.is_not_null(),
                        ),
                    ),
                ),
            ),
        )
        total = QueryStatement(
            self,
            select=[
                FunctionCall(
                    self,
                    "NULLIF",
                    CountFunction(self, column, distinct=True),
                    Literal(self, 0, inline=True),
                )
            ],
            from_=source,
            where=column.is_not_null(),
        )
        return Subquery(self, overlap) / Subquery(self, total)

    def format_join_coverage_query_statement(
        self, expr: "JoinCoverageQueryStatement"
    ) -> Tuple[str, tuple]:
        """Format a two-sided measurement of two columns' value domains.

        Unlike every other statement in this module, this one names two user
        tables rather than one catalogue view: the question is a relation
        between two objects, so both sides are carried explicitly and their
        identifiers are the dialect's to quote (see :meth:`_user_relation`). The
        aliases ``l`` and ``r`` are what keep the two columns apart in the
        rendered statement, and they are quoted like every other identifier.

        The row carries both fractions because neither is meaningful alone. A
        left share of 1.0 beside a right share of 0.2 says every tested value
        exists on the other side while most of that other domain is
        unaccounted for; a single similarity score would average the two and
        describe neither. A caller deciding whether a join is worth writing
        needs to know which direction is incomplete.

        Both figures are counted over *distinct* values, with NULLs excluded
        from the numerators and the denominators alike -- a NULL is not a value
        that could ever join, so it belongs in neither half of the fraction. The
        denominators are ``NULLIF``-guarded so a column with nothing to match
        answers ``NULL``, which the parser reports as "no measurement" instead
        of a zero overlap that would read as a real answer. See
        :meth:`_coverage_fraction` for both rules in place.

        The cost is the two sides read for their distinct domains plus the
        intersection between them, twice, because both directions are reported.
        Every read is billed, which is why this belongs behind an explicit call
        rather than in any automatic pass.

        BigQuery needs no ``FROM`` for a projection made only of subqueries, so
        the two measurements share one row without a dummy relation.
        """
        left_source = NamedRelationRef(
            self, self._user_relation(expr.left_table, expr.schema), alias="l"
        )
        right_source = NamedRelationRef(
            self, self._user_relation(expr.right_table, expr.schema), alias="r"
        )
        left_column = Column(self, expr.left_column, table="l")
        right_column = Column(self, expr.right_column, table="r")

        query = QueryStatement(
            self,
            select=[
                self._coverage_fraction(
                    left_column, left_source, right_column, right_source
                ).as_("left_coverage"),
                self._coverage_fraction(
                    right_column, right_source, left_column, left_source
                ).as_("right_coverage"),
            ],
        )
        return self.format_query_statement(query)


__all__ = ["BigQueryIntrospectionMixin"]
