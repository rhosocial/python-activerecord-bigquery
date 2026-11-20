# rhosocial-activerecord BigQuery Backend Documentation

> 🤖 **AI Learning Assistant**: Key concepts in this documentation are marked with 💡 AI prompt markers. When you encounter a concept you don't understand, you can ask the AI assistant directly.
>
> **Example:** "Why does a BigQuery column reference never carry the dataset, while the table in `FROM` does?"
>
> 📖 **See also**: [AI-Assisted Development Guide](https://github.com/rhosocial/python-activerecord/tree/main/docs/en_US/introduction/ai_assistance.md)

The BigQuery backend is the Google BigQuery backend implementation for
[rhosocial-activerecord](https://github.com/rhosocial/python-activerecord). It uses the
`google-cloud-bigquery` client, offers a native async backend alongside the sync one, and is
explicit about where BigQuery's cloud-warehouse semantics differ from the portable model:
the `schema_name` of this library maps to a **dataset**, column references never carry it,
and there is no session-level current dataset to fall back on.

These chapters cover **this backend only**. The model API, query builder and dialect-independent
expression nodes are documented in the core library and are not repeated here.

## Table of Contents

1. **[Introduction](introduction/README.md)**
    * **[Overview](introduction/README.md)**: what the backend does and the BigQuery-specific facts
    * **[Relationship with the core library](introduction/relationship.md)**: the division of responsibility
    * **[Supported versions](introduction/supported_versions.md)**: Python 3.10–3.14, the client and the feature level
    * **[Capability boundaries](introduction/capability_boundaries.md)**: what is supported and what is refused

2. **[Installation](installation/README.md)**
    * **[Installation guide](installation/installation.md)**: packages and credentials
    * **[Connection configuration](installation/configuration.md)**: project, dataset, location, credentials and emulator settings

3. **[Getting Started](getting_started/README.md)**
    * **[Quick start](getting_started/quick_start.md)**: configure, connect and render a first query

4. **[Modeling](modeling/README.md)**
    * **[Schema namespaces and datasets](modeling/schema_namespace.md)**: declaring `__schema_name__`, backtick identifiers, dataset-aware naming, dataset DDL and materialized views
    * **[BigQuery field types](modeling/field_types.md)**: STRUCT, ARRAY, JSON, GEOGRAPHY, BIGNUMERIC and the temporal types

5. **[Querying](querying/README.md)**
    * **[Querying BigQuery native types](querying/bigquery_types.md)**: backtick identifiers, nested families, JSON access
    * **[Temporal expressions (`seconds_between`)](querying/seconds_between.md)**: `TIMESTAMP_DIFF(end, start, MILLISECOND) / 1000.0`, argument order, bind order, sign and the one-millisecond resolution limit

6. **[DDL](ddl/README.md)**
    * **[BigQuery DDL specifics](ddl/README.md)**: datasets, views, identity columns, options and the refused clauses

7. **[Capabilities](capabilities/README.md)**
    * **[Transactions and DML](capabilities/transactions.md)**: session-level transactions, the absence of `RETURNING`, affected-row counts
    * **[Limits and unsupported features](capabilities/limits.md)**: query jobs, one namespace level and the refused features

8. **[Introspection](introspection/README.md)**
    * **[Database introspection](introspection/README.md)**: what this backend answers from `INFORMATION_SCHEMA`, the billed scans behind the three data families, routines, the two `COLUMNS` projections, the emulator fallback and the fifteen CLI types

9. **[Command Line](cli/README.md)**
    * **[CLI usage](cli/README.md)**: `python -m rhosocial.activerecord.backend.impl.bigquery`

10. **[Testing](testing/README.md)**
    * **[Test configuration](testing/README.md)**: `goccy/bigquery-emulator`, anonymous credentials and emulator-specific differences

## Key facts at a glance

| Question | Answer |
|---|---|
| What does `schema_name` mean? | A dataset |
| Qualified table renders as | `` `app`.`orders` `` |
| Column references | Never dataset-qualified: `` `orders`.`id` `` |
| After an alias | `` `o`.`id` `` |
| Current schema | None — BigQuery has no session-level namespace, so `get_current_schema()` raises `UnsupportedFeatureError` |
| `CREATE SCHEMA` / `DROP SCHEMA` | Supported (dataset DDL) |
| `CASCADE` / `AUTHORIZATION` on schema DDL | Not supported |
| Async | Native, via the client's own async support |
| `RETURNING` | Not supported; use a separate `SELECT` or `MERGE` |

## Related documentation

- **[Schema Namespaces (core guide)](https://github.com/rhosocial/python-activerecord/tree/main/docs/en_US/modeling/schema_namespace.md)**:
  the dialect-independent rules that every backend shares

## Worked examples

Runnable examples live in the repository's `examples/` directory:
[`named_connections`](../../examples/named_connections/example.py),
[`named_procedures`](../../examples/named_procedures/example.py) and
[`named_queries`](../../examples/named_queries/example.py).

---

> ⚠️ **Dependency note**: this backend depends on the core library
> `rhosocial-activerecord`. Install it together with the core library rather than
> independently.
