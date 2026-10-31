# `introspect` — BigQuery metadata, from the command line

The `introspect` subcommand asks a BigQuery project what it holds, and prints
the answer. Every question runs through the backend's introspector, so what the
CLI reports is what the library sees — the same objects, the same types, the
same parsing — rather than a second implementation that can drift from it.

```bash
python -m rhosocial.activerecord.backend.impl.bigquery introspect <TYPE> [NAME] [OPTIONS]
```

## What it can ask about

| Type | Reads | Notes |
| :--- | :--- | :--- |
| `tables` | `INFORMATION_SCHEMA.TABLES` | Tables and views, with `table_type` distinguishing `BASE TABLE`, `VIEW`, `MATERIALIZED VIEW` and `EXTERNAL`. |
| `views` | `INFORMATION_SCHEMA.VIEWS` | Views, with their definitions. |
| `table` | several | One table by name, with its columns and primary key filled in. |
| `columns` | `INFORMATION_SCHEMA.COLUMNS` | One table's columns: name, type, nullability, ordinal position, default. |
| `datasets` | `INFORMATION_SCHEMA.SCHEMATA` | The project's datasets. A dataset is BigQuery's namespace level above a table, so it stands where a schema would elsewhere. |

`NAME` is required for `table` and `columns`. The list types take no name.

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

## Notes

*   **Read-only.** `introspect` never writes. It does not create, drop, or
    alter anything, so it is safe to run against a project whose schema
    matters.
*   **A dataset, not a schema.** BigQuery has no schemas. `--dataset` maps
    onto the `schema` argument the core introspector takes, and the CLI says
    *dataset* so a user is not sent looking for a thing that does not exist.
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
# Datasets, and one dataset's tables
python -m rhosocial.activerecord.backend.impl.bigquery introspect datasets --project my-project
python -m rhosocial.activerecord.backend.impl.bigquery introspect tables --dataset events -o json

# One table's columns
python -m rhosocial.activerecord.backend.impl.bigquery introspect columns orders --dataset events

# Against a local emulator
python -m rhosocial.activerecord.backend.impl.bigquery introspect tables \
    --project test --dataset events --api-endpoint http://localhost:9050
```
