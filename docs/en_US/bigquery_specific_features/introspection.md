# Database Introspection

The BigQuery backend answers three layers of questions: what the project and its datasets **declare** (`INFORMATION_SCHEMA`), what its columns **hold** (three families that read the rows), and the operational layer it **declines** in full. `backend.introspector` is the entry point for all of it, and every answer on this page is BigQuery's own: the views this catalog exposes, the columns it fills, and the price the engine charges for reading them.

**The price is the headline.** BigQuery bills bytes read, so the three data families are the most expensive questions this backend can be asked, and their cost is proportional to the table rather than to the schema. A profile is one scan of the whole table, and that scan is a billed event. Nothing here is cheap because it is made of metadata: the metadata is free, the rows are not.

## Overview

`backend.introspector` exposes:

- **Project and datasets**: `@@project_id`, and `INFORMATION_SCHEMA.SCHEMATA` (the one view that answers at project level)
- **Tables and views**: `INFORMATION_SCHEMA.TABLES` / `VIEWS`, with the dataset-scoped partitions read reduced onto each table's stored bytes
- **Routines**: `INFORMATION_SCHEMA.ROUTINES`, for persistent UDFs (scalar, aggregate, table functions) and stored procedures
- **Columns**: `INFORMATION_SCHEMA.COLUMNS`, whose projection is the only question that says which of its columns an endpoint carries
- **Primary keys**: `TABLE_CONSTRAINTS` ⋈ `KEY_COLUMN_USAGE`; there is no index catalogue
- **Table options and partitions**: `TABLE_OPTIONS` and `PARTITIONS`
- **Data, three ways**: a profile, a value listing and an overlap measurement, each one or more billed reads

In BigQuery the core `schema` parameter carries a **dataset**: pass the dataset alone and the configured project qualifies it, or pass `project.dataset` to read a dataset in another project. When neither the argument nor the connection config supplies one, the builder raises with that instruction rather than guessing.

## What BigQuery Answers

Every question in the introspection contract has a probe on the dialect, and a probe is a question about the project in front of you rather than about the product. This table is BigQuery's answer to all of them, plus the dataset switch this backend declares for its own family.

Read the `False` rows first: a probe that answers `False` says the question cannot be asked of this project, never that the answer was empty or zero.

| Probe | BigQuery answers | The question it gates |
|-------|------------------|-----------------------|
| `supports_introspection()` | `True` | Anything about the schema at all |
| `supports_database_info()` | `True` | Which project this query runs in |
| `supports_table_introspection()` | `True` | Tables and views in a dataset |
| `supports_column_introspection()` | `True` | Columns and what they declare |
| `supports_index_introspection()` | `False` | Indexes |
| `supports_foreign_key_introspection()` | `False` | Foreign keys and their actions |
| `supports_view_introspection()` | `True` | Views and their definitions |
| `supports_trigger_introspection()` | `False` | Triggers |
| `supports_table_storage_introspection()` | `True` | Per-table stored bytes |
| `supports_runtime_stats()` | `False` | What the service has been doing |
| `supports_table_stats()` | `False` | Per-table usage counters |
| `supports_index_stats()` | `False` | Per-index usage counters |
| `supports_unused_indexes_detection()` | `False` | Indexes with no recorded use |
| `supports_object_dependencies()` | `False` | The object dependency graph |
| `supports_ddl_extraction()` | `False` | The text that recreates an object |
| `supports_ddl_extraction_native()` | `False` (inherited) | Whether that text is the engine's own |
| `supports_column_data_profile()` | `True` | What each column of a table holds |
| `supports_column_value_sample()` | `True` | Which values occur, and how often |
| `supports_join_coverage()` | `True` | How much two columns' domains overlap |
| `supports_partition_info()` | `True` | One table's partitions |
| `supports_extensions()` | `False` (inherited) | Installed add-on components |
| `supports_dataset_introspection()` | `True` | BigQuery's own dataset family |
| `supports_routine_introspection()` | `True` | BigQuery's own routines family |

Three of the `False` rows are not "the engine cannot": they are "the catalogue does not carry it", and each says which part is missing.

