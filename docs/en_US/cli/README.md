# CLI usage

The backend exposes a command-line module:

```bash
python -m rhosocial.activerecord.backend.impl.bigquery
```

Its `introspect` subcommand answers metadata questions from `INFORMATION_SCHEMA` (or, for
the three data families, from a billed scan).

## Connection flags

Settings come from flags or the environment: `--project`
(`BIGQUERY_PROJECT` / `GOOGLE_CLOUD_PROJECT`), `--dataset` (`BIGQUERY_DATASET`),
`--location` (`BIGQUERY_LOCATION`), `--credentials-path`
(`BIGQUERY_CREDENTIALS_PATH` / `GOOGLE_APPLICATION_CREDENTIALS`), `--credentials-json`
(`BIGQUERY_CREDENTIALS_JSON`) and `--api-endpoint` (`BIGQUERY_API_ENDPOINT`, e.g.
`http://localhost:9050` for the emulator). `--use-async` runs the same commands through the
async backend.

## Examples

```bash
# Project and datasets
python -m rhosocial.activerecord.backend.impl.bigquery introspect database \
  --project my-project
python -m rhosocial.activerecord.backend.impl.bigquery introspect datasets \
  --project my-project

# One dataset's tables and partitions
python -m rhosocial.activerecord.backend.impl.bigquery introspect tables \
  --project my-project --dataset my_dataset
python -m rhosocial.activerecord.backend.impl.bigquery introspect partitions orders \
  --project my-project --dataset my_dataset

# A column's values (billed scan)
python -m rhosocial.activerecord.backend.impl.bigquery introspect value-samples orders \
  --column status --project my-project --dataset my_dataset
```

## Types and output

Fifteen introspection types are offered: `tables`, `views`, `routines`, `columns`,
`datasets`, `database`, `partitions`, `column-profiles`, `value-samples`, `join-coverage`,
`unused-indexes`, `table-stats`, `runtime`, `index-stats`, `dependencies`. The list is
derived from the same mapping that gates each type on its support switch, so a family
cannot be advertised and forgotten by the probe. Unsupported types exit 2 with the reason
on stderr. `ddl` is not offered because no extraction statement exists.

Every type accepts `-o table` (default), `json`, `csv` or `tsv`, and `--rich-ascii` switches
table borders to ASCII. There is no `info` subcommand and no `--limit`: value samples use
the introspector's own default of 100.

The full type table, NAME rules and the warning about billed scans are in
[Database introspection](../introspection/README.md#command-line-introspection).
