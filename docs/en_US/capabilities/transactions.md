# Transactions and DML

## Session-level transactions

BigQuery transactions are attached to a session. The backend's transaction manager opens
one with `BEGIN TRANSACTION`, commits on success and rolls back on error:

```python
with backend.transaction():
    # statements run inside the BigQuery session
    ...
```

The async backend has the equivalent async manager. `isolation_level` is accepted for API
compatibility but is not mapped to a BigQuery clause. Savepoints are maintained by the
manager as a counter rather than as server-side savepoint statements.

> **Emulator caveat:** an endpoint that rejects `ROLLBACK` (the emulator may) causes a
> warning to be logged; the **original** exception is still raised, so the rollback failure
> never masks the error that caused it.

## No `RETURNING`

BigQuery has no `RETURNING` clause on `INSERT`, `UPDATE` or `DELETE`. The rendered DML
returns no rows. To get the affected rows back, either issue a separate `SELECT` with the
same predicate or express the operation as a `MERGE`. This is a service limitation, not a
setting that can be enabled.

## Affected-row counts

On a normal endpoint the DML result carries the job's affected-row count. In emulator mode
(`api_endpoint` set) the emulator reports no such count, so `update()` and `delete()` recover
one by running a `SELECT COUNT(*)` with the same predicate before the mutation. That
pre-count is qualified with `options.schema_name` using the same qualified-name renderer
the DML statement uses — which is another reason to declare `__schema_name__` on every
model. See
[DDL takes a dataset of its own](../modeling/schema_namespace.md#ddl-takes-a-dataset-of-its-own).

## Mutating statements never carry the dataset on a predicate

The dataset qualifies the target table in the DML statement:

```python
UpdateStatement(
    d, TableExpression(d, "users", schema_name="app"), {"name": Literal(d, "x")}
).to_sql()
# ('UPDATE `app`.`users` SET `name` = ?', ('x',))
```

A predicate built from a model field carries the table name and the column name, never the
dataset. See
[Columns never carry the dataset](../modeling/schema_namespace.md#columns-never-carry-the-dataset).