- **Indexes.** BigQuery creates no user-visible indexes and `INFORMATION_SCHEMA` documents no index view. A primary key is a *constraint* rather than an index, so it stays reachable through the introspector's constraint read — `get_primary_key()` and `list_indexes()` both answer from `TABLE_CONSTRAINTS` ⋈ `KEY_COLUMN_USAGE` — but the index family itself has nothing to run, and `IndexType` is `UNKNOWN` because there is no index structure behind it.
- **Foreign keys.** `TABLE_CONSTRAINTS` reports that a foreign key exists and `KEY_COLUMN_USAGE` reports its columns, but neither view names the referenced table or its columns, and BigQuery has no `REFERENTIAL_CONSTRAINTS` view. Reporting a foreign key whose `referenced_table` is empty would be a worse answer than none, so `list_foreign_keys()` returns an empty list and the builder refuses rather than fabricating the other side.
- **Triggers.** BigQuery has no triggers, so there is no trigger catalog view and `list_triggers()` returns an empty list.

`supports_extensions()` is inherited `False` for core's reason: no catalogue of add-on components is mapped here. `supports_partition_info()` is `True` because `INFORMATION_SCHEMA.PARTITIONS` answers it, and `supports_dataset_introspection()` is this backend's own switch beside core's set.

A `True` promises only that the statement renders and the project accepts it. It says nothing about the shape of the answer or its price; the price of each family is stated where the family is described.

## Where the Catalogue Answers Come From

| Family | Method | BigQuery source |
|--------|--------|-----------------|
| Database info | `get_database_info()` | `SELECT @@project_id AS catalog_name` |
| Datasets | `list_datasets()` | `INFORMATION_SCHEMA.SCHEMATA` |
| Tables | `list_tables()` | `INFORMATION_SCHEMA.TABLES` + a dataset-scoped `PARTITIONS` read |
| Columns | `list_columns()` | `INFORMATION_SCHEMA.COLUMNS`, asked with a projection |
| Primary key | `get_primary_key()`, `list_indexes()` | `TABLE_CONSTRAINTS` ⋈ `KEY_COLUMN_USAGE` |
| Views | `list_views()`, `get_view_info()` | `INFORMATION_SCHEMA.VIEWS` |
| Routines | `list_routines()`, `get_routine_info()` | `INFORMATION_SCHEMA.ROUTINES` |
| Table options | `list_table_options()` | `INFORMATION_SCHEMA.TABLE_OPTIONS` |
| Partitions | `list_partitions()` | `INFORMATION_SCHEMA.PARTITIONS` |
| Storage | `get_table_storage_info()`, `list_tables()` | `TABLE_OPTIONS`, `PARTITIONS` and `COLUMNS`, composed |

A few consequences of each statement, in the order a reader will meet them:

- **Database info is the project, not a server.** `@@project_id` is a documented read-only system variable, and there is no server release to read over SQL. The reported version is the backend's feature level (`3.0.0` by default), and the record says so in `extra["version_source"]` rather than passing it off as a server release. `name` is the project, and the configured dataset and location ride in `extra`.
- **Tables.** `TABLE_TYPE` is BigQuery's own spelling — `BASE TABLE`, `CLONE`, `SNAPSHOT`, `EXTERNAL`, `VIEW`, `MATERIALIZED VIEW` — mapped onto core's enum with `CLONE` and `SNAPSHOT` counted as base tables, and the original spelling kept in `extra["bigquery_table_type"]`. `include_system` is ignored: the `TABLES` view lists no system tables. The table row also carries the catalog's `ddl` text and the `is_typed` / `is_insertable_into` flags in `extra`.
- **Datasets.** `SCHEMATA` is the one view that answers at project level, and the only one that accepts a region qualifier (`region-us`, `region-europe-north1`, ...). It reports the dataset's location, DDL text, default collation and creation/modification times.
- **Views.** `check_option` is documented as always `NULL` for BigQuery; it is selected so the parsed object can say so rather than assume it. `use_standard_sql` rides in `extra`.
- **Routines.** `routine_type` is the catalog's own word — `FUNCTION`, `AGGREGATE FUNCTION`, `TABLE FUNCTION` or `PROCEDURE`. `data_type` is the declared return type and is `NULL` for a procedure; `routine_body` says `SQL` or `EXTERNAL`, with `external_language` naming JavaScript for the external case; `is_deterministic` is read from the catalog's `YES`/`NO` into a boolean and stays `None` when the catalog does not know. The record also keeps the catalog's `created` / `last_altered` times, the remote-function `connection`, and the `ddl` text when the service reports one.
- **Table options.** Options arrive one row per option — `description`, `expiration_timestamp`, `labels`, `partition_expiration_days`, `require_partition_filter`, `refresh_interval_minutes`, and the external-table ones — so the same option name can appear more than once with a different `option_type`. They are kept as rows rather than folded into a dict for that reason.
- **Partitions.** `partition_id` is `NULL` for an unpartitioned table and `__NULL__` for the partition holding rows whose partitioning key is `NULL`. Each row carries rows, logical bytes, billable bytes, last-modified time and storage tier. With the table name omitted the same question is asked of the whole dataset — one row per partition of every table.
- **Stored bytes.** A table's `size_bytes` is the sum of its partitions' `total_billable_bytes`, reduced from **one** dataset-scoped read rather than one read per table. A table with no partition rows — a view — keeps `None`, which is "not an object this engine stores bytes for", a different answer from zero. `data_size_bytes` and `index_size_bytes` stay `None` because managed storage has no index side to split off; the partition rows themselves stay on the `PARTITIONS` family, which is finer than the common minimum.

