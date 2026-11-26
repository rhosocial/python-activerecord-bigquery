# src/rhosocial/activerecord/backend/impl/bigquery/introspection/introspector.py
"""BigQuery concrete introspectors.

Both classes answer the core introspection questions from BigQuery's
``INFORMATION_SCHEMA`` views rather than from a DB-API catalog:

======================  ==========================================
Question                Catalog view
======================  ==========================================
database info           ``SELECT @@project_id`` (system variable)
tables                  ``INFORMATION_SCHEMA.TABLES``
columns                 ``INFORMATION_SCHEMA.COLUMNS``
indexes                 none -- BigQuery has no index catalogue
primary key             ``TABLE_CONSTRAINTS`` + ``KEY_COLUMN_USAGE``
views                   ``INFORMATION_SCHEMA.VIEWS``
routines                ``INFORMATION_SCHEMA.ROUTINES``
datasets                ``INFORMATION_SCHEMA.SCHEMATA``
table options           ``INFORMATION_SCHEMA.TABLE_OPTIONS``
partitions              ``INFORMATION_SCHEMA.PARTITIONS``
======================  ==========================================

**No SQL is written here.** Every question is a statement object from
:mod:`...expression.introspection`, rendered by the dialect mixin
(:mod:`...mixins.introspection`) into SQL text through ``to_sql()``. This
module resolves *which* dataset and project a question is about, runs the
rendered text through the executor, and parses the rows. That split is the
project rule, and it is what makes the backtick quoting of a
``project.dataset`` path the dialect's business rather than something
restated by hand here -- where a name containing a backtick would produce
SQL the server refuses.

**Dataset ↔ schema.** BigQuery has ``project.dataset.table`` and no schema
level below a dataset, so the core ``schema`` parameter carries a dataset
ID here. Pass the dataset alone and the configured project is used, or pass
``project.dataset`` to read a dataset in another project. Builders that
need a dataset raise :class:`ValueError` with that instruction when neither
the argument nor the connection config supplies one; nothing is guessed.

**Two ``COLUMNS`` projections, because there is nothing else to ask.**
``INFORMATION_SCHEMA.COLUMNS`` reports its own columns nowhere, so the only
question that says which of them an endpoint carries is the ``COLUMNS``
question itself. :meth:`list_columns` therefore asks the whole documented
list and, if the endpoint fails the question, asks the narrower list instead
-- remembering the answer for the rest of the manager's life, so a real
server pays nothing for the fallback and an emulator pays one failed
question once rather than one per table. :func:`_asked_columns` reads which
projection ran off the row, and the parsed column records it under
:data:`COLUMNS_ASKED_KEY` so a name the endpoint was never asked reports
``None`` rather than an answer of *no*. See
:data:`~..expression.introspection.COLUMNS_PROJECTION_FULL` and
the emulator's ``_EMULATOR_COLUMNS_PROJECTION``.

**What BigQuery's catalog cannot answer.**

*Foreign keys.* ``TABLE_CONSTRAINTS`` reports that a foreign key exists and
``KEY_COLUMN_USAGE`` reports its columns, but neither view names the
referenced table or its columns, and BigQuery has no
``REFERENTIAL_CONSTRAINTS`` view. A :class:`IntrospectionForeignKeyInfo`
whose ``referenced_table`` is empty would be a worse answer than no answer,
so :meth:`list_foreign_keys` returns an empty list and the builder refuses
rather than fabricating the other side.

*Triggers.* BigQuery has no triggers, so :meth:`list_triggers` returns an
empty list and the builder refuses instead of inventing a catalog view.

*Indexes.* BigQuery has no user-created indexes and its catalog exposes no
index view, so :meth:`supports_index_introspection` answers ``False`` and
no CLI type offers the family. Primary-key constraints are still reported
as :class:`IndexInfo` values so ``get_primary_key()`` works; ``IndexType``
is ``UNKNOWN`` because there is no index structure behind it. The neutral
:meth:`list_index_states` is left to core's refusal for the same reason --
a primary key is a constraint question, answered by
:meth:`list_constraint_states`.

*Sequences and derived objects.* BigQuery has neither sequences nor
engine-created, independently nameable objects (an identity column is a
declared column, not a sequence), and ``INFORMATION_SCHEMA`` has no view
for either family, so :meth:`list_sequence_states` and
:meth:`list_derived_objects` stay refusals.

**Partition state.** :meth:`get_partition_state` is the neutral answer to
"is this table partitioned": a :class:`PartitionState` whose ``scheme`` is
``None`` when it is not -- never a ``None`` object, because core made
``TableState.partitioning`` non-optional and ``scheme=None`` is the single
answer for every backend. ``PARTITIONS`` answers one row with a ``NULL``
``partition_id`` for an unpartitioned table; that row is the catalog saying
"no partitions", not a partition named ``NULL``, so it becomes the empty
state rather than a bound.
Column-, integer-range- and ingestion-time-partitioned tables all answer
:class:`PartitionScheme` ``RANGE`` -- the engine divides rows into
intervals of a column's value or of the ingestion time. Ingestion-time
partitioning is recognised from the ``_PARTITIONTIME`` / ``_PARTITIONDATE``
pseudo columns ``COLUMNS`` reports with ``is_hidden = 'YES'``; they are
dropped from the declared schema, so the partition question reads the raw
``COLUMNS`` answer rather than the parsed column list.

Documentation:

* ``INFORMATION_SCHEMA`` overview (dataset/region/project qualifiers)
  https://cloud.google.com/bigquery/docs/information-schema-intro
* ``TABLES`` https://cloud.google.com/bigquery/docs/information-schema-tables
* ``COLUMNS`` https://cloud.google.com/bigquery/docs/information-schema-columns
* ``VIEWS`` https://cloud.google.com/bigquery/docs/information-schema-views
* ``ROUTINES`` https://cloud.google.com/bigquery/docs/information-schema-routines
* ``TABLE_CONSTRAINTS``
  https://cloud.google.com/bigquery/docs/information-schema-table-constraints
* ``KEY_COLUMN_USAGE``
  https://cloud.google.com/bigquery/docs/information-schema-key-column-usage
* ``SCHEMATA``
  https://cloud.google.com/bigquery/docs/information-schema-datasets-schemata
* ``TABLE_OPTIONS``
  https://cloud.google.com/bigquery/docs/information-schema-table-options
* ``PARTITIONS``
  https://cloud.google.com/bigquery/docs/information-schema-partitions
* System variables (``@@project_id``)
  https://cloud.google.com/bigquery/docs/reference/system-variables

No BigQuery instance was available while writing this module. Statement
shapes follow the pages above; the parsing tests feed the documented column
names and value spellings directly.
"""

import copy
import warnings
from datetime import datetime
from typing import Any, Dict, List, NoReturn, Optional, Sequence, Tuple

from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError
from rhosocial.activerecord.backend.errors import DatabaseError
from rhosocial.activerecord.backend.introspection.base import (
    AbstractIntrospector,
    AsyncAbstractIntrospector,
    IntrospectorMixin,
)
from rhosocial.activerecord.backend.introspection.cache import IntrospectionCache
from rhosocial.activerecord.backend.introspection.errors import ObjectNotFoundError
from rhosocial.activerecord.backend.introspection.executor import (
    AsyncIntrospectorExecutor,
    IntrospectorExecutor,
)
from rhosocial.activerecord.backend.introspection.types import (
    ColumnDataProfile,
    ColumnNullable,
    ConstraintState,
    IndexColumnInfo,
    IndexInfo,
    IndexType,
    IntrospectionColumnInfo,
    IntrospectionDatabaseInfo,
    IntrospectionForeignKeyInfo,
    IntrospectionScope,
    IntrospectionTableInfo,
    IntrospectionTriggerInfo,
    IntrospectionViewInfo,
    ItemKind,
    PartitionBound,
    PartitionScheme,
    PartitionState,
    StorageOptionsState,
    TableState,
    TableType,
)

from ..expression.introspection import (
    _EMULATOR_COLUMNS_PROJECTION,
    COLUMNS_PROJECTION_FULL,
    BigQueryColumnInfoQueryStatement,
    BigQueryDatabaseInfoQueryStatement,
    BigQueryDatasetListQueryStatement,
    BigQueryIndexInfoQueryStatement,
    BigQueryPartitionListQueryStatement,
    BigQueryRoutineListQueryStatement,
    BigQueryTableListQueryStatement,
    BigQueryTableOptionsQueryStatement,
    BigQueryViewInfoQueryStatement,
    BigQueryViewListQueryStatement,
)
from .types import (
    BigQueryDatasetInfo,
    BigQueryPartitionInfo,
    BigQueryRoutineInfo,
    BigQueryTableOptionInfo,
    BigQueryTableStorageInfo,
)

#: BigQuery's documented ``TABLES.table_type`` spellings, mapped onto the
#: core enum. ``CLONE`` and ``SNAPSHOT`` are standard tables for the purpose
#: of "is this something I can select from"; the original spelling is kept in
#: ``IntrospectionTableInfo.extra["bigquery_table_type"]``.
#: https://cloud.google.com/bigquery/docs/information-schema-tables
_TABLE_TYPE_MAP = {
    "BASE TABLE": TableType.BASE_TABLE,
    "CLONE": TableType.BASE_TABLE,
    "SNAPSHOT": TableType.BASE_TABLE,
    "EXTERNAL": TableType.EXTERNAL,
    "VIEW": TableType.VIEW,
    "MATERIALIZED VIEW": TableType.MATERIALIZED_VIEW,
}

#: The views that are not tables, used when ``include_views=False``.
_VIEW_TYPES = ("VIEW", "MATERIALIZED VIEW")

#: The ``extra`` key a parsed column records the catalog names it was actually
#: asked for under. It is what separates "the catalog says this column is not
#: generated" from "nobody asked": the first is a value in the slot, the
#: second is the name's absence from this tuple -- and reading an unasked name
#: as an answer of *no* is how a consumer ends up told a column is not
#: generated when the truth is that the endpoint never carried the fact.
COLUMNS_ASKED_KEY = "columns_asked"

#: The pseudo columns BigQuery reports for an ingestion-time partitioned
#: table. ``COLUMNS`` answers them with ``is_hidden = 'YES'``, and
#: :meth:`~...BigQueryIntrospectorMixin.parse_columns` drops them because
#: they are not part of the declared schema -- which is why the partition
#: question reads the raw ``COLUMNS`` answer instead: their presence is the
#: only catalog signal that an ingestion-time table is partitioned at all
#: when it holds no partition rows yet.
_INGESTION_TIME_PSEUDO_COLUMNS = ("_PARTITIONTIME", "_PARTITIONDATE")

