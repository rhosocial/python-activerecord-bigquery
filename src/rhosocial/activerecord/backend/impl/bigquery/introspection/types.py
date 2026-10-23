# src/rhosocial/activerecord/backend/impl/bigquery/introspection/types.py
"""BigQuery-only introspection result types.

The core introspection dataclasses describe objects every backend has:
tables, columns, indexes, views and triggers. BigQuery's catalog carries a
few things those shapes have no room for, and this module names them rather
than smuggling them into ``extra`` on an unrelated object:

``BigQueryDatasetInfo``
    A dataset, from ``INFORMATION_SCHEMA.SCHEMATA``.
``BigQueryTableOptionInfo``
    One table option, from ``INFORMATION_SCHEMA.TABLE_OPTIONS``.
``BigQueryPartitionInfo``
    One partition, from ``INFORMATION_SCHEMA.PARTITIONS``.
``BigQueryTableStorageInfo``
    The storage shape of one table: its options, its partitions, and the
    partitioning and clustering columns the ``COLUMNS`` view reports.

**Dataset and schema are the same level here.** BigQuery names relations
``project.dataset.table`` and has no schema under a dataset, so throughout
this backend the core ``schema`` argument *is* the dataset ID. A caller can
pass the dataset alone (the configured project supplies the project) or a
``project.dataset`` pair when the two differ.

Documentation (all read 2026-10-24 UTC):

* ``INFORMATION_SCHEMA.SCHEMATA``
  https://cloud.google.com/bigquery/docs/information-schema-datasets-schemata
* ``INFORMATION_SCHEMA.TABLE_OPTIONS``
  https://cloud.google.com/bigquery/docs/information-schema-table-options
* ``INFORMATION_SCHEMA.PARTITIONS``
  https://cloud.google.com/bigquery/docs/information-schema-partitions
* ``INFORMATION_SCHEMA.COLUMNS``
  https://cloud.google.com/bigquery/docs/information-schema-columns
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class BigQueryDatasetInfo:
    """One row of ``INFORMATION_SCHEMA.SCHEMATA``.

    Field names follow the catalog, lowercased, so a reader can trace each
    one back to the documented column without a mapping table.
    """

    schema_name: str
    catalog_name: Optional[str] = None
    #: Documented as always ``NULL`` for BigQuery.
    schema_owner: Optional[str] = None
    creation_time: Optional[datetime] = None
    last_modified_time: Optional[datetime] = None
    location: Optional[str] = None
    ddl: Optional[str] = None
    default_collation_name: Optional[str] = None
    #: Present for cross-region replicated datasets; ``NULL`` otherwise.
    sync_status: Optional[str] = None


@dataclass
class BigQueryTableOptionInfo:
    """One row of ``INFORMATION_SCHEMA.TABLE_OPTIONS``.

    Options are returned as rows rather than folded into a dict on the table
    because the same option name can carry a different ``option_type``
    (``labels`` is an ``ARRAY<STRUCT<STRING, STRING>>``), and collapsing the
    rows would lose that.
    """

    table_name: str
    option_name: str
    option_value: Optional[str] = None
    option_type: Optional[str] = None
    table_catalog: Optional[str] = None
    table_schema: Optional[str] = None


@dataclass
class BigQueryPartitionInfo:
    """One row of ``INFORMATION_SCHEMA.PARTITIONS``.

    ``partition_id`` is ``NULL`` for an unpartitioned table and
    ``__NULL__`` for the partition that holds rows with a ``NULL``
    partition key, as documented on the catalog page.
    """

    table_name: str
    partition_id: Optional[str] = None
    table_catalog: Optional[str] = None
    table_schema: Optional[str] = None
    total_rows: Optional[int] = None
    total_logical_bytes: Optional[int] = None
    total_billable_bytes: Optional[int] = None
    last_modified_time: Optional[datetime] = None
    storage_tier: Optional[str] = None


@dataclass
class BigQueryTableStorageInfo:
    """One table's storage shape, from three catalog answers.

    BigQuery has no single view that says how a table is stored, so this
    composes the three that each carry part of the answer:

    * ``options`` -- ``TABLE_OPTIONS`` rows: ``partition_expiration_days``,
      ``require_partition_filter``, ``expiration_timestamp``, ``labels``
      and the rest. Which columns partition or cluster the table is *not*
      here; the options table documents no such option.
    * ``partitions`` -- ``PARTITIONS`` rows, one per partition, with the
      per-partition row counts and storage tiers. An unpartitioned table
      answers one row whose ``partition_id`` is ``NULL``.
    * ``partitioning_columns`` / ``clustering_columns`` -- the ``COLUMNS``
      view's ``is_partitioning_column`` and ``clustering_ordinal_position``
      answers, which is where the partitioning and clustering columns are
      actually named. Clustering order is the ordinal position, so the list
      is ordered by it rather than by column name.

    All three pieces are the cached answers of the questions
    :meth:`~...introspection.SyncBigQueryIntrospector.list_table_options`,
    :meth:`~...introspection.SyncBigQueryIntrospector.list_partitions` and
    :meth:`~...introspection.SyncBigQueryIntrospector.list_columns` already
    keep, so a second call for the same table issues no new questions.
    """

    table_name: str
    schema: Optional[str] = None
    options: List[BigQueryTableOptionInfo] = field(default_factory=list)
    partitions: List[BigQueryPartitionInfo] = field(default_factory=list)
    partitioning_columns: List[str] = field(default_factory=list)
    clustering_columns: List[str] = field(default_factory=list)


__all__ = [
    "BigQueryDatasetInfo",
    "BigQueryTableOptionInfo",
    "BigQueryPartitionInfo",
    "BigQueryTableStorageInfo",
]