## The Six Operational Families BigQuery Declines

All six answer `False`, and they are inherited rather than declared here — the dialect does not override core's probe, because no `INFORMATION_SCHEMA` view answers the question.

| Family | Probe | Why |
|--------|-------|-----|
| Unused indexes | `supports_unused_indexes_detection()` | No unused-index view, and no index to report on |
| Table counters | `supports_table_stats()` | `INFORMATION_SCHEMA` keeps no usage counters |
| Runtime metrics | `supports_runtime_stats()` | No runtime metrics view |
| Index counters | `supports_index_stats()` | No per-index counters, and no indexes to count |
| Dependencies | `supports_object_dependencies()` | No dependency graph in the catalog |
| DDL | `supports_ddl_extraction()` | No native extraction family is mapped here |

A `False` here is "the question cannot be asked here", not "nothing was used". It does not say that a table was never read or that the project has no dependencies; it says the catalog cannot be asked *through this layer*, and the CLI refuses the family rather than running a statement the service would reject or printing an empty row that reads like an answer of zero.

The `ddl` family is the one worth stating carefully, because a table record does carry `TABLES.ddl` in its `extra` dict: that text is what the catalog hands back on the listing, not a DDL-extraction family. The `ddl` probe answers `False` because the family has no statement here, and the CLI offers the subcommand only so that asking it is a capability refusal rather than an unknown command.

## Object Families BigQuery Does Not Have

Some families in the common introspection vocabulary name objects this engine has no equivalent of. They are not implemented here, and no empty family is offered for them; adding a `types` or `sequences` type that always answers `[]` would claim a catalogue the service does not expose.

| Family | Why there is no implementation |
|--------|----------------------------------|
| Types | BigQuery has no standalone user-defined types. `COLUMNS.data_type` names a column's declared type; there is no project- or dataset-level type object to list separately, and no enum, domain, composite or range *type* catalogue. |
| Sequences | BigQuery has no sequences and no `nextval`-style generator. Identity columns and their bounds are reported through `INFORMATION_SCHEMA.COLUMNS` (`is_identity`, `identity_start`, `identity_increment`, ...), which is the column family, not a sequence family. |
| Operators, operator classes, operator families | BigQuery exposes functions and routines, not user-defined operators. There is no `pg_operator`-style catalogue. |
| Reservations, capacity commitments | These are BigQuery **Admin API** resources, not `INFORMATION_SCHEMA` objects. They are also project/organization-level capacity configuration rather than schema metadata a model could be inferred from, so they are intentionally left out of introspection. Use the Admin API (`google-cloud-bigquery-reservation`) when capacity management is the question. |
| Jobs | `INFORMATION_SCHEMA.JOBS*` is project-level job history, not schema. It is operational telemetry rather than a describable structure, is retained for a limited window, and is not a family a model generator should read. The service's job history and monitoring APIs are the right entry point. |

`ROUTINES` is the one family in this table's neighbourhood that *is* implemented, because BigQuery does have persistent routines and the catalog documents them.

