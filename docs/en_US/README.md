# rhosocial-activerecord BigQuery Backend Documentation

The BigQuery backend is the Google BigQuery backend implementation for
[rhosocial-activerecord](https://github.com/rhosocial/python-activerecord). It uses the
`google-cloud-bigquery` REST driver. In BigQuery the `schema_name` of this library maps to
a **dataset**, and unlike every other backend, column references never carry it.

## Table of Contents

- **[Schema Namespaces](bigquery_specific_features/schema_namespace.md)**: declaring
  `__schema_name__`, why columns are never dataset-qualified, the absence of a
  session-level current dataset, and the limits of single-level qualification

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

## Related documentation

- **[Schema Namespaces (core guide)](https://github.com/rhosocial/python-activerecord/tree/docs/docs/modeling/schema_namespace.md)**:
  the dialect-independent rules that every backend shares

---

> ⚠️ **Dependency note**: this backend depends on the core library
> `rhosocial-activerecord`. Install it together with the core library rather than
> independently.