#: The ``TableState.kind`` and compound ``traits`` each documented
#: ``TABLES.table_type`` maps onto. ``CLONE`` and ``SNAPSHOT`` are ordinary
#: tables that remember what they were copied from, so the spelling rides in
#: ``traits`` beside ``kind="regular"`` rather than widening ``kind``.
#: A spelling this map does not know keeps the catalog's own word (lowercased)
#: in ``kind`` -- a backend may add its spelling, and folding an unknown one
#: onto "regular" would be the one place the catalog's distinction was seen
#: and thrown away.
#: https://cloud.google.com/bigquery/docs/information-schema-tables
_TABLE_STATE_KINDS: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "BASE TABLE": ("regular", ()),
    "CLONE": ("regular", ("clone",)),
    "SNAPSHOT": ("regular", ("snapshot",)),
    "EXTERNAL": ("external", ()),
    "VIEW": ("view", ()),
    "MATERIALIZED VIEW": ("materialized_view", ()),
}

#: The ``TABLE_OPTIONS`` only a partitioned table carries. Their presence is
#: how an empty partitioned table is still recognised as partitioned: its
#: ``PARTITIONS`` answer holds no rows and its ``COLUMNS`` answer names no
#: partitioning column.
_PARTITION_OPTIONS = ("partition_expiration_days", "require_partition_filter")

#: Core made ``TableState.partitioning`` non-optional, so the parser needs a
#: value when a caller has no partition answer to pass. It is the same empty
#: state ``get_partition_state`` returns for an unpartitioned table:
#: ``scheme`` is ``None``, not a ``None`` object. ``PartitionState`` is frozen,
#: and the parser never writes to it, so one shared instance is safe.
_EMPTY_PARTITION_STATE = PartitionState()

#: The ``routine_type`` spellings that are functions rather than procedures.
#: ``list_routines`` answers both, because they share one name namespace;
#: only these are asked about by ``item_exists(ItemKind.FUNCTION, ...)``.
_FUNCTION_ROUTINE_TYPES = ("FUNCTION", "AGGREGATE FUNCTION", "TABLE FUNCTION")


def _row_get(row: Dict[str, Any], key: str, default: Any = None) -> Any:
    """Read one catalog column, tolerating the case the driver used.

    BigQuery returns ``INFORMATION_SCHEMA`` column names in lowercase, but
    a row may come from a test fixture, an emulator or a future driver that
    preserves the uppercase spelling. The catalog's spelling does not change
    what the value means, so all three are accepted.
    """
    if key in row:
        return row[key]
    if key.lower() in row:
        return row[key.lower()]
    if key.upper() in row:
        return row[key.upper()]
    return default


def _row_asked(row: Dict[str, Any], key: str) -> bool:
    """Whether the question that produced *row* selected *key*.

    A projection selects names, and an endpoint returns one field per
    selected name -- so a field's presence *is* the record of the question
    that was asked, and its absence is never the endpoint answering "no".
    """
    return key in row or key.lower() in row or key.upper() in row


def _asked_columns(row: Dict[str, Any]) -> Tuple[str, ...]:
    """The documented ``COLUMNS`` names *row* was asked for, in their order.

    The two projections are both subsets of the documented list, so the
    intersection with it is the answer whichever one ran: the whole list for
    a real server, the narrower set for an endpoint that could not answer
    more. A name a future endpoint returns beyond that list cannot be
    attributed to the question -- no projection named it -- so it stays out
    of the tuple and is still read as a value, which is the only part of the
    answer that is true either way.
    """
    return tuple(name for name in COLUMNS_PROJECTION_FULL if _row_asked(row, name))


def _isoformat(value: Any) -> Optional[str]:
    """Render a catalog time as ISO-8601 text, leaving absent values absent."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _as_int(value: Any) -> Optional[int]:
    """Read a catalog count as an ``int``, or ``None`` when it is absent."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> Optional[bool]:
    """Read a ``YES``/``NO`` catalog flag as a bool, or ``None``."""
    if value is None:
        return None
    text = str(value).strip().upper()
    if text == "YES":
        return True
    if text == "NO":
        return False
    return None


def _as_option_bool(value: Any) -> Optional[bool]:
    """Read a ``TABLE_OPTIONS`` boolean option value as a bool, or ``None``.

    Option values are the catalog's rendering of the option's declared type;
    a ``BOOL`` option arrives as ``true``/``false`` (the two spellings
    ``TABLE_OPTIONS`` documents), and an absent option stays ``None`` -- not
    ``False``, which would claim the option was set to off.
    """
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in ("true", "yes"):
        return True
    if text in ("false", "no"):
        return False
    return None


def _option_values(options: List["BigQueryTableOptionInfo"]) -> Dict[str, Any]:
    """The option rows as ``name -> value``, lowercased for the lookup.

    ``TABLE_OPTIONS`` answers one row per option; the name is the key a
    caller asks about, and the catalog's spelling is normalised only in the
    dict's keys -- the original rows keep their own spelling.
    """
    return {option.option_name.lower(): option.option_value for option in options}


def _pseudo_partition_columns(rows: List[Dict[str, Any]]) -> Tuple[str, ...]:
    """The ingestion-time pseudo columns a raw ``COLUMNS`` answer carries.

    ``COLUMNS`` reports ``_PARTITIONTIME`` and ``_PARTITIONDATE`` with
    ``is_hidden = 'YES'`` and a ``NULL`` ordinal position; they are pseudo
    columns, not declared ones, so the parsed column list drops them. Their
    presence is the catalog's own statement that the table is partitioned by
    ingestion time, which column-based partitioning never carries and which
    an empty table's ``PARTITIONS``/``TABLE_OPTIONS`` answer cannot tell.
    """
    names = {str(_row_get(row, "column_name") or "").strip().upper() for row in rows}
    return tuple(name for name in _INGESTION_TIME_PSEUDO_COLUMNS if name in names)