## Cost: Every Data Family Is a Billed Read

| Family | Method | Price |
|--------|--------|-------|
| Column profiles | `list_column_data_profiles(table)` | One scan of the whole table, billed |
| Value samples | `sample_column_values(table, column, limit=100)` | One grouped scan of the table, billed, plus a sort |
| Join coverage | `estimate_join_coverage(left..., right...)` | A read of each column, twice over |

There is no per-column statistics catalogue to read. `INFORMATION_SCHEMA.COLUMNS` describes what a column *declares* — type, nullability, default — and no view reports what its rows hold: no null fraction, no distinct count, no bounds. So every figure here is computed when asked, exact over the rows the query saw, and paid for in bytes read.

`COUNT(DISTINCT ...)` is the exact spelling and is what the statement uses; `APPROX_COUNT_DISTINCT` would be cheaper and approximate, and a figure derived from a sample would have to be labelled `source='sample'` rather than `'aggregate'`. The label exists so a caller can tell, and this backend answers exactly — which is also why the price is a full read.

The profile also reads the column catalogue first, and not only for the names: the declared type of each column decides which aggregates may be asked of it. That metadata read is priced in bytes of `INFORMATION_SCHEMA` rather than of the table, so it is cheap beside what follows.

## Column Profiles: One Wide Row, Never a `UNION ALL`

The profile is deliberately projected as **a single wide row** rather than as one `UNION ALL` arm per column, and that is a billing decision as much as a spelling one.

Each arm of a union that reads the same table is a read of it, billed on its own. A fifty-column table written as fifty arms would be scanned fifty times for the same figures. One projection is scanned once, so this is the cheapest exact answer the engine can give — though "cheapest exact" is still a full scan, and the most expensive introspection this backend offers.

The row form has a second consequence that matters to a caller: it keeps each column's bound out of a common-type resolution. A union resolves one common type across its arms, so `min_value` carrying an `INT64` from one column and a `STRING` from another would be a type error rather than a coercion. Here every slot belongs to exactly one column, and the bound is cast to `STRING` only to give it a result name.

The row is shaped positionally — `c1_name`, `c1_null_count`, `c1_distinct_count`, `c1_min`, `c1_max`, then `c2_...` — because a column name may contain any character the catalogue accepts while these names are fixed words the parser reads. The parser pivots the row back into one profile per column, through core's own rules for what a missing figure means, so the derivation of `null_fraction` and the treatment of an absent figure are not spelled a second time here.

## Opaque Types Are Projected as `NULL` by Name

BigQuery refuses `MIN` and `MAX` on columns that are not orderable — `ARRAY`, `STRUCT`/`RECORD`, `JSON`, `GEOGRAPHY` and `RANGE` — and refuses `COUNT(DISTINCT ...)` on several of the same types, which are not groupable either. A statement that named such a column in those positions would not answer for the columns it *can* read: the server rejects the whole query during analysis.

So the introspector names the opaque columns, from the column catalogue it just read, and the formatter leaves their distinct count and both bounds as SQL `NULL` while still counting their nulls and the table's rows. Those three slots arrive as `None` and stay `None`.

The distinction the projection preserves is the one a reader most needs: **`NULL` is a figure the engine refused to measure, not one it measured as zero.** An empty string, a zero and a missing bound are three different answers, and only the third is what an opaque column's profile says. The null count is answerable for every type, so that slot is always a measurement.

An empty column list renders the row with the table's own facts and no column groups; the parser reads it as an empty profile, which is the truth about a table with no columns and not an error. A `SUM` over no rows answers `NULL` rather than a fabricated zero, so an empty table's null count is absent rather than `0`.

## Value Samples and Join Coverage

**Value samples** are a `GROUP BY` over the column plus a sort of the groups — the same billed scan as the profile, plus the sort. Nothing is precomputed, so this is a separate probe from the profile: a caller asking only for the most frequent values should not be charged for the aggregates the profile computes.

