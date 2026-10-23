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
indexes (primary keys)  ``TABLE_CONSTRAINTS`` + ``KEY_COLUMN_USAGE``
views                   ``INFORMATION_SCHEMA.VIEWS``
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

*Indexes.* BigQuery has no user-created indexes. Primary-key constraints
are reported as :class:`IndexInfo` values so ``get_primary_key()`` works;
``IndexType`` is ``UNKNOWN`` because there is no index structure behind it.

Documentation:

* ``INFORMATION_SCHEMA`` overview (dataset/region/project qualifiers)
  https://cloud.google.com/bigquery/docs/information-schema-intro
* ``TABLES`` https://cloud.google.com/bigquery/docs/information-schema-tables
* ``COLUMNS`` https://cloud.google.com/bigquery/docs/information-schema-columns
* ``VIEWS`` https://cloud.google.com/bigquery/docs/information-schema-views
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
from typing import Any, Dict, List, Optional, Tuple

from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError
from rhosocial.activerecord.backend.introspection.base import (
    AsyncAbstractIntrospector,
    IntrospectorMixin,
    SyncAbstractIntrospector,
)
from rhosocial.activerecord.backend.introspection.cache import IntrospectionCache
from rhosocial.activerecord.backend.introspection.executor import (
    AsyncIntrospectorExecutor,
    SyncIntrospectorExecutor,
)
from rhosocial.activerecord.backend.introspection.types import (
    ColumnNullable,
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
    TableType,
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
from .types import (
    BigQueryDatasetInfo,
    BigQueryPartitionInfo,
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
    "MATERIALIZED VIEW": TableType.VIEW,
}

#: The views that are not tables, used when ``include_views=False``.
_VIEW_TYPES = ("VIEW", "MATERIALIZED VIEW")


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


class BigQueryIntrospectorMixin(IntrospectorMixin):
    """SQL building and row parsing shared by the sync and async managers.

    The ``_build_*_sql`` overrides resolve *which* dataset and project a
    question is about and construct the matching statement object from
    :mod:`...expression.introspection`; rendering is the dialect's job. The
    ``_parse_*`` methods are pure Python: rows in, core introspection
    dataclasses out, shared by both managers.
    """

    # ------------------------------------------------------------------ #
    # Names and qualifiers
    # ------------------------------------------------------------------ #

    def _get_default_schema(self) -> str:
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
        raw = schema if schema is not None else self._get_default_schema()
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
        raw = schema if schema is not None else self._get_default_schema()
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
    # SQL building — statement objects, rendered by the dialect
    # ------------------------------------------------------------------ #

    def _build_database_info_sql(self):
        """``SELECT @@project_id AS catalog_name``, as a statement object."""
        return BigQueryDatabaseInfoQueryStatement(self.dialect).to_sql()

    def _build_table_list_sql(
        self,
        schema: Optional[str],
        include_system: bool,
        include_views: bool = True,
        table_type: Optional[str] = None,
    ):
        """Build the ``INFORMATION_SCHEMA.TABLES`` statement.

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
                ``VIEW`` expands to views and materialized views.
        """
        catalog, dataset = self._dataset_scoped(schema)
        del include_system  # BigQuery's catalog has no system tables here.
        return BigQueryTableListQueryStatement(
            self.dialect,
            schema=dataset,
            catalog=catalog,
            include_views=include_views,
            table_type=table_type,
        ).to_sql()

    def _build_column_info_sql(self, table_name: str, schema: Optional[str]):
        """Build the ``INFORMATION_SCHEMA.COLUMNS`` statement.

        ``ordinal_position`` is selected because it orders the result; the
        other columns are the documented ones this backend maps onto
        :class:`IntrospectionColumnInfo` or keeps in ``extra``. Pseudo
        columns (``is_hidden = 'YES'``) are filtered in the parser, because
        their ``ordinal_position`` is documented as ``NULL`` and they are not
        part of the table's declared schema.
        https://cloud.google.com/bigquery/docs/information-schema-columns
        """
        catalog, dataset = self._dataset_scoped(schema)
        return BigQueryColumnInfoQueryStatement(
            self.dialect,
            table_name=table_name,
            schema=dataset,
            catalog=catalog,
        ).to_sql()

    def _build_index_info_sql(self, table_name: str, schema: Optional[str]):
        """Build the primary-key statement over constraints.

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
        ).to_sql()

    def _build_foreign_key_sql(self, table_name: str, schema: Optional[str]):
        """Refuse: the catalog does not expose the referenced relation.

        See the module docstring. The public ``list_foreign_keys`` returns
        an empty list instead of calling this; the builder still refuses so
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

    def _build_view_list_sql(self, schema: Optional[str], include_system: bool):
        """Build the ``INFORMATION_SCHEMA.VIEWS`` statement.

        ``include_system`` is ignored: every row of this view is a user
        view. ``VIEWS`` is dataset-qualified, unlike ``SCHEMATA``.
        https://cloud.google.com/bigquery/docs/information-schema-views
        """
        del include_system
        catalog, dataset = self._dataset_scoped(schema)
        return BigQueryViewListQueryStatement(
            self.dialect, schema=dataset, catalog=catalog
        ).to_sql()

    def _build_view_info_sql(self, view_name: str, schema: Optional[str]):
        """Build one view's ``INFORMATION_SCHEMA.VIEWS`` statement."""
        catalog, dataset = self._dataset_scoped(schema)
        return BigQueryViewInfoQueryStatement(
            self.dialect, view_name=view_name, schema=dataset, catalog=catalog
        ).to_sql()

    def _build_trigger_list_sql(self, table_name: Optional[str], schema: Optional[str]):
        """Refuse: BigQuery has no triggers and no trigger catalog view."""
        del table_name, schema
        raise UnsupportedFeatureError(
            self.dialect.name,
            "trigger introspection",
            "BigQuery has no triggers, so there is no catalog view to query. "
            "list_triggers() returns an empty list.",
        )

    def _build_dataset_list_sql(self):
        """Build the ``INFORMATION_SCHEMA.SCHEMATA`` statement (project/region)."""
        config = getattr(self._backend, "config", None)
        location = getattr(config, "location", None) if config is not None else None
        return BigQueryDatasetListQueryStatement(
            self.dialect, catalog=self._project(), location=location
        ).to_sql()

    def _build_table_options_sql(self, table_name: str, schema: Optional[str]):
        """Build the ``INFORMATION_SCHEMA.TABLE_OPTIONS`` statement."""
        catalog, dataset = self._dataset_scoped(schema)
        return BigQueryTableOptionsQueryStatement(
            self.dialect, table_name=table_name, schema=dataset, catalog=catalog
        ).to_sql()

    def _build_partition_list_sql(self, table_name: str, schema: Optional[str]):
        """Build the ``INFORMATION_SCHEMA.PARTITIONS`` statement.

        Unlike ``SCHEMATA`` this view takes a dataset qualifier only, never
        a region qualifier.
        https://cloud.google.com/bigquery/docs/information-schema-partitions
        """
        catalog, dataset = self._dataset_scoped(schema)
        return BigQueryPartitionListQueryStatement(
            self.dialect, table_name=table_name, schema=dataset, catalog=catalog
        ).to_sql()

    # ------------------------------------------------------------------ #
    # Parsing
    # ------------------------------------------------------------------ #

    def _parse_database_info(self, rows: List[Dict[str, Any]]) -> IntrospectionDatabaseInfo:
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

    def _parse_tables(
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

    def _parse_data_type(self, raw: str, column_name: str) -> Optional[Any]:
        """Read one catalog type string, degrading one column on failure.

        ``parsed_data_type`` is ``None`` for exactly one reason: the catalog
        string could not be read. A ``STRUCT<...>`` or ``RANGE<...>`` type is
        not a type name this dialect's parser accepts, so that column keeps
        its ``data_type`` string and the schema differ falls back to
        comparing strings; the rest of the table is unaffected.
        """
        from rhosocial.activerecord.backend.expression.types._base import DataType

        try:
            return DataType.parse_data_type_str(self.dialect, raw)
        except Exception as exc:  # noqa: BLE001 -- see the docstring
            warnings.warn(
                f"BigQuery reported column {column_name!r} as {raw!r}, which "
                f"this backend's parse_type could not read "
                f"({type(exc).__name__}: {exc}). That column's "
                f"parsed_data_type is left unset; the rest of the table is "
                f"unaffected.",
                RuntimeWarning,
                stacklevel=3,
            )
            return None

    def _parse_columns(
        self, rows: List[Dict[str, Any]], table_name: str, schema: str
    ) -> List[IntrospectionColumnInfo]:
        label = self._schema_label(schema)
        columns: List[IntrospectionColumnInfo] = []
        for row in rows:
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
            identity = str(_row_get(row, "is_identity") or "").strip().upper() == "YES"
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
                        self._parse_data_type(str(raw_type), column_name) if raw_type else None
                    ),
                    nullable=nullable,
                    default_value=_row_get(row, "column_default"),
                    # BigQuery has no AUTO_INCREMENT/IDENTITY column flag in
                    # the core sense; identity columns are reported through
                    # the extra fields instead of claiming auto-increment.
                    is_auto_increment=False,
                    is_generated=(
                        str(_row_get(row, "is_generated") or "").strip().upper() == "ALWAYS"
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
                    },
                )
            )
        return columns

    def _parse_indexes(
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

    def _parse_foreign_keys(
        self, rows: List[Dict[str, Any]], table_name: str, schema: str
    ) -> List[IntrospectionForeignKeyInfo]:
        """Always empty: the catalog cannot name the referenced relation."""
        del rows, table_name, schema
        return []

    def _parse_views(self, rows: List[Dict[str, Any]], schema: str) -> List[IntrospectionViewInfo]:
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

    def _parse_view_info(
        self, rows: List[Dict[str, Any]], view_name: str, schema: str
    ) -> Optional[IntrospectionViewInfo]:
        if not rows:
            return None
        return self._parse_views(rows[:1], schema)[0]

    def _parse_triggers(
        self, rows: List[Dict[str, Any]], schema: str
    ) -> List[IntrospectionTriggerInfo]:
        """Always empty: BigQuery has no triggers."""
        del rows, schema
        return []

    def _parse_datasets(self, rows: List[Dict[str, Any]]) -> List[BigQueryDatasetInfo]:
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

    def _parse_table_options(self, rows: List[Dict[str, Any]]) -> List[BigQueryTableOptionInfo]:
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

    def _parse_partitions(self, rows: List[Dict[str, Any]]) -> List[BigQueryPartitionInfo]:
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


class SyncBigQueryIntrospector(BigQueryIntrospectorMixin, SyncAbstractIntrospector):
    """Synchronous BigQuery introspector.

    Access it through ``backend.introspector``::

        tables = backend.introspector.list_tables()
        columns = backend.introspector.list_columns("orders")
        datasets = backend.introspector.list_datasets()
    """

    def __init__(
        self,
        backend: Any,
        executor: SyncIntrospectorExecutor,
        cache: Optional[IntrospectionCache] = None,
    ) -> None:
        super().__init__(backend, executor, cache)

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

    # ------------------------------------------------------------------ #
    # BigQuery-specific questions
    # ------------------------------------------------------------------ #

    def list_datasets(self) -> List[BigQueryDatasetInfo]:
        """List the project's datasets from ``INFORMATION_SCHEMA.SCHEMATA``."""
        key = self._cache.key(IntrospectionScope.SCHEMA, "*", extra="datasets")
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        sql, params = self._build_dataset_list_sql()
        result = self._parse_datasets(self._executor.execute(sql, params))
        self._cache.set(key, result)
        return result

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
        sql, params = self._build_table_options_sql(table_name, schema)
        result = self._parse_table_options(self._executor.execute(sql, params))
        self._cache.set(key, result)
        return result

    def list_partitions(
        self, table_name: str, schema: Optional[str] = None
    ) -> List[BigQueryPartitionInfo]:
        """List one table's partitions from ``INFORMATION_SCHEMA.PARTITIONS``."""
        key = self._cache.key(
            IntrospectionScope.TABLE, table_name, schema=schema, extra="partitions"
        )
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        sql, params = self._build_partition_list_sql(table_name, schema)
        result = self._parse_partitions(self._executor.execute(sql, params))
        self._cache.set(key, result)
        return result

    def get_table_storage_info(
        self, table_name: str, schema: Optional[str] = None
    ) -> BigQueryTableStorageInfo:
        """Return how one table is stored, from the three views that know.

        Composed from :meth:`list_table_options`, :meth:`list_partitions`
        and :meth:`list_columns`; each of those is cached on its own, so a
        repeated call for the same table asks the database nothing new.

        An unpartitioned table answers one ``PARTITIONS`` row whose
        ``partition_id`` is ``NULL``, and no partitioning or clustering
        columns; a partitioned table answers one row per partition and the
        ``COLUMNS`` view names its partitioning column and any clustering
        columns.
        """
        options = self.list_table_options(table_name, schema)
        partitions = self.list_partitions(table_name, schema)
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

    # ------------------------------------------------------------------ #
    # BigQuery-specific questions
    # ------------------------------------------------------------------ #

    async def list_datasets(self) -> List[BigQueryDatasetInfo]:
        """List the project's datasets (async)."""
        key = self._cache.key(IntrospectionScope.SCHEMA, "*", extra="datasets")
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        sql, params = self._build_dataset_list_sql()
        result = self._parse_datasets(await self._executor.execute(sql, params))
        self._cache.set(key, result)
        return result

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
        sql, params = self._build_table_options_sql(table_name, schema)
        result = self._parse_table_options(await self._executor.execute(sql, params))
        self._cache.set(key, result)
        return result

    async def list_partitions(
        self, table_name: str, schema: Optional[str] = None
    ) -> List[BigQueryPartitionInfo]:
        """List one table's partitions (async)."""
        key = self._cache.key(
            IntrospectionScope.TABLE, table_name, schema=schema, extra="partitions"
        )
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        sql, params = self._build_partition_list_sql(table_name, schema)
        result = self._parse_partitions(await self._executor.execute(sql, params))
        self._cache.set(key, result)
        return result

    async def get_table_storage_info(
        self, table_name: str, schema: Optional[str] = None
    ) -> BigQueryTableStorageInfo:
        """Return how one table is stored, from the three views that know (async)."""
        options = await self.list_table_options(table_name, schema)
        partitions = await self.list_partitions(table_name, schema)
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
    "SyncBigQueryIntrospector",
    "AsyncBigQueryIntrospector",
]