class BigQueryIntrospectorMixin(IntrospectorMixin):
    """SQL building and row parsing shared by the sync and async managers.

    The ``*_statement`` factories resolve *which* dataset and project a
    question is about and construct the matching statement object from
    :mod:`...expression.introspection`; rendering is the dialect's job. The
    ``parse_*`` methods are pure Python: rows in, core introspection
    dataclasses out, shared by both managers.

    The one thing the two managers hold between calls is which ``COLUMNS``
    projection the endpoint in front of them answers -- see
    :meth:`list_columns`, which is where an endpoint that cannot answer the
    full documented list is asked the narrower one instead and the choice is
    remembered. It is state rather than a constant because the answer is the
    endpoint's, not this backend's.
    """

    #: The ``COLUMNS`` projection this manager asks with, assigned by the
    #: manager's ``__init__`` and narrowed by :meth:`list_columns`.
    columns_projection: Tuple[str, ...]

    # ------------------------------------------------------------------ #
    # Names and qualifiers
    # ------------------------------------------------------------------ #

    @property
    def default_schema(self) -> str:
        """Return the configured dataset ID, or ``""`` when there is none.

        The core ``schema`` parameter is BigQuery's dataset. A connection
        may name a default dataset; when it does not, callers have to say
        which dataset they mean rather than have one inferred.
        """
        config = getattr(self._backend, "config", None)
        if config is None:
            return ""
        return getattr(config, "dataset", None) or ""

    def _get_version(self) -> Tuple[int, ...]:
        """Return the feature-level version tuple carried by the backend.

        BigQuery does not report a server version over SQL; the backend's
        version is the emulated feature level (``3.0.0`` by default) and is
        reported as such rather than passed off as a server release.
        """
        return getattr(self._backend, "_version", (3, 0, 0))

    def _project(self) -> Optional[str]:
        """The configured project, or ``None`` for the query-executing one."""
        config = getattr(self._backend, "config", None)
        if config is None:
            return None
        return getattr(config, "project", None) or None

    def _resolve_dataset(self, schema: Optional[str]) -> Tuple[Optional[str], str]:
        """Split a schema argument into ``(project, dataset)``.

        Args:
            schema: A dataset ID, a ``project.dataset`` pair, or ``None``
                to use the connection's default dataset.

        Returns:
            The project (possibly ``None``, meaning the configured project,
            which the dialect then leaves unqualified) and the dataset ID.

        Raises:
            ValueError: When no dataset is available, or when the argument
                has more than one dot.
        """
        raw = schema if schema is not None else self.default_schema
        raw = (raw or "").strip()
        if raw.startswith("`") and raw.endswith("`") and len(raw) >= 2:
            raw = raw[1:-1].strip()
        if not raw:
            raise ValueError(
                "BigQuery introspection needs a dataset: pass schema= (the "
                "dataset ID) or configure BigQueryConnectionConfig(dataset=...)."
            )
        if "." not in raw:
            return self._project(), raw
        parts = raw.split(".")
        if len(parts) != 2 or not all(parts):
            raise ValueError(f"Expected a dataset ID or a project.dataset pair, got {raw!r}.")
        return parts[0], parts[1]

    def _schema_label(self, schema: Optional[str]) -> str:
        """Return the dataset ID to record on a parsed object.

        Parsing never raises for a missing dataset: the object being built
        still carries whatever the query already selected, and the caller
        that asked for it supplied the qualifier in the first place.
        """
        raw = schema if schema is not None else self.default_schema
        raw = (raw or "").strip().strip("`")
        if not raw:
            return ""
        return raw.split(".")[-1] if "." in raw else raw

    def _dataset_scoped(self, schema: Optional[str]) -> Tuple[Optional[str], str]:
        """The ``(catalog, dataset)`` pair every dataset-scoped view needs.

        Raises:
            ValueError: No dataset is reachable -- see :meth:`_resolve_dataset`.
        """
        return self._resolve_dataset(schema)

    # ------------------------------------------------------------------ #
    # Statement factories — rendered by the dialect
    # ------------------------------------------------------------------ #

    def database_info_statement(self) -> "BigQueryDatabaseInfoQueryStatement":
        """Return ``SELECT @@project_id AS catalog_name``, as a statement object."""
        return BigQueryDatabaseInfoQueryStatement(self.dialect)

    def table_list_statement(
        self,
        *,
        schema: Optional[str],
        include_system: bool,
        include_views: bool = True,
        table_type: Optional[str] = None,
    ) -> "BigQueryTableListQueryStatement":
        """Return the ``INFORMATION_SCHEMA.TABLES`` statement.

        ``include_system`` has no effect: BigQuery does not list system
        tables in this view. It is accepted so the core signature keeps
        working, and documented here rather than silently ignored.

        Args:
            schema: Dataset ID or ``project.dataset``; ``None`` for the
                connection default.
            include_system: Ignored (see above).
            include_views: When false and no ``table_type`` is given,
                exclude views and materialized views.
            table_type: A core ``TableType`` value or a catalog spelling.
                ``BASE_TABLE`` expands to base tables, clones and snapshots;
                ``VIEW`` and ``MATERIALIZED_VIEW`` each match their own
                catalog spelling.
        """
        catalog, dataset = self._dataset_scoped(schema)
        del include_system  # BigQuery's catalog has no system tables here.
        return BigQueryTableListQueryStatement(
            self.dialect,
            schema=dataset,
            catalog=catalog,
            include_views=include_views,
            table_type=table_type,
        )

    def column_info_statement(
        self,
        *,
        table_name: str,
        schema: Optional[str],
        projection: Sequence[str] = COLUMNS_PROJECTION_FULL,
    ) -> "BigQueryColumnInfoQueryStatement":
        """Return the ``INFORMATION_SCHEMA.COLUMNS`` statement.

        ``ordinal_position`` is selected because it orders the result; the
        other columns are the documented ones this backend maps onto
        :class:`IntrospectionColumnInfo` or keeps in ``extra``. Pseudo
        columns (``is_hidden = 'YES'``) are filtered in the parser, because
        their ``ordinal_position`` is documented as ``NULL`` and they are not
        part of the table's declared schema.

        Args:
            table_name: The table whose columns are wanted.
            schema: A dataset ID or a ``project.dataset`` pair; ``None``
                for the connection default.
            projection: The catalog columns to select. Defaults to the whole
                documented list, which is what a real BigQuery answers and
                therefore what a real server is asked; :meth:`list_columns`
                is what narrows it, and only for an endpoint that has just
                failed to answer the whole list.

        https://cloud.google.com/bigquery/docs/information-schema-columns
        """
        catalog, dataset = self._dataset_scoped(schema)
        return BigQueryColumnInfoQueryStatement(
            self.dialect,
            table_name=table_name,
            schema=dataset,
            catalog=catalog,
            projection=projection,
        )

    def index_info_statement(
        self, *, table_name: str, schema: Optional[str]
    ) -> "BigQueryIndexInfoQueryStatement":
        """Return the primary-key statement over constraints.

        ``TABLE_CONSTRAINTS`` documents ``constraint_type`` as either
        ``PRIMARY KEY`` or ``FOREIGN KEY``; only the former maps onto an
        index. The join to ``KEY_COLUMN_USAGE`` supplies the constrained
        columns in order.
        https://cloud.google.com/bigquery/docs/information-schema-table-constraints
        """
        catalog, dataset = self._dataset_scoped(schema)
        return BigQueryIndexInfoQueryStatement(
            self.dialect,
            table_name=table_name,
            schema=dataset,
            catalog=catalog,
        )

    def foreign_key_statement(self, *, table_name: str, schema: Optional[str]) -> "NoReturn":
        """Refuse: the catalog does not expose the referenced relation.

        See the module docstring. The public ``list_foreign_keys`` returns
        an empty list instead of calling this; the factory still refuses so
        a future caller cannot mistake it for an unanswered query.
        """
        del table_name, schema
        raise UnsupportedFeatureError(
            self.dialect.name,
            "foreign key introspection",
            "BigQuery's INFORMATION_SCHEMA reports that a foreign key exists "
            "but does not name the referenced table or columns, and it has no "
            "REFERENTIAL_CONSTRAINTS view. list_foreign_keys() therefore "
            "returns an empty list.",
        )

    def view_list_statement(
        self, *, schema: Optional[str], include_system: bool
    ) -> "BigQueryViewListQueryStatement":
        """Return the ``INFORMATION_SCHEMA.VIEWS`` statement.

        ``include_system`` is ignored: every row of this view is a user
        view. ``VIEWS`` is dataset-qualified, unlike ``SCHEMATA``.
        https://cloud.google.com/bigquery/docs/information-schema-views
        """
        del include_system
        catalog, dataset = self._dataset_scoped(schema)
        return BigQueryViewListQueryStatement(self.dialect, schema=dataset, catalog=catalog)

    def view_info_statement(
        self, *, view_name: str, schema: Optional[str]
    ) -> "BigQueryViewInfoQueryStatement":
        """Return one view's ``INFORMATION_SCHEMA.VIEWS`` statement."""
        catalog, dataset = self._dataset_scoped(schema)
        return BigQueryViewInfoQueryStatement(
            self.dialect, view_name=view_name, schema=dataset, catalog=catalog
        )

    def routine_list_statement(
        self, *, schema: Optional[str], routine_name: Optional[str] = None
    ) -> "BigQueryRoutineListQueryStatement":
        """Return the ``INFORMATION_SCHEMA.ROUTINES`` statement.

        With no name the statement lists the dataset's routines; with one it
        filters the same question to that row, which is how
        :meth:`get_routine_info` asks.

        https://cloud.google.com/bigquery/docs/information-schema-routines
        """
        catalog, dataset = self._dataset_scoped(schema)
        return BigQueryRoutineListQueryStatement(
            self.dialect,
            schema=dataset,
            catalog=catalog,
            routine_name=routine_name,
        )

    def trigger_list_statement(
        self, *, schema: Optional[str], table_name: Optional[str] = None
    ) -> "NoReturn":
        """Refuse: BigQuery has no triggers and no trigger catalog view."""
        del schema, table_name
        raise UnsupportedFeatureError(
            self.dialect.name,
            "trigger introspection",
            "BigQuery has no triggers, so there is no catalog view to query. "
            "list_triggers() returns an empty list.",
        )

    def dataset_list_statement(self) -> "BigQueryDatasetListQueryStatement":
        """Return the ``INFORMATION_SCHEMA.SCHEMATA`` statement (project/region)."""
        config = getattr(self._backend, "config", None)
        location = getattr(config, "location", None) if config is not None else None
        return BigQueryDatasetListQueryStatement(
            self.dialect, catalog=self._project(), location=location
        )

    def table_options_statement(
        self, *, table_name: str, schema: Optional[str]
    ) -> "BigQueryTableOptionsQueryStatement":
        """Return the ``INFORMATION_SCHEMA.TABLE_OPTIONS`` statement."""
        catalog, dataset = self._dataset_scoped(schema)
        return BigQueryTableOptionsQueryStatement(
            self.dialect, table_name=table_name, schema=dataset, catalog=catalog
        )

    def partition_list_statement(
        self, *, table_name: str, schema: Optional[str]
    ) -> "BigQueryPartitionListQueryStatement":
        """Return the ``INFORMATION_SCHEMA.PARTITIONS`` statement.

        Unlike ``SCHEMATA`` this view takes a dataset qualifier only, never
        a region qualifier.
        https://cloud.google.com/bigquery/docs/information-schema-partitions
        """
        catalog, dataset = self._dataset_scoped(schema)
        return BigQueryPartitionListQueryStatement(
            self.dialect, table_name=table_name, schema=dataset, catalog=catalog
        )

    def partition_totals_statement(
        self, schema: Optional[str]
    ) -> "BigQueryPartitionListQueryStatement":
        """Return the same ``PARTITIONS`` question asked of the whole dataset.

        No table filter, so the answer is every partition row the dataset
        has. One read for the dataset is what lets the storage reducer fill
        a whole listing; asking the filtered question once per table would
        be one round trip per relation.
        """
        catalog, dataset = self._dataset_scoped(schema)
        return BigQueryPartitionListQueryStatement(
            self.dialect, table_name=None, schema=dataset, catalog=catalog
        )

    def parse_table_storage(
        self, tables: List[IntrospectionTableInfo], rows: List[Dict[str, Any]]
    ) -> List[IntrospectionTableInfo]:
        """Attribute the dataset's partition rows to the tables they sum to.

        ``PARTITIONS`` answers one row per partition; a table's stored bytes
        is the sum of its partitions' ``total_billable_bytes``, which lands
        on ``size_bytes`` -- the common minimum's total. A table with no
        partition rows (a view has none) keeps ``None``: not an object this
        engine stores bytes for, which is a different answer from zero.

        The split slots stay ``None`` for a reason that is BigQuery's shape
        rather than a gap: managed storage has no index side to separate,
        so there is nothing to attribute ``data_size_bytes`` or
        ``index_size_bytes`` to (``.claude/rules/introspection.md`` §5).
        Per-partition rows are already answered by the ``PARTITIONS``
        family; this reduction is only the common minimum.
        """
        billable_by_table: Dict[str, int] = {}
        for row in rows:
            table_name = row.get("table_name")
            total = _as_int(row.get("total_billable_bytes"))
            if table_name is None or total is None:
                continue
            billable_by_table[table_name] = billable_by_table.get(table_name, 0) + total
        for table in tables:
            table.size_bytes = billable_by_table.get(table.name)
        return tables

    # ------------------------------------------------------------------ #
    # Parsing
    # ------------------------------------------------------------------ #

    def parse_database_info(self, rows: List[Dict[str, Any]]) -> IntrospectionDatabaseInfo:
        row = rows[0] if rows else {}
        version = self._get_version()
        config = getattr(self._backend, "config", None)
        return IntrospectionDatabaseInfo(
            name=_row_get(row, "catalog_name") or self._project() or "",
            version=".".join(str(part) for part in version),
            version_tuple=tuple(version),
            vendor="BigQuery",
            collation=None,
            extra={
                "project": self._project(),
                "dataset": getattr(config, "dataset", None) if config else None,
                "location": getattr(config, "location", None) if config else None,
                "version_source": "backend feature level, not a server version",
            },
        )

    def parse_tables(
        self, rows: List[Dict[str, Any]], schema: Optional[str]
    ) -> List[IntrospectionTableInfo]:
        label = self._schema_label(schema)
        tables: List[IntrospectionTableInfo] = []
        for row in rows:
            raw_type = str(_row_get(row, "table_type") or "BASE TABLE").upper()
            tables.append(
                IntrospectionTableInfo(
                    name=_row_get(row, "table_name") or "",
                    schema=label,
                    table_type=_TABLE_TYPE_MAP.get(raw_type, TableType.BASE_TABLE),
                    create_time=_isoformat(_row_get(row, "creation_time")),
                    extra={
                        "bigquery_table_type": raw_type,
                        "is_insertable_into": _as_bool(_row_get(row, "is_insertable_into")),
                        "is_typed": _as_bool(_row_get(row, "is_typed")),
                        "ddl": _row_get(row, "ddl"),
                        "default_collation_name": _row_get(row, "default_collation_name"),
                    },
                )
            )
        return tables

    def parse_data_type(self, raw: str, column_name: str) -> Optional[Any]:
        """Read one catalog type string, degrading one column on failure.

        ``parsed_data_type`` is ``None`` for exactly one reason: the catalog
        string could not be read. A ``STRUCT<...>`` or ``RANGE<...>`` type is
        not a type name this dialect's parser accepts, so that column keeps
        its ``data_type`` string and the schema differ falls back to
        comparing strings; the rest of the table is unaffected.
        """
        from .type_parser import BigQueryTypeParser

        try:
            return BigQueryTypeParser(self.dialect).parse(raw)
        except Exception as exc:  # noqa: BLE001 -- see the docstring
            warnings.warn(
                f"BigQuery reported column {column_name!r} as {raw!r}, which "
                f"this backend's introspection type parser could not read "
                f"({type(exc).__name__}: {exc}). That column's "
                f"parsed_data_type is left unset; the rest of the table is "
                f"unaffected.",
                RuntimeWarning,
                stacklevel=3,
            )
            return None

    def parse_columns(
        self, rows: List[Dict[str, Any]], table_name: str, schema: str
    ) -> List[IntrospectionColumnInfo]:
        """Turn ``COLUMNS`` rows into column objects, keeping what was asked.

        The names the row carries are the names the question asked, and the
        difference matters for every name the narrower projection leaves out:
        read through ``_row_get``'s ``None`` default it would arrive as an
        answer of *no* rather than as no question, so a consumer would be told
        a column is not generated when the truth is that the endpoint never
        carried the fact. Each column therefore records what it was asked
        (``extra[COLUMNS_ASKED_KEY]``), and the slots for an unasked name say
        ``None`` instead of a value: ``is_generated`` in particular, whose
        ``False`` would be a claim.
        """
        label = self._schema_label(schema)
        columns: List[IntrospectionColumnInfo] = []
        for row in rows:
            asked = _asked_columns(row)
            if str(_row_get(row, "is_hidden") or "").strip().upper() == "YES":
                # Pseudo columns have a NULL ordinal_position and are not
                # declared schema; the catalog documents this explicitly.
                continue
            raw_type = _row_get(row, "data_type") or ""
            nullable_raw = str(_row_get(row, "is_nullable") or "").strip().upper()
            if nullable_raw == "YES":
                nullable = ColumnNullable.NULLABLE
            elif nullable_raw == "NO":
                nullable = ColumnNullable.NOT_NULL
            else:
                nullable = ColumnNullable.UNKNOWN
            # ``None`` when the question did not name it -- the endpoint was
            # not asked, which is not the same as an answer of "no".
            identity = (
                str(_row_get(row, "is_identity") or "").strip().upper() == "YES"
                if "is_identity" in asked
                else None
            )
            column_name = _row_get(row, "column_name") or ""
            columns.append(
                IntrospectionColumnInfo(
                    name=column_name,
                    table_name=table_name,
                    schema=label,
                    ordinal_position=_as_int(_row_get(row, "ordinal_position")) or 0,
                    data_type=str(raw_type).lower(),
                    data_type_full=str(raw_type) or None,
                    parsed_data_type=(
                        self.parse_data_type(str(raw_type), column_name) if raw_type else None
                    ),
                    nullable=nullable,
                    default_value=_row_get(row, "column_default"),
                    # BigQuery has no AUTO_INCREMENT/IDENTITY column flag in
                    # the core sense; identity columns are reported through
                    # the extra fields instead of claiming auto-increment.
                    is_auto_increment=False,
                    is_generated=(
                        str(_row_get(row, "is_generated") or "").strip().upper() == "ALWAYS"
                        if "is_generated" in asked
                        else None
                    ),
                    generated_expression=_row_get(row, "generation_expression"),
                    collation=_row_get(row, "collation_name"),
                    extra={
                        "is_stored": _as_bool(_row_get(row, "is_stored")),
                        "is_hidden": _as_bool(_row_get(row, "is_hidden")),
                        "is_system_defined": _as_bool(_row_get(row, "is_system_defined")),
                        "is_partitioning_column": _as_bool(_row_get(row, "is_partitioning_column")),
                        "clustering_ordinal_position": _as_int(
                            _row_get(row, "clustering_ordinal_position")
                        ),
                        "rounding_mode": _row_get(row, "rounding_mode"),
                        "is_identity": identity,
                        "identity_generation": _row_get(row, "identity_generation"),
                        "identity_start": _as_int(_row_get(row, "identity_start")),
                        "identity_increment": _as_int(_row_get(row, "identity_increment")),
                        # The documented spellings are identity_maximum /
                        # identity_minimum; a row carrying neither means an
                        # older or emulated catalog, which yields None.
                        "identity_maximum": _as_int(_row_get(row, "identity_maximum")),
                        "identity_minimum": _as_int(_row_get(row, "identity_minimum")),
                        "identity_cycle": _row_get(row, "identity_cycle"),
                        # Which of the documented names this row was asked:
                        # a name absent here was never asked, so its slot is
                        # "no answer" rather than a value the catalog gave.
                        COLUMNS_ASKED_KEY: asked,
                    },
                )
            )
        return columns

    def parse_column_data_profiles(
        self,
        rows: List[Dict[str, Any]],
        schema: str,
        table_name: str,
    ) -> List[ColumnDataProfile]:
        """Pivot the profile's single row back into one row per column.

        The statement projects every column's figures as one wide row -- that is
        what makes the profile one billed scan rather than one per column -- so
        the row is reshaped here into the per-column rows core's parser already
        knows how to read: ``column_name``, ``null_count``, ``distinct_count``,
        ``min_value``, ``max_value``, ``row_count`` and ``source``.

        Reshaping rather than re-implementing is deliberate. "``None`` means not
        measured", the derivation of ``null_fraction`` from a count and a row
        count, and the skipping of a row with no column name are one set of
        rules, and they live in core. A second parser here would be a second
        place for the two engines to disagree about what a missing figure means.

        Slots the formatter projected as ``NULL`` -- the distinct count and the
        bounds of a column whose declared type the aggregates cannot read --
        arrive as ``None`` and stay ``None``: their absence is a fact about the
        engine, not a zero it measured.
        """
        shaped: List[Dict[str, Any]] = []
        for row in rows or []:
            # The catalogue reports lower-case names and this formatter aliases
            # its slots in lower case; normalising keeps the parser independent
            # of whether a client folds identifiers.
            normalized = {str(key).lower(): value for key, value in row.items()}
            index = 1
            while f"c{index}_name" in normalized:
                prefix = f"c{index}_"
                shaped.append(
                    {
                        "column_name": normalized[prefix + "name"],
                        "null_count": normalized.get(prefix + "null_count"),
                        "distinct_count": normalized.get(prefix + "distinct_count"),
                        "min_value": normalized.get(prefix + "min"),
                        "max_value": normalized.get(prefix + "max"),
                        "row_count": normalized.get("row_count"),
                        "source": normalized.get("source"),
                    }
                )
                index += 1
        return super().parse_column_data_profiles(shaped, schema, table_name)

    def parse_indexes(
        self, rows: List[Dict[str, Any]], table_name: str, schema: str
    ) -> List[IndexInfo]:
        """Parse primary-key constraint rows into ``IndexInfo`` objects.

        BigQuery has no physical indexes. A primary key is reported the way
        the rest of the codebase understands keys, with the original
        ``constraint_type`` kept in ``extra``.
        """
        indexes: Dict[str, IndexInfo] = {}
        for row in rows:
            name = _row_get(row, "constraint_name") or ""
            if not name:
                continue
            if name not in indexes:
                constraint_type = str(_row_get(row, "constraint_type") or "PRIMARY KEY").upper()
                indexes[name] = IndexInfo(
                    name=name,
                    table_name=table_name,
                    schema=self._schema_label(schema),
                    is_unique=True,
                    is_primary=constraint_type == "PRIMARY KEY",
                    index_type=IndexType.UNKNOWN,
                    columns=[],
                    extra={"constraint_type": constraint_type},
                )
            column_name = _row_get(row, "column_name")
            if column_name:
                indexes[name].columns.append(
                    IndexColumnInfo(
                        name=column_name,
                        ordinal_position=_as_int(_row_get(row, "ordinal_position")) or 0,
                        is_descending=False,
                    )
                )
        return list(indexes.values())

    def parse_foreign_keys(
        self, rows: List[Dict[str, Any]], table_name: str, schema: str
    ) -> List[IntrospectionForeignKeyInfo]:
        """Always empty: the catalog cannot name the referenced relation."""
        del rows, table_name, schema
        return []

    def parse_views(self, rows: List[Dict[str, Any]], schema: str) -> List[IntrospectionViewInfo]:
        label = self._schema_label(schema)
        return [
            IntrospectionViewInfo(
                name=_row_get(row, "table_name") or "",
                schema=label,
                definition=_row_get(row, "view_definition"),
                check_option=_row_get(row, "check_option"),
                extra={
                    "use_standard_sql": _as_bool(_row_get(row, "use_standard_sql")),
                },
            )
            for row in rows
        ]

    def parse_view_info(
        self, rows: List[Dict[str, Any]], view_name: str, schema: str
    ) -> Optional[IntrospectionViewInfo]:
        if not rows:
            return None
        return self.parse_views(rows[:1], schema)[0]

    def parse_triggers(
        self, rows: List[Dict[str, Any]], schema: str
    ) -> List[IntrospectionTriggerInfo]:
        """Always empty: BigQuery has no triggers."""
        del rows, schema
        return []

    def parse_routines(
        self, rows: List[Dict[str, Any]], schema: Optional[str]
    ) -> List[BigQueryRoutineInfo]:
        """Parse ``ROUTINES`` rows into one record per routine.

        ``is_deterministic`` arrives as the catalog's ``YES``/``NO``/``NULL``
        and is read as ``True``/``False``/``None``; every other slot keeps
        the catalog's own spelling. ``specific_schema`` and
        ``routine_schema`` both name the dataset, so a row that carries
        neither falls back to the schema argument the question was scoped to.
        """
        label = self._schema_label(schema)
        return [
            BigQueryRoutineInfo(
                routine_name=_row_get(row, "routine_name") or "",
                routine_type=_row_get(row, "routine_type") or "",
                specific_catalog=_row_get(row, "specific_catalog"),
                specific_schema=_row_get(row, "specific_schema") or label,
                specific_name=_row_get(row, "specific_name"),
                routine_catalog=_row_get(row, "routine_catalog"),
                routine_schema=_row_get(row, "routine_schema") or label,
                data_type=_row_get(row, "data_type"),
                routine_body=_row_get(row, "routine_body"),
                routine_definition=_row_get(row, "routine_definition"),
                external_language=_row_get(row, "external_language"),
                is_deterministic=_as_bool(_row_get(row, "is_deterministic")),
                security_type=_row_get(row, "security_type"),
                created=_row_get(row, "created"),
                last_altered=_row_get(row, "last_altered"),
                connection=_row_get(row, "connection"),
                ddl=_row_get(row, "ddl"),
            )
            for row in rows
        ]

    def parse_datasets(self, rows: List[Dict[str, Any]]) -> List[BigQueryDatasetInfo]:
        return [
            BigQueryDatasetInfo(
                schema_name=_row_get(row, "schema_name") or "",
                catalog_name=_row_get(row, "catalog_name"),
                schema_owner=_row_get(row, "schema_owner"),
                creation_time=_row_get(row, "creation_time"),
                last_modified_time=_row_get(row, "last_modified_time"),
                location=_row_get(row, "location"),
                ddl=_row_get(row, "ddl"),
                default_collation_name=_row_get(row, "default_collation_name"),
                sync_status=_row_get(row, "sync_status"),
            )
            for row in rows
        ]

    def parse_table_options(self, rows: List[Dict[str, Any]]) -> List[BigQueryTableOptionInfo]:
        return [
            BigQueryTableOptionInfo(
                table_name=_row_get(row, "table_name") or "",
                option_name=_row_get(row, "option_name") or "",
                option_value=_row_get(row, "option_value"),
                option_type=_row_get(row, "option_type"),
                table_catalog=_row_get(row, "table_catalog"),
                table_schema=_row_get(row, "table_schema"),
            )
            for row in rows
        ]

    def parse_partitions(self, rows: List[Dict[str, Any]]) -> List[BigQueryPartitionInfo]:
        return [
            BigQueryPartitionInfo(
                table_name=_row_get(row, "table_name") or "",
                partition_id=_row_get(row, "partition_id"),
                table_catalog=_row_get(row, "table_catalog"),
                table_schema=_row_get(row, "table_schema"),
                total_rows=_as_int(_row_get(row, "total_rows")),
                total_logical_bytes=_as_int(_row_get(row, "total_logical_bytes")),
                total_billable_bytes=_as_int(_row_get(row, "total_billable_bytes")),
                last_modified_time=_row_get(row, "last_modified_time"),
                storage_tier=_row_get(row, "storage_tier"),
            )
            for row in rows
        ]

    # ------------------------------------------------------------------ #
    # Neutral object state: partitions, tables, constraints
    # ------------------------------------------------------------------ #

    def parse_partition_state(
        self,
        rows: List[Dict[str, Any]],
        table_name: str,
        schema: Optional[str],
        columns: List[IntrospectionColumnInfo],
        options: List[BigQueryTableOptionInfo],
        pseudo_columns: Tuple[str, ...] = (),
        include_stats: bool = False,
    ) -> PartitionState:
        """Turn the three catalog answers into the neutral partition state.

        ``PARTITIONS`` alone cannot answer "is this table partitioned":
        an unpartitioned table answers exactly one row whose
        ``partition_id`` is ``NULL``, which is the catalog saying *no
        partitions*, not a partition named NULL. That row is therefore
        dropped and contributes no bound -- a table with nothing else
        indicating partitioning answers an empty :class:`PartitionState`
        whose ``scheme`` is ``None``, core's single neutral answer for
        "not partitioned".

        The other two answers are what recognise a partitioned table that
        answers no partition rows yet: ``COLUMNS`` names the partitioning
        column (or, for ingestion-time partitioning, the pseudo columns the
        raw answer carries), and ``TABLE_OPTIONS`` carries
        ``partition_expiration_days`` / ``require_partition_filter``, which
        only a partitioned table can set.

        BigQuery partitions by intervals of a column's value or of ingestion
        time, so every partitioned table answers
        :attr:`PartitionScheme.RANGE`; ``key_columns`` names the partitioning
        column and ``key_expression`` the pseudo column for ingestion-time
        partitioning. ``PARTITIONS`` reports no explicit range end, so a
        bound's identity -- the partition's start -- is carried in ``name``
        and ``upper``/``values`` stay empty.

        ``include_stats`` fills ``row_count`` and ``size_bytes`` from
        ``total_rows``/``total_billable_bytes``; when it is false those
        slots stay ``None`` because nobody asked, even though the view's
        row already carried the figures. The finer per-partition facts
        (logical bytes, storage tier, last modified) stay on
        :meth:`parse_partitions`, BigQuery's own shape.

        Args:
            rows: The ``PARTITIONS`` rows for one table.
            table_name: The table the rows were asked about.
            schema: The dataset, or a ``project.dataset`` pair.
            columns: The parsed ``COLUMNS`` answer (pseudo columns excluded).
            options: The parsed ``TABLE_OPTIONS`` answer.
            pseudo_columns: The ingestion-time pseudo columns the raw
                ``COLUMNS`` answer carried, if any.
            include_stats: Whether to fill the per-partition figures.

        Returns:
            The partition state; an empty one (``scheme`` ``None``) when the
            table is not partitioned.
        """
        label = self._schema_label(schema)
        partitioning = self._partitioning_columns(columns)
        clustering = self._clustering_columns(columns)
        values = _option_values(options)

        ingestion_time = bool(pseudo_columns) and not partitioning
        has_bounds = any(_row_get(row, "partition_id") is not None for row in rows)
        has_options = any(name in values for name in _PARTITION_OPTIONS)
        if not (has_bounds or has_options or partitioning or ingestion_time):
            return PartitionState()

        bounds: List[PartitionBound] = []
        seen = set()
        for row in rows:
            partition_id = _row_get(row, "partition_id")
            if partition_id is None:
                # An unpartitioned table's single row: "no partitions", not
                # a partition whose identity is NULL.
                continue
            name = str(partition_id)
            if name in seen:
                continue
            seen.add(name)
            bounds.append(
                PartitionBound(
                    name=name,
                    row_count=_as_int(_row_get(row, "total_rows")) if include_stats else None,
                    size_bytes=(
                        _as_int(_row_get(row, "total_billable_bytes")) if include_stats else None
                    ),
                )
            )

        if partitioning:
            key_expression = ", ".join(partitioning)
        elif ingestion_time:
            key_expression = pseudo_columns[0]
        else:
            key_expression = ""

        return PartitionState(
            scheme=PartitionScheme.RANGE,
            key_expression=key_expression,
            key_columns=tuple(partitioning),
            # BigQuery has no DEFAULT partition. ``__NULL__`` is the partition
            # holding rows whose key is NULL, which is a bound like any other.
            has_default=False,
            auto_extend=False,
            bounds=tuple(bounds),
            raw={
                "require_partition_filter": _as_option_bool(values.get("require_partition_filter")),
                "partition_expiration_days": _as_int(values.get("partition_expiration_days")),
                "partitioning_columns": partitioning,
                "clustering_columns": clustering,
                "ingestion_time_partitioned": ingestion_time,
                "pseudo_columns": list(pseudo_columns),
                "partition_ids": [bound.name for bound in bounds],
                "table_name": table_name,
                "table_schema": label,
            },
        )

    def parse_table_state(
        self,
        table: IntrospectionTableInfo,
        options: List[BigQueryTableOptionInfo],
        partitioning: PartitionState = _EMPTY_PARTITION_STATE,
    ) -> TableState:
        """Turn a parsed table and its options into the neutral table state.

        ``kind`` is ``regular`` / ``view`` / ``materialized_view`` /
        ``external`` (BigQuery has no temporary, unlogged or transient
        tables in this view); ``CLONE`` and ``SNAPSHOT`` keep their catalog
        spelling in ``traits`` because they are ordinary tables that remember
        their source. A spelling this backend does not know keeps the
        catalog's own word in ``kind`` rather than being folded away.

        The table's storage options are its ``TABLE_OPTIONS`` rows: there is
        no engine, charset or tablespace to report (managed storage has no
        such setting), ``compression`` is the external-table format option
        when one was set, and the table's default collation comes from
        ``TABLES.default_collation_name``. ``comment`` is the ``description``
        option. ``raw`` keeps the option values as the catalog spelled them.

        Args:
            table: The parsed row this state describes.
            options: The parsed ``TABLE_OPTIONS`` rows for the same table.
            partitioning: The neutral partition state. When the caller did not
                ask, an empty :class:`PartitionState` (``scheme`` ``None``)
                stands for "not partitioned"; ``None`` is never an answer, and
                ``TableState.partitioning`` is always a ``PartitionState``.
        """
        raw_type = str(table.extra.get("bigquery_table_type") or "").upper()
        kind, traits = _TABLE_STATE_KINDS.get(raw_type, (raw_type.lower(), ()))
        values = _option_values(options)
        return TableState(
            name=table.name,
            schema=table.schema or None,
            kind=kind,
            traits=traits,
            storage=StorageOptionsState(
                engine=None,
                charset=None,
                collation=table.extra.get("default_collation_name"),
                compression=values.get("compression"),
                tablespace=None,
                raw=values,
            ),
            comment=values.get("description"),
            partitioning=partitioning,
            raw={
                "bigquery_table_type": raw_type,
                "create_time": table.create_time,
                "is_insertable_into": table.extra.get("is_insertable_into"),
                "is_typed": table.extra.get("is_typed"),
                "ddl": table.extra.get("ddl"),
            },
        )

    def parse_constraint_states(
        self, rows: List[Dict[str, Any]], table_name: str, schema: str
    ) -> List[ConstraintState]:
        """Turn ``TABLE_CONSTRAINTS``/``KEY_COLUMN_USAGE`` rows into states.

        The same catalog question that answers the primary key answers every
        declared constraint: ``TABLE_CONSTRAINTS`` names them and
        ``KEY_COLUMN_USAGE`` supplies their columns in order. BigQuery
        **does not enforce** primary and foreign key constraints -- they
        are declarations for tools and query optimisers, not checks the
        engine runs -- so every state answers ``enforced=False`` and
        ``validated=False``: nothing validated the existing rows and nothing
        will validate the next ones.

        ``kind`` is ``primary_key`` or ``foreign_key`` for the two documented
        ``constraint_type`` spellings, and the columns are kept in ``raw``
        because :class:`ConstraintState` is the common minimum and has no
        column slot.

        https://cloud.google.com/bigquery/docs/information-schema-table-constraints
        https://cloud.google.com/bigquery/docs/information-schema-key-column-usage
        """
        label = self._schema_label(schema)
        gathered: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            name = _row_get(row, "constraint_name") or ""
            if not name:
                continue
            constraint_type = str(_row_get(row, "constraint_type") or "").upper()
            entry = gathered.setdefault(
                name,
                {
                    "kind": {
                        "PRIMARY KEY": "primary_key",
                        "FOREIGN KEY": "foreign_key",
                    }.get(constraint_type, constraint_type.lower().replace(" ", "_")),
                    "constraint_type": constraint_type,
                    "columns": [],
                },
            )
            column_name = _row_get(row, "column_name")
            if column_name:
                position = _as_int(_row_get(row, "ordinal_position"))
                entry["columns"].append(
                    (position if position is not None else len(entry["columns"]) + 1, column_name)
                )
        states: List[ConstraintState] = []
        for name, entry in gathered.items():
            ordered = [column for _position, column in sorted(entry["columns"])]
            states.append(
                ConstraintState(
                    name=name,
                    table=table_name,
                    kind=entry["kind"],
                    schema=label,
                    validated=False,
                    enforced=False,
                    raw={
                        "constraint_type": entry["constraint_type"],
                        "columns": ordered,
                    },
                )
            )
        return states

    # ------------------------------------------------------------------ #
    # Column extraction shared by the storage-shape question
    # ------------------------------------------------------------------ #

    def _partitioning_columns(self, columns: List[IntrospectionColumnInfo]) -> List[str]:
        """The columns the catalog marks as partitioning columns.

        ``COLUMNS.is_partitioning_column`` answers ``YES`` for them; there
        is no ordering to respect, so column order is the row order.
        """
        return [
            column.name for column in columns if column.extra.get("is_partitioning_column") is True
        ]

    def _clustering_columns(self, columns: List[IntrospectionColumnInfo]) -> List[str]:
        """The clustering columns, in clustering order.

        ``COLUMNS.clustering_ordinal_position`` is the 1-indexed offset of
        the column within the table's clustering columns, so the list is
        built by position rather than by the order the rows arrived in.
        """
        positioned = [
            (column.extra["clustering_ordinal_position"], column.name)
            for column in columns
            if _as_int(column.extra.get("clustering_ordinal_position")) is not None
        ]
        return [name for _position, name in sorted(positioned, key=lambda item: item[0])]