- `ORDER BY COUNT(*) DESC` is what makes the answer "the most frequent values" rather than "the first values"; ties break by the value, so two runs of the same query agree.
- The `LIMIT` is a bind parameter, so the caller's integer is never spliced into statement text.
- `GROUP BY` groups `NULL`s, so a column containing `NULL` has an entry whose `value` is `None`. The parser does not skip it: `NULL` is a member of the domain in this listing.
- A column BigQuery cannot group — `ARRAY`, `STRUCT`, `JSON`, `GEOGRAPHY` — is refused **by the server**, with an error naming the column. That is the engine's rule about the chosen column rather than a gap in this family, and a server error is a better answer than a listing that silently omits it.
- `frequency` stays `None`: the engine reports a count and the denominator is the row count, which this query does not carry.

**Join coverage** measures the share of each side's distinct values that the other side also holds. Both fractions come from one statement — two scalar subqueries in one projection, with no `FROM` needed for a row made only of subqueries. Each fraction counts the distinct values under an `IN` predicate over the other side's non-`NULL` values, and divides by that side's distinct non-`NULL` values. `IS NOT NULL` is written on both halves rather than relied upon, and `NULLIF(..., 0)` makes a column with nothing to match answer `NULL` rather than `0.0`, so "nothing matched" and "nothing to match" stay distinct. BigQuery's `/` over two `INT64` counts already answers a `FLOAT64`, so there is no `* 1.0` here.

The row carries both fractions because neither is meaningful alone: a left share of 1.0 beside a right share of 0.2 says every tested value exists on the other side while most of that other domain is unaccounted for, and a single averaged score would describe neither. The price is the two sides read for their distinct domains plus the intersection between them, twice, because both directions are reported. Every one of those reads is billed, which makes this the most expensive measurement in the family. Answering `True` is right because the probe asks whether the engine *can* answer, not whether it can answer cheaply: the cost belongs in this page, not in a `False` that would claim BigQuery cannot measure its own rows.

```python
from rhosocial.activerecord.backend.impl.bigquery.backend import BigQueryBackend
from rhosocial.activerecord.backend.impl.bigquery.config import BigQueryConnectionConfig

config = BigQueryConnectionConfig(
    project="my-project",
    dataset="my_dataset",
    location="US",
    credentials_path="/path/to/key.json",
    # api_endpoint="http://localhost:9050",  # the CI emulator
)
backend = BigQueryBackend(connection_config=config)
backend.connect()

# One scan, one bill. The row is wide; the profiles are per column.
for profile in backend.introspector.list_column_data_profiles("orders"):
    print(
        profile.column_name,
        profile.source,          # 'aggregate': exact, and paid for in bytes read
        profile.row_count,
        profile.null_fraction,
        profile.distinct_count,  # None on an ARRAY, STRUCT, JSON, GEOGRAPHY or RANGE
        profile.min_value,       # None for the same types, by design
        profile.max_value,
    )

# A second scan, of the same bytes: ask for it only when it is the question.
for sample in backend.introspector.sample_column_values("orders", "status", limit=20):
    print(sample.value, sample.count)   # value is None when NULL is a group

# Two columns of two tables, read on both sides and both directions.
coverage = backend.introspector.estimate_join_coverage(
    "orders", "customer_id",
    "customers", "id",
)
print(coverage.left_coverage, coverage.right_coverage)
```

## The `COLUMNS` Projection and the Emulator

`INFORMATION_SCHEMA.COLUMNS` reports its own columns nowhere, so the only question that says which of them an endpoint carries is the `COLUMNS` question itself. There is no version and no capability switch for it: BigQuery reports no server release, and this backend's version is a feature level rather than a negotiated one.

Two projections exist, and they answer different questions.

- `COLUMNS_PROJECTION_FULL` is BigQuery's **documented 24-column order**, and it is the only projection a real server is asked. It is also the only way to read the families a narrower list leaves out: whether a column is generated, what a computed one is computed from, what an identity column's bounds are, which column a table clusters by.
- `_EMULATOR_COLUMNS_PROJECTION` is 10 of those 24 columns — the column coverage of the `goccy/bigquery-emulator` this repository's CI runs against. It is a property of that emulator, not of BigQuery, which is why the constant is **private** and named for the emulator: no real server is asked for less than the documented list.

The fallback is a try-then-reask, performed once and remembered. `list_columns()` asks the full list; if the endpoint fails the question, it re-asks the narrow list and records that this endpoint answers that one, for the rest of the manager's life. A real server never pays for the fallback because the first question succeeds; an emulator pays one failed question once rather than one per table. The narrow list is a subset of the one that just failed, so if it fails too, what failed is the table, the dataset or the connection — and the *first* error is the one that names it, which is the error that is raised.

