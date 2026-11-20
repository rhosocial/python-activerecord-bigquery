# Limits and unsupported features

## Execution model

Every query runs as a **job**; results are fetched from the job. The sync and native async
backends both go through this path, so the difference between them is how the client waits
for and fetches results, not a different SQL generator. An `api_endpoint` override switches
the sync backend to a REST fast path used by the emulator.

## Namespace limits

* There is no session-level current dataset. `get_current_schema()` raises
  `UnsupportedFeatureError`; pass `schema_name` explicitly.
* The expression layer carries **one** namespace level — the dataset. `TableExpression`,
  `Column` and the wildcards have no project field. A dotted value handed to `schema_name`
  stays inside a single quoted identifier; a three-part path is written into `name`
  instead. See
  [Only the dataset level is carried](../modeling/schema_namespace.md#only-the-dataset-level-is-carried).
* A column is never dataset-qualified; a dataset on a column with no table is an error.

## Statements and features refused

| Feature | Reason / alternative |
|---|---|
| `RETURNING` | No clause on BigQuery; use a separate `SELECT` or `MERGE` |
| `EXPLAIN` / `EXPLAIN PLAN` | Not supported by the dialect |
| `AUTO_INCREMENT` | Not GoogleSQL; use `GENERATED ... AS IDENTITY` |
| `VIRTUAL` generated columns | BigQuery generated columns are always stored |
| `CREATE VIEW ... IF NOT EXISTS`, `DROP VIEW IF EXISTS` | Use `CREATE OR REPLACE VIEW` |
| `DROP SCHEMA ... CASCADE` via the expression layer | Hand-written statement required |
| `DROP TABLE ... CASCADE` / `RESTRICT` | Refused |
| `WITH DATA` / `WITH NO DATA` | No such clause in the relevant grammars |
| `MATERIALIZED` CTE hints | GoogleSQL decides materialization itself |
| Secondary indexes | No user-visible indexes; clustering/search indexes are separate |
| Sequences | No sequence DDL on this backend |
| Foreign keys, triggers | No catalogue view; readers return empty rather than inventing data |
| Standalone user-defined types | No type catalogue family in introspection |

A refusal is a `UnsupportedFeatureError` with a suggestion, and the CLI refuses a family
whose probe answers `False` rather than running a statement the service would reject.

## Data-type edges

`MIN` / `MAX` and `COUNT(DISTINCT ...)` are refused by BigQuery on non-orderable or
non-groupable columns (`ARRAY`, `STRUCT`, `JSON`, `GEOGRAPHY`, `RANGE`). The introspector
handles this by projecting those slots as SQL `NULL` rather than failing the whole profile.
See
[Opaque types are projected as `NULL` by name](../introspection/README.md#opaque-types-are-projected-as-null-by-name).
