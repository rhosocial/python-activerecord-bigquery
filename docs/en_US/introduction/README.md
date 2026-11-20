# Overview

The BigQuery backend is the Google BigQuery implementation for
[rhosocial-activerecord](https://github.com/rhosocial/python-activerecord). It uses the
native `google-cloud-bigquery` client and exposes both a synchronous and an asynchronous
backend. Its job is narrow: map the core library's portable model and expression layer onto
BigQuery's cloud warehouse semantics, and be explicit where those semantics differ.

This chapter set documents **this backend only**. The model API, the query builder and the
dialect-independent expression nodes belong to the core library and are not repeated here;
where a rule is shared, these pages link to the core guide instead of restating it.

## What is particular about BigQuery

| Concern | BigQuery behaviour in this backend |
|---|---|
| Connection identity | A **project** plus a **dataset**; `location` selects a region |
| `schema_name` | Names a dataset, not a table schema |
| Table reference | `` `project`.`dataset`.`table` `` / `` `dataset`.`table` `` |
| Column reference | Never dataset-qualified: `` `orders`.`id` `` or `` `o`.`id` `` |
| Identifier quoting | Backticks, with an embedded backtick doubled |
| Parameters | Named `@param` / positional query parameters via the client, not text substitution |
| Async | Native: `AsyncBigQueryBackend`, not a thread wrapper |
| Execution | Everything is a query **job**; results are fetched from the job |
| Current schema | None — there is no session-level namespace to read back |

The largest single difference to keep in mind: **a dataset is bound per query, not held as
connection state**. Declare `__schema_name__` on the models you use; see
[Schema namespaces and datasets](../modeling/schema_namespace.md).

## Where to go next

* [Relationship with the core library](relationship.md) — the division of responsibility
* [Supported versions](supported_versions.md) — Python and client versions
* [Capability boundaries](capability_boundaries.md) — what is supported and what is refused
* [Connection configuration](../installation/configuration.md) — project, dataset, location,
  credentials and the emulator
* [Quick start](../getting_started/quick_start.md) — a minimal runnable program

## Worked examples

Small, runnable examples live in the repository's `examples/` directory (outside `docs/`):

* [`examples/named_connections/`](../../../examples/named_connections/example.py)
* [`examples/named_procedures/`](../../../examples/named_procedures/example.py)
* [`examples/named_queries/`](../../../examples/named_queries/example.py)