The fallback makes a new distinction necessary, and the parser keeps it. A field's **presence** in a row *is* the record of the question that was asked — a projection selects names and an endpoint returns one field per selected name — so a name that is absent was never asked, and its absence is never the endpoint answering "no". Each parsed column therefore records the names it was actually asked for in `extra["columns_asked"]`, read off the row.

That is what keeps `is_generated` honest. Read through a `None` default it would arrive as an answer of *no*, so a consumer would be told a column is not generated when the truth is that the endpoint never carried the fact. Instead `is_generated` is `True` or `False` only when `is_generated` is in `columns_asked`, and `None` otherwise — and the same rule covers the identity flags, the identity bounds, the clustering position and the rounding mode. A consumer deciding "is this column generated" must read the two together: `extra["columns_asked"]` says whether the question was asked; the slot says what the answer was.

Two smaller facts about the same view: a column whose `is_hidden` is `YES` is a pseudo column with a `NULL` `ordinal_position`, not part of the declared schema, so the parser skips it; and `parsed_data_type` is `None` for a type string this dialect's parser cannot read (`STRUCT<...>`, `RANGE<...>`), with a warning naming the column, so one unreadable type degrades one column's structured type rather than the whole listing.

## What Has Been Verified

**Only against the emulator.** No GCP credentials exist in CI, so the shard these tests run on is `goccy/bigquery-emulator`, started as a container and spoken to through the REST driver with `--api-endpoint` pointing at it. That is where every statement on this page has been exercised, and it is worth saying plainly what that means:

- A real BigQuery answers the full 24-column `COLUMNS` projection; the emulator answers 10. The code is written so a real server is asked the documented list and only an endpoint that fails it falls back — but the full-list path itself has not been exercised against a real service in this repository's CI.
- The emulator is a shim, not the service: it does not bill, it does not implement everything, and the workflow restarts it between shards because it degrades as tables accumulate. A statement that parses and returns rows there is a statement BigQuery should accept; it is not proof that a real project answered it.
- Anything whose behaviour differs between the emulator and the service — the column projection above is the visible one — is written to prefer the service and to degrade to the emulator, not the other way round.
- The `routines` family is newer than that verification: its statement and parser are covered by offline tests, but no live project or emulator run has exercised `INFORMATION_SCHEMA.ROUTINES` from this repository yet.

## Floors and Version Gates

There are none, and that is a fact about the engine rather than a missing section.

| Family | Floor | What a missing floor looks like |
|--------|-------|----------------------------------|
| every family | none | — |
| `COLUMNS` projection | no version question exists | The `COLUMNS` question itself, asked and re-asked once |

BigQuery reports no server release over SQL, and this backend's version is a feature level rather than a negotiated one, so there is nothing to compare a floor against. The dialect is not version-adapted, and the probes answer for the dialect this backend constructs — the same answer every call of the same construction gets. An `INFORMATION_SCHEMA` question that fails on an endpoint is answered by re-asking with the narrower projection, not by a version gate.

The probes do not test credentials either. A probe answers about the catalog, not about the account: if the run has no credentials or no access to a dataset, the client refuses to connect or the service returns its own permission error, and the probe does not pretend to have foreseen it.

## Command Line Introspection

```bash
# The project, and the datasets it holds
python -m rhosocial.activerecord.backend.impl.bigquery introspect database \
  --project my-project
python -m rhosocial.activerecord.backend.impl.bigquery introspect datasets \
  --project my-project

# One dataset's tables, views and partitions
python -m rhosocial.activerecord.backend.impl.bigquery introspect tables \
  --project my-project --dataset my_dataset
python -m rhosocial.activerecord.backend.impl.bigquery introspect routines \
  --project my-project --dataset my_dataset
python -m rhosocial.activerecord.backend.impl.bigquery introspect routines add_one \
  --project my-project --dataset my_dataset
python -m rhosocial.activerecord.backend.impl.bigquery introspect partitions orders \
  --project my-project --dataset my_dataset

# What a column holds: both commands scan and both are billed
python -m rhosocial.activerecord.backend.impl.bigquery introspect column-profiles orders \
  --project my-project --dataset my_dataset
python -m rhosocial.activerecord.backend.impl.bigquery introspect value-samples orders \
  --column status --project my-project --dataset my_dataset

# The families this backend declines -- refused, not answered with an empty row
python -m rhosocial.activerecord.backend.impl.bigquery introspect unused-indexes \
  --project my-project --dataset my_dataset
python -m rhosocial.activerecord.backend.impl.bigquery introspect ddl orders \
  --project my-project --dataset my_dataset
```

