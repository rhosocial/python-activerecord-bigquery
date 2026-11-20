# Capability boundaries

BigQuery is a managed, columnar warehouse. Some things that look ordinary in an OLTP
database have no equivalent here, and the backend says so rather than producing SQL the
service would reject. This page is a map; the numbered details live in the chapter they
belong to.

## Supported

| Area | Behaviour |
|---|---|
| Queries | `SELECT`, CTEs (including recursive), window functions, `QUALIFY`, set operators, `MERGE`, upsert |
| JSON | A real `JSON` type with `JSON_QUERY` / `JSON_VALUE` access |
| Arrays | `ARRAY` support; nested `STRUCT` / `RECORD` values |
| DDL | `CREATE` / `DROP` / `ALTER TABLE`, `CREATE SCHEMA` (a dataset), views, materialized views, clones and copies |
| Views | `CREATE OR REPLACE VIEW` is available where `IF NOT EXISTS` is not |
| Identity | `GENERATED ... AS IDENTITY` for server-generated keys; plain `AUTO_INCREMENT` is not GoogleSQL |
| Transactions | Session-level `BEGIN` / `COMMIT` / `ROLLBACK` |
| Async | Native async backend with the same API surface as the sync one |
| Introspection | `INFORMATION_SCHEMA` catalogue plus three billed data families |

## Refused, not emulated

| Feature | What happens instead |
|---|---|
| `RETURNING` on DML | No clause exists; issue a separate `SELECT` or use `MERGE` |
| Session-level current schema | `get_current_schema()` raises; pass the dataset explicitly |
| `AUTO_INCREMENT` | Refused; use an identity column |
| `VIRTUAL` generated columns | Refused; BigQuery generated columns are stored |
| `CREATE VIEW ... IF NOT EXISTS`, `DROP VIEW IF EXISTS` | Refused; use `CREATE OR REPLACE VIEW` |
| `DROP SCHEMA ... CASCADE` through the expression layer | Refused; a hand-written statement is needed |
| Secondary indexes | No index family in introspection; clustering and search indexes are separate resources |
| `EXPLAIN` / `EXPLAIN PLAN` | Refused |
| Sequences | No sequence DDL on this backend |
| Cross-project expression names | Only the dataset level is carried; see the schema namespace guide |
| Foreign keys, triggers | No catalogue view; readers return empty rather than inventing the other side |

A refusal usually arrives as `UnsupportedFeatureError` with a suggestion, and often before
a statement is sent — the dialect's `supports_*` probes are what the CLI and the expression
layer consult first.

## Two consequences that surprise people

**Every statement is a job.** Queries run as BigQuery jobs and results are fetched from
them; this is invisible for ordinary CRUD but matters for latency and for how the emulator
is configured.

**Metadata is free; rows are not.** Catalogue reads from `INFORMATION_SCHEMA` are cheap,
but the column-profile, value-sample and join-coverage families scan the table and are
billed. See [Database introspection](../introspection/README.md#cost-every-data-family-is-a-billed-read).