class BigQueryIntrospector(BigQueryIntrospectorMixin, AbstractIntrospector):
    """Synchronous BigQuery introspector.

    Access it through ``backend.introspector``::

        tables = backend.introspector.list_tables()
        columns = backend.introspector.list_columns("orders")
        datasets = backend.introspector.list_datasets()
    """

    def __init__(
        self,
        backend: Any,
        executor: IntrospectorExecutor,
        cache: Optional[IntrospectionCache] = None,
    ) -> None:
        super().__init__(backend, executor, cache)
        # The full documented list is what a real BigQuery answers, so that is
        # what this manager asks until an endpoint proves otherwise.
        self.columns_projection: Tuple[str, ...] = COLUMNS_PROJECTION_FULL

    def list_columns(
        self, table_name: str, schema: Optional[str] = None
    ) -> List[IntrospectionColumnInfo]:
        """List a table's columns, parsed from the answer :meth:`column_rows` keeps.

        The cache key is core's, so a caller reaching this method and one
        reaching it through the base class share an answer. The raw rows
        behind it are cached separately, which is what lets the partition
        question read the pseudo columns this parser drops without asking
        ``COLUMNS`` a second time.
        """
        target = schema if schema is not None else self.default_schema
        key = self._cache.key(IntrospectionScope.COLUMN, table_name, schema=schema)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        result = self.parse_columns(self.column_rows(table_name, schema), table_name, target)
        self._cache.set(key, result)
        return result

    def column_rows(self, table_name: str, schema: Optional[str] = None) -> List[Dict[str, Any]]:
        """The raw ``INFORMATION_SCHEMA.COLUMNS`` answer, asked once per table.

        The whole documented column list is asked first, because that is what
        BigQuery answers and it is the only way to read the families the
        narrower list leaves out -- whether a column is generated, what a
        computed one is computed from, what an identity column's bounds are,
        which column the table clusters by. There is no version or capability
        question in ``INFORMATION_SCHEMA`` that says whether an endpoint
        carries those names -- BigQuery reports no server release at all, and
        this backend's version is a feature level rather than a negotiated
        one -- so the only question that can be answered is the ``COLUMNS``
        question itself: ask, and if the endpoint fails the question because
        it lacks a name, ask the narrow list instead and remember that this
        endpoint answers that one. One failed question per manager, not one
        per table, and a real server never pays for the fallback at all
        because the first question succeeds.

        The rows are cached rather than re-parsed: two families read this
        one answer -- the column listing, which parses it into columns, and
        the partition question, which reads the hidden pseudo columns the
        parser drops -- and each of them must not ask it again. The cache key
        carries the table scope, so invalidating a table drops both this
        answer and the parsed columns built from it.
        """
        key = self._cache.key(IntrospectionScope.COLUMN, table_name, schema=schema, extra="rows")
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        sql, params = self.column_info_statement(
            table_name=table_name, schema=schema, projection=self.columns_projection
        ).to_sql()
        try:
            rows = self._executor.execute(sql, params)
        except DatabaseError as first_error:
            if self.columns_projection == _EMULATOR_COLUMNS_PROJECTION:
                raise
            self.columns_projection = _EMULATOR_COLUMNS_PROJECTION
            sql, params = self.column_info_statement(
                table_name=table_name,
                schema=schema,
                projection=self.columns_projection,
            ).to_sql()
            try:
                rows = self._executor.execute(sql, params)
            except DatabaseError:
                # The narrow list is a subset of the one that just failed, so
                # it cannot fail where that one succeeded: what failed is the
                # table, the dataset or the connection, and the first error is
                # the one that names it.
                raise first_error from None
        self._cache.set(key, rows)
        return rows

    def get_table_info(
        self, table_name: str, schema: Optional[str] = None
    ) -> Optional[IntrospectionTableInfo]:
        """Return a table with its columns and primary key.

        The table object is copied before it is populated: the instance in
        the ``list_tables()`` cache must not gain columns because one caller
        asked for details about it.
        """
        key = self._cache.key(IntrospectionScope.TABLE, table_name, schema=schema)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        table = next((t for t in self.list_tables(schema) if t.name == table_name), None)
        if table is None:
            return None
        table = copy.copy(table)
        table.columns = self.list_columns(table_name, schema)
        table.indexes = self.list_indexes(table_name, schema)
        table.foreign_keys = self.list_foreign_keys(table_name, schema)
        self._cache.set(key, table)
        return table

    def list_foreign_keys(
        self, table_name: str, schema: Optional[str] = None
    ) -> List[IntrospectionForeignKeyInfo]:
        """Return an empty list; see the module docstring."""
        del table_name, schema
        return []

    def list_triggers(
        self, table_name: Optional[str] = None, schema: Optional[str] = None
    ) -> List[IntrospectionTriggerInfo]:
        """Return an empty list; BigQuery has no triggers."""
        del table_name, schema
        return []

    def list_column_data_profiles(
        self,
        table_name: str,
        schema: Optional[str] = None,
    ) -> List[ColumnDataProfile]:
        """Profile one table's columns from its rows. **This scans the table.**

        The answer is exact, and it is the most expensive question this backend
        can be asked: BigQuery bills bytes read, so the cost is proportional to
        the table rather than to its schema. One scan answers every column --
        the statement projects all of them in one ``SELECT`` -- but a caller
        profiling a large table is choosing to read all of it, twice if the
        query is run again for the same table once the cache expires.

        The column catalogue is read first, and not only for the names: an
        aggregating dialect needs the names to pivot its aggregates, and this
        one also needs each column's declared type to know whether the engine
        will compute a distinct count and bounds for it at all. That is a
        metadata read, priced in bytes of ``INFORMATION_SCHEMA`` rather than of
        the table, so it is cheap beside what follows.

        The cache key is core's, so a caller that reaches this method and one
        that reaches it through the base class share an answer and a bill.
        """
        key = self._cache.key(IntrospectionScope.COLUMN, table_name, "data_profile", schema=schema)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        target = schema if schema is not None else self.default_schema
        columns = self.list_columns(table_name, target)
        sql, params = self.dialect.profile_statement(
            table_name=table_name, schema=target, columns=columns
        ).to_sql()
        result = self.parse_column_data_profiles(
            self._executor.execute(sql, params),
            target,
            table_name,
        )
        self._cache.set(key, result)
        return result

    # ------------------------------------------------------------------ #
    # BigQuery-specific questions
    # ------------------------------------------------------------------ #

    def list_datasets(self) -> List[BigQueryDatasetInfo]:
        """List the project's datasets from ``INFORMATION_SCHEMA.SCHEMATA``."""
        key = self._cache.key(IntrospectionScope.SCHEMA, "*", extra="datasets")
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        sql, params = self.dataset_list_statement().to_sql()
        result = self.parse_datasets(self._executor.execute(sql, params))
        self._cache.set(key, result)
        return result

    def list_routines(self, schema: Optional[str] = None) -> List[BigQueryRoutineInfo]:
        """List a dataset's routines from ``INFORMATION_SCHEMA.ROUTINES``.

        One row per persistent user-defined function, aggregate function,
        table function or stored procedure. The cache key carries the schema
        the question was scoped to, so two datasets do not answer each other.
        """
        key = self._cache.key(
            IntrospectionScope.SCHEMA,
            schema or self.default_schema,
            extra="routines",
        )
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        sql, params = self.routine_list_statement(schema=schema).to_sql()
        result = self.parse_routines(self._executor.execute(sql, params), schema)
        self._cache.set(key, result)
        return result

    def get_routine_info(
        self, routine_name: str, schema: Optional[str] = None
    ) -> Optional[BigQueryRoutineInfo]:
        """Return one named routine, or ``None`` when the dataset has none.

        The question is the same ``ROUTINES`` read as :meth:`list_routines`,
        filtered by ``routine_name``. A missing name is not an error here:
        the caller decides whether "no such routine" is a failure.
        """
        key = self._cache.key(
            IntrospectionScope.SCHEMA,
            routine_name,
            schema=schema,
            extra="routine",
        )
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        sql, params = self.routine_list_statement(schema=schema, routine_name=routine_name).to_sql()
        rows = self.parse_routines(self._executor.execute(sql, params), schema)
        if not rows:
            return None
        self._cache.set(key, rows[0])
        return rows[0]

    def list_table_options(
        self, table_name: str, schema: Optional[str] = None
    ) -> List[BigQueryTableOptionInfo]:
        """List one table's options from ``INFORMATION_SCHEMA.TABLE_OPTIONS``."""
        key = self._cache.key(
            IntrospectionScope.TABLE, table_name, schema=schema, extra="table_options"
        )
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        sql, params = self.table_options_statement(table_name=table_name, schema=schema).to_sql()
        result = self.parse_table_options(self._executor.execute(sql, params))
        self._cache.set(key, result)
        return result

    def collect_table_storage(self, schema: Optional[str] = None) -> List[Dict[str, Any]]:
        """The dataset's partition rows, the storage reducer's input.

        One read for the whole dataset, gated on the dialect's
        ``supports_table_storage_introspection``: a build that cannot answer
        the family answers an empty list rather than an error, and the
        reducer keeps every slot ``None``.
        """
        if not self.dialect.supports_table_storage_introspection():
            return []
        sql, params = self.partition_totals_statement(schema).to_sql()
        return self._executor.execute(sql, params)

    def list_tables(
        self,
        schema: Optional[str] = None,
        include_system: bool = False,
        table_type: Optional[str] = None,
    ) -> List[IntrospectionTableInfo]:
        """List tables with ``size_bytes`` filled from the partitions.

        The base flow asks one question and parses its rows; this adds the
        dataset-scoped partition read beside it and reduces it, so a caller
        of the ordinary listing sees each table's stored bytes on the common
        minimum instead of only through the ``PARTITIONS`` family.
        """
        key = self._cache.key(
            IntrospectionScope.TABLE,
            schema=schema,
            extra=f"{include_system}:{table_type}",
        )
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        sql, params = self.table_list_statement(
            schema=schema,
            include_system=include_system,
            include_views=True,
            table_type=table_type,
        ).to_sql()
        tables = self.parse_tables(self._executor.execute(sql, params), schema)
        tables = self.parse_table_storage(tables, self.collect_table_storage(schema))
        self._cache.set(key, tables)
        return tables

    def get_table_state(self, table_name: str, schema: Optional[str] = None) -> TableState:
        """Return the table's kind, storage options, comment and partitioning.

        Composed from the three catalog answers that each carry part of it --
        ``TABLES`` for the kind and collation, ``TABLE_OPTIONS`` for the
        description and storage options, and :meth:`get_partition_state` for
        the scheme -- all of which are cached on their own, so a second call
        for the same table asks the database nothing new.

        A table the dataset does not hold raises
        :class:`~...errors.ObjectNotFoundError` rather than answering a
        state built from no row: ``TableState`` has no "unknown" member, and
        an empty one would read as a table that exists and has no facts.

        Args:
            table_name: The table to describe.
            schema: The dataset, or a ``project.dataset`` pair; ``None`` for
                the connection default.

        Raises:
            ObjectNotFoundError: When the dataset holds no table of that name.
        """
        key = self._cache.key(IntrospectionScope.TABLE, table_name, schema=schema, extra="state")
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        table = next((t for t in self.list_tables(schema) if t.name == table_name), None)
        if table is None:
            raise ObjectNotFoundError("table", table_name, self._schema_label(schema))
        state = self.parse_table_state(
            table,
            self.list_table_options(table_name, schema),
            self.get_partition_state(table_name, schema),
        )
        self._cache.set(key, state)
        return state

    def get_partition_state(
        self,
        table_name: str,
        schema: Optional[str] = None,
        include_stats: bool = False,
    ) -> PartitionState:
        """Return the table's partition scheme and bounds, never ``None``.

        An unpartitioned table answers an empty :class:`PartitionState`
        whose ``scheme`` is ``None`` -- the single neutral answer for "this
        table is not partitioned", for every backend. BigQuery answers one
        ``PARTITIONS`` row whose ``partition_id`` is ``NULL`` for such a
        table; that row is the catalog saying *no partitions*, so it is
        dropped rather than turned into a bound named NULL. See
        :meth:`parse_partition_state` for how column-, range- and
        ingestion-time partitioning are told apart.

        Three catalog answers are read: the table's ``PARTITIONS`` rows, its
        raw ``COLUMNS`` answer (the parsed column list drops the hidden
        pseudo columns that identify ingestion-time partitioning, and the
        same read names the partitioning and clustering columns), and its
        ``TABLE_OPTIONS`` (the partition options and
        ``require_partition_filter``). An answer that carries no partition
        signal is checked against the table listing, so a table that does
        not exist raises rather than being reported as unpartitioned.

        ``include_stats`` fills each bound's row count and size from the
        ``PARTITIONS`` row; leaving it false keeps those slots ``None``
        rather than presenting optional figures nobody asked for. No extra
        statistics question is ever run.

        Args:
            table_name: The table whose partitioning is wanted.
            schema: The dataset, or a ``project.dataset`` pair.
            include_stats: Whether to fill each bound's row count and size.

        Raises:
            ObjectNotFoundError: When the dataset holds no table of that name.
        """
        key = self._cache.key(
            IntrospectionScope.PARTITION,
            table_name,
            schema=schema,
            extra=f"partition_state:{include_stats}",
        )
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        raw_columns = self.column_rows(table_name, schema)
        columns = self.list_columns(table_name, schema)
        options = self.list_table_options(table_name, schema)
        state = self.parse_partition_state(
            self.partition_rows(table_name, schema),
            table_name,
            schema,
            columns,
            options,
            _pseudo_partition_columns(raw_columns),
            include_stats=include_stats,
        )
        if state.scheme is None and not any(t.name == table_name for t in self.list_tables(schema)):
            raise ObjectNotFoundError("table", table_name, self._schema_label(schema))
        self._cache.set(key, state)
        return state

    def list_constraint_states(
        self, table_name: str, schema: Optional[str] = None
    ) -> List[ConstraintState]:
        """Return every constraint the table declares, with its enforcement.

        The same ``TABLE_CONSTRAINTS``/``KEY_COLUMN_USAGE`` question that
        answers the primary key answers the whole constraint family; a
        constraint is a declaration rather than an index, which is why this
        is here and ``list_index_states`` stays core's refusal. BigQuery
        does not enforce primary or foreign keys, so every state answers
        ``enforced=False`` and ``validated=False`` -- see
        :meth:`parse_constraint_states`.
        """
        key = self._cache.key(
            IntrospectionScope.TABLE, table_name, schema=schema, extra="constraint_states"
        )
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        sql, params = self.index_info_statement(table_name=table_name, schema=schema).to_sql()
        result = self.parse_constraint_states(
            self._executor.execute(sql, params), table_name, schema or self.default_schema
        )
        self._cache.set(key, result)
        return result

    def list_schemas(self) -> List[str]:
        """Return the datasets the configured project exposes, by name.

        BigQuery's namespace level is the dataset, and
        ``INFORMATION_SCHEMA.SCHEMATA`` is the one view that answers it
        (project-wide, or for one region when the connection names one).
        The names are the catalog's own spelling.
        """
        return [dataset.schema_name for dataset in self.list_datasets()]

    def item_exists(
        self,
        kind: ItemKind,
        name: str,
        schema: Optional[str] = None,
    ) -> bool:
        """Whether a shared object of this kind exists, where BigQuery has one.

        The catalogue answers three of the kinds:

        * ``SCHEMA`` -- a dataset of the configured project (``SCHEMATA``);
        * ``TABLE`` -- a table or view in the dataset (``TABLES``);
        * ``FUNCTION`` -- a routine that is a scalar, aggregate or table
          function (``ROUTINES``). A stored procedure is a different kind
          and answers ``False``: BigQuery's routines share one name
          namespace, but ``ItemKind`` has no procedure member, so a plan
          that needs to know whether the *name* is taken must read the
          routine listing itself.

        BigQuery has no types, domains, sequences, extensions, tablespaces,
        partition functions/schemes or full-text catalogues, and no
        ``INFORMATION_SCHEMA`` view answers those families, so the remaining
        kinds stay core's refusal rather than a ``False`` that would claim
        the engine was asked. A name qualified with a project or dataset
        (a dot) is refused for the same reason: the listings this manager
        asks are scoped to one dataset.

        Args:
            kind: The kind of shared object.
            name: The object's name.
            schema: The dataset, for the kinds that are dataset-scoped.
        """
        if "." in name:
            return super().item_exists(kind, name, schema)
        if kind == ItemKind.SCHEMA:
            return name in {dataset.schema_name for dataset in self.list_datasets()}
        if kind == ItemKind.TABLE:
            return any(table.name == name for table in self.list_tables(schema))
        if kind == ItemKind.FUNCTION:
            return any(
                routine.routine_name == name
                and str(routine.routine_type).upper() in _FUNCTION_ROUTINE_TYPES
                for routine in self.list_routines(schema)
            )
        return super().item_exists(kind, name, schema)

    def partition_rows(self, table_name: str, schema: Optional[str] = None) -> List[Dict[str, Any]]:
        """The table's raw ``INFORMATION_SCHEMA.PARTITIONS`` answer.

        One question, two answers built from it: the neutral partition state
        (:meth:`get_partition_state`) reads the rows for its bounds, and the
        BigQuery-specific storage shape (:meth:`get_table_storage_info`)
        parses the same rows into :class:`BigQueryPartitionInfo` values with
        the per-partition bytes and tiers the common minimum has no slot for.
        Caching the rows rather than one of the two shapes keeps the second
        caller from issuing the same SQL again.
        """
        key = self._cache.key(
            IntrospectionScope.PARTITION, table_name, schema=schema, extra="partition_rows"
        )
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        sql, params = self.partition_list_statement(table_name=table_name, schema=schema).to_sql()
        rows = self._executor.execute(sql, params)
        self._cache.set(key, rows)
        return rows

    def get_table_storage_info(
        self, table_name: str, schema: Optional[str] = None
    ) -> BigQueryTableStorageInfo:
        """Return how one table is stored, from the three views that know.

        This is BigQuery's own, finer answer: the ``TABLE_OPTIONS`` rows, one
        :class:`BigQueryPartitionInfo` per ``PARTITIONS`` row (with that
        partition's logical and billable bytes, storage tier and last
        modified time), and the partitioning and clustering columns
        ``COLUMNS`` names. The neutral answers -- "is this partitioned" and
        "what are the bounds" -- are :meth:`get_partition_state` and
        :meth:`get_table_state`; this shape exists because those per-partition
        figures have no slot in the common minimum.

        An unpartitioned table still answers the one ``PARTITIONS`` row whose
        ``partition_id`` is ``NULL`` here: this is the catalog's answer kept
        whole. The neutral state is where that row becomes ``scheme=None``.
        """
        options = self.list_table_options(table_name, schema)
        partitions = self.parse_partitions(self.partition_rows(table_name, schema))
        columns = self.list_columns(table_name, schema)
        return BigQueryTableStorageInfo(
            table_name=table_name,
            schema=self._schema_label(schema),
            options=options,
            partitions=partitions,
            partitioning_columns=self._partitioning_columns(columns),
            clustering_columns=self._clustering_columns(columns),
        )