Connection settings come from flags or from the environment: `--project` (`BIGQUERY_PROJECT` or `GOOGLE_CLOUD_PROJECT`), `--dataset` (`BIGQUERY_DATASET`), `--location` (`BIGQUERY_LOCATION`), `--credentials-path` (`BIGQUERY_CREDENTIALS_PATH` or `GOOGLE_APPLICATION_CREDENTIALS`), `--credentials-json` (`BIGQUERY_CREDENTIALS_JSON`), `--api-endpoint` (`BIGQUERY_API_ENDPOINT`, e.g. `http://localhost:9050` for the emulator). `--use-async` runs the same commands through the async backend.

`--dataset` selects the dataset every question is scoped to, and it is the same argument the schema parameter carries, because the two are the same level. `database` is the one question scoped to the project instead, because `@@project_id` names the project and no dataset.

No command fabricates an answer: without a dataset the introspector raises with the exact instruction, and without credentials the client refuses to connect. Both exit non-zero with the reason on stderr, and `--include-system` is accepted but has nothing to include, because the `TABLES` view lists no system tables.

### Introspection Types

| Type | Description | NAME |
|------|-------------|------|
| `tables` | Tables and views in a dataset | not accepted |
| `views` | Views in a dataset | not accepted |
| `routines` | The dataset's routines, or one named routine | optional (routine) |
| `columns` | One table's columns | required (table) |
| `datasets` | The project's datasets | not accepted |
| `database` | The project this run is connected to | not accepted |
| `partitions` | One table's partitions, with their sizes | required (table) |
| `column-profiles` | Every column of a table, profiled from its data | required (table) |
| `value-samples` | One column's most frequent values | required (table) |
| `join-coverage` | How two columns' value domains overlap | required (left table) |
| `unused-indexes` | Indexes with no recorded use | not accepted |
| `table-stats` | Per-table usage counters | not accepted |
| `runtime` | Live runtime measurements | not accepted |
| `index-stats` | Per-index usage counters | not accepted |
| `dependencies` | The object dependency graph | optional (object) |
| `ddl` | The DDL that recreates one table | required (table) |

Sixteen types, and the advertised list is derived from the same mapping that gates each type on its switch, so a family cannot be offered by the CLI and forgotten by the probe.

`database`, `routines` and `partitions` are here because the dialect answers them and the CLI could not ask: `database` is the project-level question, `routines` is the persistent-function/procedure family, and `partitions` is the engine's own family — one row per partition with the rows and the bytes each holds, finer than the common minimum the table listing reduces onto. A CLI that could not ask what the dialect declares would be "answerable but unaskable".

This command has **no `info` subcommand**, so there is no second output-format list: every `introspect` type takes `-o table` (the default), `json`, `csv` or `tsv`, and `--rich-ascii` switches the table borders to ASCII. There is also no `--limit`: `value-samples` is bounded by the introspector's own default (`VALUE_SAMPLE_LIMIT`, 100), so the number is not written in two places.

NAME is required, optional or refused per type, and the rule for each lives in one table rather than inside the question that needs it. A missing `required` name is an incomplete invocation (exit 1); a name a type has no question for is a request the command declines (exit 2), never a parsed-and-dropped argument that would print a family listing under a one-object question. `value-samples` takes `--column`; `join-coverage` takes the left table as its NAME plus `--column`, `--right-table` and `--right-column`; a flag the chosen type does not read is refused (exit 2) rather than ignored.

A type whose switch answers `False` is refused with exit 2 and the reason on stderr, because "this project cannot answer" and "this dataset has none" are different answers. The scan warning for `column-profiles` goes to stderr, ahead of the rows, so a reader sees the price while looking at figures that cost a scan — and the machine formats on stdout stay parseable.
