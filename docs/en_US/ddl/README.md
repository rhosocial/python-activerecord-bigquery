# BigQuery DDL specifics

DDL is where the cloud-warehouse model shows most. The authoritative, example-by-example
treatment of dataset naming is
[Schema namespaces and datasets](../modeling/schema_namespace.md#ddl-takes-a-dataset-of-its-own);
this page is the short index of what is particular here.

## Datasets are schemas

`CREATE SCHEMA` / `DROP SCHEMA` create and delete **datasets**:

```python
CreateSchemaStatement(d, "sales").to_sql()[0]
# CREATE SCHEMA `sales`

CreateSchemaStatement(d, "sales", if_not_exists=True).to_sql()[0]
# CREATE SCHEMA IF NOT EXISTS `sales`
```

`AUTHORIZATION` is refused, and `CASCADE` is refused through the expression layer even
though BigQuery's own grammar accepts it — dropping a non-empty dataset needs a hand-written
statement. The connection config's dataset is not consulted when DDL is built; a migration
names the dataset it means on the statement itself.

## Tables and views

* `CREATE TABLE`, `DROP TABLE IF EXISTS`, `ALTER TABLE ADD/DROP COLUMN IF NOT EXISTS/EXISTS`
  and `TRUNCATE TABLE` are supported.
* `CREATE OR REPLACE TABLE` and `CREATE TABLE ... LIKE` / `... CLONE` are supported.
* BigQuery has no `COMMENT` keyword; an inline table comment is rendered as
  `OPTIONS(description='...')`.
* Views use `CREATE OR REPLACE VIEW`: `CREATE VIEW ... IF NOT EXISTS` and
  `DROP VIEW IF EXISTS` are both refused.
* `AUTO_INCREMENT` is not GoogleSQL. Use `GENERATED ... AS IDENTITY`; generated columns are
  stored, never `VIRTUAL`.
* Sequences are not implemented on this backend.

## Materialized views

Materialized views name their target with a `MaterializedView` object carrying a dataset
(and optionally a project). Refresh is a creation option, changed with
`ALTER MATERIALIZED VIEW ... SET OPTIONS(...)` — there is no `REFRESH MATERIALIZED VIEW`.
Replicas take two view objects, so a replica and its source can live in different datasets.
See
[Materialized views](../modeling/schema_namespace.md#materialized-views).

## Indexes and constraints

BigQuery has no secondary indexes. `CREATE INDEX` / `DROP INDEX` still render for the
statement layer, and a `schema_name` on them qualifies the *index name*, not the table;
index introspection and full-text index support both answer `False`. Clustering and search
indexes are separate resources the expression layer does not model.
