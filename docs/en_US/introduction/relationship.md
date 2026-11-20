# Relationship with the core library

This backend is a plugin, not a fork. `rhosocial-activerecord` supplies the model
declarations, the query builder and the expression tree; the BigQuery package supplies the
dialect, the connection configuration, the storage backends and the metadata readers that
make those portable objects run against BigQuery.

## What the core library provides

* `ActiveRecord` models, `FieldProxy`, `ActiveQuery` and the expression nodes
* The `ConnectionConfig` base and the mixins a backend composes into its own config
* The backend and dialect protocols, the type-adapter machinery and the introspection
  contracts
* The documentation that explains all of the above — see the
  [core library docs](https://github.com/rhosocial/python-activerecord/tree/main/docs/en_US)

None of that is re-explained in these chapters. When a page here says "the core layer
renders..." it means that behaviour is defined there and merely consumed here.

## What this package adds

| Layer | BigQuery implementation |
|---|---|
| Dialect | `BigQueryDialect` — backtick identifiers, `@param`-style bindings, GoogleSQL spellings |
| Config | `BigQueryConnectionConfig` — project, dataset, location, credentials, API endpoint |
| Backend | `BigQueryBackend` (sync) and `AsyncBigQueryBackend` (native async) |
| Transactions | Session-level `BEGIN` / `COMMIT` / `ROLLBACK` managers, sync and async |
| Types | `BigQueryStruct`, `BigQueryArray`, `BigQueryJSON` and the type adapters |
| Expressions | BigQuery-specific introspection and materialized-view statements |
| Metadata | `BigQueryIntrospector` / `AsyncBigQueryIntrospector` over `INFORMATION_SCHEMA` |
| CLI | `python -m rhosocial.activerecord.backend.impl.bigquery` |

## The two boundaries worth knowing

**The expression layer carries one namespace level.** `TableExpression`, `Column` and the
wildcard nodes accept `schema_name` (a dataset) but have no project field. A three-part
name is reachable only by writing a dotted path into `name`. The full rule is in
[Schema namespaces and datasets](../modeling/schema_namespace.md#only-the-dataset-level-is-carried).

**The introspection probes answer for a service, not a version.** BigQuery reports no
server release over SQL, so the dialect is not version-negotiated in the way a self-hosted
engine might be; the probes are this backend's declared answers. See
[Database introspection](../introspection/README.md#floors-and-version-gates).

## Installation as a namespace package

Both distributions install under the `rhosocial.activerecord` namespace. See
[Installation guide](../installation/installation.md).