class AsyncBigQueryIntrospector(BigQueryIntrospectorMixin, AsyncAbstractIntrospector):
    """Asynchronous BigQuery introspector.

    Method names match the sync class; every I/O method is ``async``::

        tables = await backend.introspector.list_tables()
        columns = await backend.introspector.list_columns("orders")
        datasets = await backend.introspector.list_datasets()
    """

    def __init__(
        self,
        backend: Any,
        executor: AsyncIntrospectorExecutor,
        cache: Optional[IntrospectionCache] = None,
    ) -> None:
        super().__init__(backend, executor, cache)
        # The full documented list is what a real BigQuery answers, so that is
        # what this manager asks until an endpoint proves otherwise.
        self.columns_projection: Tuple[str, ...] = COLUMNS_PROJECTION_FULL

    async def list_columns(
        self, table_name: str, schema: Optional[str] = None
    ) -> List[IntrospectionColumnInfo]:
        """List a table's columns, parsed from the answer :meth:`column_rows` keeps.

        The async twin of :meth:`BigQueryIntrospector.list_columns`, with the
        same cache keys: the parsed columns under core's key and the raw rows
        beside them under this manager's ``rows`` namespace, so the column
        listing and the partition question share one ``COLUMNS`` read.
        """
        target = schema if schema is not None else self.default_schema
        key = self._cache.key(IntrospectionScope.COLUMN, table_name, schema=schema)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        result = self.parse_columns(await self.column_rows(table_name, schema), table_name, target)
        self._cache.set(key, result)
        return result

    async def column_rows(
        self, table_name: str, schema: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """The raw ``INFORMATION_SCHEMA.COLUMNS`` answer (async).

        The async twin of :meth:`BigQueryIntrospector.column_rows`: same
        projection fallback (the whole documented list first, the narrower
        one only after the endpoint has failed to answer it, remembered for
        the rest of this manager's life) and the same cache key, so the two
        managers cannot disagree about which projection this endpoint
        answers or ask it twice for one table.
        """
        key = self._cache.key(IntrospectionScope.COLUMN, table_name, schema=schema, extra="rows")
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        sql, params = self.column_info_statement(
            table_name=table_name, schema=schema, projection=self.columns_projection
        ).to_sql()
        try:
            rows = await self._executor.execute(sql, params)
        except DatabaseError as first_error:
            if self.columns_projection == _EMULATOR_COLUMNS_PROJECTION:
                raise
            self.columns_projection = _EMULATOR_COLUMNS_PROJECTION
            sql, params = self.column_info_statement(
                table_name=table_name,
                schema=schema,
                projection=self.columns_projection,
            ).to_sql()
            try:
                rows = await self._executor.execute(sql, params)
            except DatabaseError:
                raise first_error from None
        self._cache.set(key, rows)
        return rows

    async def get_table_info(
        self, table_name: str, schema: Optional[str] = None
    ) -> Optional[IntrospectionTableInfo]:
        """Return a table with its columns and primary key (async)."""
        key = self._cache.key(IntrospectionScope.TABLE, table_name, schema=schema)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        table = next((t for t in await self.list_tables(schema) if t.name == table_name), None)
        if table is None:
            return None
        table = copy.copy(table)
        table.columns = await self.list_columns(table_name, schema)
        table.indexes = await self.list_indexes(table_name, schema)
        table.foreign_keys = await self.list_foreign_keys(table_name, schema)
        self._cache.set(key, table)
        return table

    async def list_foreign_keys(
        self, table_name: str, schema: Optional[str] = None
    ) -> List[IntrospectionForeignKeyInfo]:
        """Return an empty list; see the module docstring."""
        del table_name, schema
        return []

    async def list_triggers(
        self, table_name: Optional[str] = None, schema: Optional[str] = None
    ) -> List[IntrospectionTriggerInfo]:
        """Return an empty list; BigQuery has no triggers."""
        del table_name, schema
        return []

    async def list_column_data_profiles(
        self,
        table_name: str,
        schema: Optional[str] = None,
    ) -> List[ColumnDataProfile]:
        """Profile one table's columns from its rows (async).

        The async twin of :meth:`BigQueryIntrospector.list_column_data_profiles`:
        same catalogue read, same one-scan statement, same cache key, so the two
        cannot disagree about which columns carry figures or about what a billed
        scan buys.
        """
        key = self._cache.key(IntrospectionScope.COLUMN, table_name, "data_profile", schema=schema)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        target = schema if schema is not None else self.default_schema
        columns = await self.list_columns(table_name, target)
        sql, params = self.dialect.profile_statement(
            table_name=table_name, schema=target, columns=columns
        ).to_sql()
        result = self.parse_column_data_profiles(
            await self._executor.execute(sql, params),
            target,
            table_name,
        )
        self._cache.set(key, result)
        return result

    # ------------------------------------------------------------------ #
    # BigQuery-specific questions
    # ------------------------------------------------------------------ #

    async def list_datasets(self) -> List[BigQueryDatasetInfo]:
        """List the project's datasets (async)."""
        key = self._cache.key(IntrospectionScope.SCHEMA, "*", extra="datasets")
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        sql, params = self.dataset_list_statement().to_sql()
        result = self.parse_datasets(await self._executor.execute(sql, params))
        self._cache.set(key, result)
        return result

    async def list_routines(self, schema: Optional[str] = None) -> List[BigQueryRoutineInfo]:
        """List a dataset's routines (async).

        The async twin of :meth:`BigQueryIntrospector.list_routines`: same
        statement, same parser and same cache key.
        """
        key = self._cache.key(
            IntrospectionScope.SCHEMA,
            schema or self.default_schema,
            extra="routines",
        )
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        sql, params = self.routine_list_statement(schema=schema).to_sql()
        result = self.parse_routines(await self._executor.execute(sql, params), schema)
        self._cache.set(key, result)
        return result

    async def get_routine_info(
        self, routine_name: str, schema: Optional[str] = None
    ) -> Optional[BigQueryRoutineInfo]:
        """Return one named routine, or ``None`` (async).

        The async twin of :meth:`BigQueryIntrospector.get_routine_info`.
        """
        key = self._cache.key(
            IntrospectionScope.SCHEMA,
            routine_name,
            schema=schema,
            extra="routine",
        )
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        sql, params = self.routine_list_statement(schema=schema, routine_name=routine_name).to_sql()
        rows = self.parse_routines(await self._executor.execute(sql, params), schema)
        if not rows:
            return None
        self._cache.set(key, rows[0])
        return rows[0]

    async def list_table_options(
        self, table_name: str, schema: Optional[str] = None
    ) -> List[BigQueryTableOptionInfo]:
        """List one table's options (async)."""
        key = self._cache.key(
            IntrospectionScope.TABLE, table_name, schema=schema, extra="table_options"
        )
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        sql, params = self.table_options_statement(table_name=table_name, schema=schema).to_sql()
        result = self.parse_table_options(await self._executor.execute(sql, params))
        self._cache.set(key, result)
        return result

    async def collect_table_storage(self, schema: Optional[str] = None) -> List[Dict[str, Any]]:
        """The async twin of :meth:`BigQueryIntrospector.collect_table_storage`.

        Same question, awaited, and the same empty-list answer when the
        dialect cannot answer the family -- so the two reductions see one
        shape of input and cannot disagree about a table's bytes.
        """
        if not self.dialect.supports_table_storage_introspection():
            return []
        sql, params = self.partition_totals_statement(schema).to_sql()
        return await self._executor.execute(sql, params)

    async def list_tables(
        self,
        schema: Optional[str] = None,
        include_system: bool = False,
        table_type: Optional[str] = None,
    ) -> List[IntrospectionTableInfo]:
        """The async twin of :meth:`BigQueryIntrospector.list_tables`.

        Same questions awaited, same reducer, same cache key.
        """
        key = self._cache.key(
            IntrospectionScope.TABLE,
            schema=schema,
            extra=f"{include_system}:{table_type}",
        )
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        sql, params = self.table_list_statement(
            schema=schema,
            include_system=include_system,
            include_views=True,
            table_type=table_type,
        ).to_sql()
        tables = self.parse_tables(await self._executor.execute(sql, params), schema)
        tables = self.parse_table_storage(tables, await self.collect_table_storage(schema))
        self._cache.set(key, tables)
        return tables

    async def get_table_state(self, table_name: str, schema: Optional[str] = None) -> TableState:
        """Return the table's kind, storage options, comment and partitioning.
        (async)

        The async twin of :meth:`BigQueryIntrospector.get_table_state`: same
        three catalog answers awaited, same cache keys, and the same refusal
        -- :class:`~...errors.ObjectNotFoundError` -- for a table the dataset
        does not hold, rather than a state built from no row.
        """
        key = self._cache.key(IntrospectionScope.TABLE, table_name, schema=schema, extra="state")
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        table = next((t for t in await self.list_tables(schema) if t.name == table_name), None)
        if table is None:
            raise ObjectNotFoundError("table", table_name, self._schema_label(schema))
        state = self.parse_table_state(
            table,
            await self.list_table_options(table_name, schema),
            await self.get_partition_state(table_name, schema),
        )
        self._cache.set(key, state)
        return state

    async def get_partition_state(
        self,
        table_name: str,
        schema: Optional[str] = None,
        include_stats: bool = False,
    ) -> PartitionState:
        """Return the table's partition scheme and bounds, never ``None`` (async).

        The async twin of :meth:`BigQueryIntrospector.get_partition_state`:
        same three reads awaited, same neutral answer -- an empty
        :class:`PartitionState` with ``scheme`` ``None`` for a table that is
        not partitioned, never a ``None`` object and never a placeholder
        bound built from the catalog's single ``NULL`` ``partition_id`` row
        -- and the same cache key, ``include_stats`` in the key included.
        """
        key = self._cache.key(
            IntrospectionScope.PARTITION,
            table_name,
            schema=schema,
            extra=f"partition_state:{include_stats}",
        )
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        raw_columns = await self.column_rows(table_name, schema)
        columns = await self.list_columns(table_name, schema)
        options = await self.list_table_options(table_name, schema)
        state = self.parse_partition_state(
            await self.partition_rows(table_name, schema),
            table_name,
            schema,
            columns,
            options,
            _pseudo_partition_columns(raw_columns),
            include_stats=include_stats,
        )
        if state.scheme is None and not any(
            t.name == table_name for t in await self.list_tables(schema)
        ):
            raise ObjectNotFoundError("table", table_name, self._schema_label(schema))
        self._cache.set(key, state)
        return state

    async def list_constraint_states(
        self, table_name: str, schema: Optional[str] = None
    ) -> List[ConstraintState]:
        """Return every constraint the table declares (async).

        The async twin of :meth:`BigQueryIntrospector.list_constraint_states`:
        the same constraints question awaited, the same parser and the same
        cache key, including BigQuery's unenforced declaration
        (``enforced=False``, ``validated=False``).
        """
        key = self._cache.key(
            IntrospectionScope.TABLE, table_name, schema=schema, extra="constraint_states"
        )
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        sql, params = self.index_info_statement(table_name=table_name, schema=schema).to_sql()
        result = self.parse_constraint_states(
            await self._executor.execute(sql, params),
            table_name,
            schema or self.default_schema,
        )
        self._cache.set(key, result)
        return result

    async def list_schemas(self) -> List[str]:
        """Return the datasets the configured project exposes, by name (async)."""
        return [dataset.schema_name for dataset in await self.list_datasets()]

    async def item_exists(
        self,
        kind: ItemKind,
        name: str,
        schema: Optional[str] = None,
    ) -> bool:
        """Whether a shared object of this kind exists (async).

        The async twin of :meth:`BigQueryIntrospector.item_exists`: the same
        three kinds answered from the same cached listings, and the same
        refusal for the kinds and spellings BigQuery cannot be asked about.
        """
        if "." in name:
            return await super().item_exists(kind, name, schema)
        if kind == ItemKind.SCHEMA:
            return name in {dataset.schema_name for dataset in await self.list_datasets()}
        if kind == ItemKind.TABLE:
            return any(table.name == name for table in await self.list_tables(schema))
        if kind == ItemKind.FUNCTION:
            return any(
                routine.routine_name == name
                and str(routine.routine_type).upper() in _FUNCTION_ROUTINE_TYPES
                for routine in await self.list_routines(schema)
            )
        return await super().item_exists(kind, name, schema)

    async def partition_rows(
        self, table_name: str, schema: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """The table's raw ``INFORMATION_SCHEMA.PARTITIONS`` answer (async).

        The async twin of :meth:`BigQueryIntrospector.partition_rows`: same
        statement, same cache key, awaited -- one question shared by the
        neutral partition state and this backend's finer storage shape.
        """
        key = self._cache.key(
            IntrospectionScope.PARTITION, table_name, schema=schema, extra="partition_rows"
        )
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        sql, params = self.partition_list_statement(table_name=table_name, schema=schema).to_sql()
        rows = await self._executor.execute(sql, params)
        self._cache.set(key, rows)
        return rows

    async def get_table_storage_info(
        self, table_name: str, schema: Optional[str] = None
    ) -> BigQueryTableStorageInfo:
        """Return how one table is stored (async), from the three views that know.

        The async twin of :meth:`BigQueryIntrospector.get_table_storage_info`:
        same reads awaited, same per-partition bytes and tiers, and the
        neutral answers are :meth:`get_partition_state` /
        :meth:`get_table_state`.
        """
        options = await self.list_table_options(table_name, schema)
        partitions = self.parse_partitions(await self.partition_rows(table_name, schema))
        columns = await self.list_columns(table_name, schema)
        return BigQueryTableStorageInfo(
            table_name=table_name,
            schema=self._schema_label(schema),
            options=options,
            partitions=partitions,
            partitioning_columns=self._partitioning_columns(columns),
            clustering_columns=self._clustering_columns(columns),
        )


__all__ = [
    "BigQueryIntrospectorMixin",
    "BigQueryIntrospector",
    "AsyncBigQueryIntrospector",
]
