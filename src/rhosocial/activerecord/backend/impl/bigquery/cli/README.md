# `introspect` — BigQuery metadata, from the command line

The `introspect` subcommand asks a BigQuery project what it holds, and prints
the answer. Every question runs through the backend's introspector, so what the
CLI reports is what the library sees — the same objects, the same types, the
same parsing — rather than a second implementation that can drift from it.

```bash
python -m rhosocial.activerecord.backend.impl.bigquery introspect <TYPE> [NAME] [OPTIONS]
```

## What it can ask about

Fifteen types, each gated by the dialect capability switch that answers for it
(`_TYPE_CAPABILITIES` in `introspect.py`). A type whose switch is `False` is
refused with exit code 2 rather than answered with an empty row: "this project
cannot report per-index use counters" and "this project has no counters" are
different answers, and only one of them is what happened.

| Type | Reads | Notes |
| :--- | :--- | :--- |
| `tables` | `INFORMATION_SCHEMA.TABLES` | Tables and views, with `table_type` distinguishing `BASE TABLE`, `VIEW`, `MATERIALIZED VIEW` and `EXTERNAL`. |
| `views` | `INFORMATION_SCHEMA.VIEWS` | Views, with their definitions. |
| `columns` | `INFORMATION_SCHEMA.COLUMNS` | One table's columns: name, type, nullability, ordinal position, default. |
| `datasets` | `INFORMATION_SCHEMA.SCHEMATA` | The project's datasets. A dataset is BigQuery's namespace level above a table, so it stands where a schema would elsewhere. |
| `database` | `SELECT @@project_id` | The project this run connected to. The project-level question, so it takes no dataset and no name. |
| `partitions` | `INFORMATION_SCHEMA.PARTITIONS` | One table's partitions: rows, logical bytes and billable bytes each. This engine's own family — the per-table storage minimum reduces its sums onto one slot, and these rows are finer than that. |
| `column-profiles` | the table's rows | Every column's null count, distinct count, bounds and the table's row count. **A full scan, billed.** |
| `value-samples` | the table's rows | One column's most frequent values. |
| `join-coverage` | two columns' rows | How two columns' value domains overlap, both directions. |
| `unused-indexes` | — | Refused: no `INFORMATION_SCHEMA` view reports index use. |
| `table-stats` | — | Refused: no usage counters exist to read. |
| `runtime` | — | Refused: BigQuery reports no runtime metrics. |
| `index-stats` | — | Refused: there are no per-index counters. |
| `dependencies` | — | Refused: no view names an object's dependants. |
| `ddl` | — | Refused: `TABLES.ddl` describes tables and external tables, not a routine or a view's definition. |

`NAME` is required for `columns`, `partitions`, `ddl`, `column-profiles`,
`value-samples` and `join-coverage`; optional for `dependencies`; refused for
`database`. The list types take no name. A `NAME` given where it is refused
exits 2 rather than being parsed and dropped, and a flag the type does not read
(`--column`, `--right-table`, `--right-column`) is refused the same way.

## Options

| Option | Default | Description |
| :--- | :--- | :--- |
| `-o, --output` | `table` | `table` (rich), `json`, `csv`, `tsv`. |
| `--project` | `BIGQUERY_PROJECT`, or `GOOGLE_CLOUD_PROJECT` | The project to read. |
| `--dataset` | `BIGQUERY_DATASET` | The dataset to read. Stands where `--schema` would in another backend. |
| `--location` | `BIGQUERY_LOCATION` | Region qualifier for the `INFORMATION_SCHEMA` views. |
| `--credentials-path` | `BIGQUERY_CREDENTIALS_PATH`, or `GOOGLE_APPLICATION_CREDENTIALS` | Path to a service-account key file. |
| `--credentials-json` | `BIGQUERY_CREDENTIALS_JSON` | The key's JSON, inline. |
| `--api-endpoint` | `BIGQUERY_API_ENDPOINT` | Endpoint override, for an emulator. |
| `--use-async` | off | Drive the asynchronous backend. |
| `--rich-ascii` | off | ASCII borders for the rich table. |
| `--include-system` | off | No effect: `INFORMATION_SCHEMA` lists no system tables here. |

## Notes

*   **Read-only.** `introspect` never writes. It does not create, drop, or
    alter anything, so it is safe to run against a project whose schema
    matters.
*   **A dataset, not a schema.** BigQuery has no schemas. `--dataset` maps
    onto the `schema` argument the core introspector takes, and the CLI says
    *dataset* so a user is not sent looking for a thing that does not exist.
*   **A profile costs a scan.** BigQuery bills by bytes read, so
    `column-profiles` reads the whole table and is the most expensive thing
    this CLI can be asked. The sentence on stderr before the rows says so;
    each row's `source='aggregate'` says the figures are exact counts.
*   **Nothing here was run against a live project.** The statements are
    written from the official documentation (cited beside each one in the
    source). Verify the first run against your project before relying on the
    shapes.
*   **The `version` is not a server version.** BigQuery has no server release
    to ask about; the backend reports a feature level, and says so rather than
    inventing a number.
*   **One question per invocation.** A CLI process is one connection that
    opens, answers, and closes — there is no cache carried between runs.

## Examples

```bash
# Datasets, and the project itself
python -m rhosocial.activerecord.backend.impl.bigquery introspect datasets --project my-project
python -m rhosocial.activerecord.backend.impl.bigquery introspect database --project my-project

# One dataset's tables and views
python -m rhosocial.activerecord.backend.impl.bigquery introspect tables --dataset events -o json
python -m rhosocial.activerecord.backend.impl.bigquery introspect views --dataset events

# One table's columns, and its partitions
python -m rhosocial.activerecord.backend.impl.bigquery introspect columns orders --dataset events
python -m rhosocial.activerecord.backend.impl.bigquery introspect partitions orders --dataset events

# What the rows hold: a profile, the most frequent values, an overlap
python -m rhosocial.activerecord.backend.impl.bigquery introspect column-profiles orders --dataset events
python -m rhosocial.activerecord.backend.impl.bigquery introspect value-samples orders --column status --dataset events
python -m rhosocial.activerecord.backend.impl.bigquery introspect join-coverage orders \
    --column buyer_id --right-table users --right-column id --dataset events

# A family this project declines: refused, not answered with an empty row
python -m rhosocial.activerecord.backend.impl.bigquery introspect ddl orders --dataset events

# Against a local emulator
python -m rhosocial.activerecord.backend.impl.bigquery introspect tables \
    --project test --dataset events --api-endpoint http://localhost:9050
```
