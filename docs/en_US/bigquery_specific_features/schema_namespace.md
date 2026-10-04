# docs/en_US/bigquery_specific_features/schema_namespace.md

# BigQuery Schema Namespaces

> This page covers what is specific to this backend: what a `schema_name` names
> here, why a column reference never carries that name on BigQuery, what a table
> alias leaves to address a range by, why there is no current dataset to fall
> back on, how much of the three-part BigQuery name the expression layer
> carries, and what the dataset DDL and the materialized view statements do
> with the value.
>
> The model-level API — declaring `__schema_name__`, when the dataset reaches the
> SQL, the DDL boundary, the cross-backend support matrix — is documented in the
> core library guide `docs/modeling/schema_namespace.md`, which lives in the
> `python-activerecord` repository
> ([`docs/en_US/modeling/schema_namespace.md`][core-en]).

[core-en]: https://github.com/rhosocial/python-activerecord/tree/main/docs/en_US/modeling/schema_namespace.md

## How this page was verified

Every SQL fragment below was rendered by the expression layer with
`BigQueryDialect` and no live server:

```
PYTHONPATH=src .venv3.14-ubuntu26.04/bin/python
```

`BigQueryDialect` takes its version as a tuple; `(3, 0, 0)` is the default and
what every example here uses. Model-level fragments were produced by configuring
two models against a `BigQueryConnectionConfig(project="test", dataset="app")`
and reading `to_sql()`.

Statements that describe the server rather than the renderer — what happens to an
unqualified table name, whether a three-part name is accepted, the semantics of
`@@dataset_id` — are BigQuery's own documented behaviour. This repository has no
live BigQuery instance; the `goccy/bigquery-emulator` used by the test suite was
not running while this page was written. Each such statement is marked where it
appears. This page was written against `rhosocial-activerecord-bigquery`
1.0.0.dev1.

## `schema_name` names a dataset, and columns never carry one

This is the first thing to settle, because it changes both what a `schema_name`
means and how much of the generated SQL it appears in.

`BigQueryDialect` implements the core `SchemaSupport` protocol, so a
`schema_name` is accepted everywhere the core expects one, and
`supports_schema()` answers `True`:

```python
dialect.supports_schema()                # True
dialect.supports_create_schema()         # True
dialect.supports_drop_schema()           # True
dialect.supports_schema_if_not_exists()  # True
dialect.supports_schema_if_exists()      # True
dialect.supports_schema_authorization()  # False
dialect.supports_schema_cascade()        # False
```

The value names **a dataset**, which is BigQuery's own container for tables,
views and other resources. BigQuery's `CREATE SCHEMA` reference says so
explicitly, because the word is otherwise misleading:

> **Key Point:** This SQL statement uses the term SCHEMA to refer to a logical
> collection of tables, views, and other resources. The equivalent concept in
> BigQuery is a dataset. In this context, SCHEMA does not refer to BigQuery table
> schemas.
>
> — [`CREATE SCHEMA` statement][ddl-create-schema]

[ddl-create-schema]: https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language#create_schema_statement

That quotation also disposes of a second reading of the word. "Schema" names the
column definitions of a single table in BigQuery's own vocabulary as well, and the
two meanings coexist on the server; a `schema_name` in this library is always the
first and never the second.

A dataset is the container a query names things in. A table lives in a dataset, a
dataset lives in a project, and a project's datasets are unrelated namespaces:
`` `app`.`orders` `` and `` `crm`.`orders` `` are two tables that happen to share
a name.

### Rendering

Identifiers are quoted with backticks, one quoted identifier per segment:

| Expression | SQL |
|---|---|
| `TableExpression(d, "orders", schema_name="app")` | `` `app`.`orders` `` |
| `TableExpression(d, "orders")` | `` `orders` `` |
| `TableExpression(d, "orders", schema_name="app", alias="o")` | `` `app`.`orders` AS `o` `` |
`format_identifier` escapes an embedded backtick by doubling it, so a value that
would otherwise close the reference stays inside one identifier:

```python
TableExpression(d, "orders", schema_name="app`x").to_sql()[0]
# `app``x`.`orders`

TableExpression(d, "orders", schema_name="My Dataset").to_sql()[0]
# `My Dataset`.`orders`
```

The dataset's quoting can also be dropped deliberately:

```python
TableExpression(d, "orders", schema_name="app", schema_need_quote=False).to_sql()[0]
# app.`orders`
```

`schema_need_quote=False` (and its per-role siblings `name_need_quote` and
`alias_need_quote`) reach the unquoted branch, where `need_quote=False` on a
reserved word additionally emits an `IdentifierQuotingWarning`.

**The renderer never folds case.** `schema_name` is emitted in the case it was
written in, and on BigQuery that is the case the server compares:

> Dataset and table names are case-sensitive unless the
> [`is_case_insensitive`][case-insensitive] option is set to `TRUE`.
>
> — [Case sensitivity][lexical-case]

[lexical-case]: https://cloud.google.com/bigquery/docs/reference/standard-sql/lexical#case_sensitivity
[case-insensitive]: https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language#schema_option_list

So on a dataset created without that option, `` `app` `` and `` `APP` `` are two
different names, and a dataset created as `my_dataset` is not found by a model
declaring `__schema_name__ = "My_Dataset"`.

### Columns never carry the dataset

On every other backend in this library, an unaliased range propagates its
namespace into the column references built against it: PostgreSQL renders
`"app"."orders"."id"` from `FROM "app"."orders"`. BigQuery renders no dataset on
a column at all, and this is the single largest difference between this backend
and the rest of the family:

```python
Order.query().select(Order.c.id).to_sql()[0]
# SELECT `orders`.`id` FROM `app`.`orders`

Order.query().where(Order.c.id > 1).to_sql()[0]
# SELECT * FROM `app`.`orders` WHERE `orders`.`id` > ?

Order.query().group_by(Order.c.user_id).order_by(Order.c.id).limit(5).to_sql()[0]
# SELECT * FROM `app`.`orders` GROUP BY `orders`.`user_id`
#   ORDER BY `orders`.`id` ASC LIMIT ?

Order.query().group_by(Order.c.user_id).having(Order.c.total > 10).to_sql()[0]
# SELECT * FROM `app`.`orders` GROUP BY `orders`.`user_id`
#   HAVING `orders`.`total` > ?
```

The dataset qualifies the range in `FROM` and stops there. A column reference is
a table name or an alias plus a column name — two parts — and BigQuery's
documented table-name forms are `mytable`, `dataset.mytable` and
`project.dataset.mytable`, so a column prefix is never a dataset:

> `table_name`
>
> The name (optionally qualified) of an existing table.
>
> ```
> SELECT * FROM Roster;
> SELECT * FROM dataset.Roster;
> SELECT * FROM project.dataset.Roster;
> ```
>
> — [`FROM` clause][from-clause]

[from-clause]: https://cloud.google.com/bigquery/docs/reference/standard-sql/query-syntax#from_clause

`BigQueryDialect` enforces this by overriding `format_column` rather than
letting the core renderer qualify the column, and `format_wildcard` does the
same for `table.*`:

```python
Column(d, "id", table="orders").to_sql()[0]
# `orders`.`id`

WildcardExpression(d, table="orders").to_sql()[0]
# `orders`.*

WildcardExpression(d).to_sql()[0]
# *
```

`format_wildcard` is the one formatter that discards a `schema_name` without
rendering it and without validating it, an empty string included:

```python
WildcardExpression(d, table="orders", schema_name="app").to_sql()[0]
# `orders`.*

WildcardExpression(d, table="orders", schema_name="").to_sql()[0]
# `orders`.*
```

Nothing is lost from the output, since a wildcard carries no dataset to begin
with. The asymmetry is worth noting next to `format_column`, which does refuse an
empty dataset.

Two further consequences of the override are worth stating precisely, because
they differ from the core renderer:

- **A dataset on a column that also has a table is discarded without a
  warning.** The value is still validated — an empty string on a column raises —
  but a valid dataset simply does not reach the output:

  ```python
  Column(d, "id", table="o", schema_name="app").to_sql()[0]
  # `o`.`id`
  ```

- **A dataset on a column with no table warns rather than raises**, because
  BigQuery never qualifies a column and one model definition often has to serve
  both PostgreSQL and BigQuery:

  ```python
  Column(d, "id", schema_name="app").to_sql()[0]
  # `id`
  # UserWarning: BigQuery: dropping schema_name='app' from column 'id' because
  # no table was given; a column reference needs a table to be qualified
  ```

A column *alias* is unaffected: the alias is a property of the output column, not
of the range, so it renders on the unqualified column just as on any other
backend.

```python
Order.query().select(Order.c.id.as_("x")).to_sql()[0]
# SELECT `orders`.`id` AS `x` FROM `app`.`orders`
```

### Aliases

Because the dataset never reaches a column, an alias changes nothing about
qualification: the range keeps its dataset, and the column prefix becomes the
alias. That is one of the places where BigQuery is the simpler case, since a
schema-qualified reference to an aliased range is a syntax error on PostgreSQL and
SQL Server.

```python
TableExpression(d, "orders", schema_name="app", alias="o").to_sql()[0]
# `app`.`orders` AS `o`

Order.query().select(Order.c.with_table_alias("o").id).to_sql()[0]
# SELECT `o`.`id` FROM `app`.`orders`
```

At model level the range alias comes only from a join. Build the range alias and
the column accessor from the same name, and pair them with `join(..., alias=...)`:

```python
Order.query().join(
    User, on=Order.c.user_id == User.c.with_table_alias("u").id, alias="u"
).select(Order.c.id, User.c.with_table_alias("u").name).to_sql()[0]
# SELECT `orders`.`id`, `u`.`name` FROM `app`.`orders`
#   JOIN `crm`.`users` AS `u` ON `orders`.`user_id` = `u`.`id`
```

A self-join aliases both sides:

```python
Order.query().join(
    Order,
    on=Order.c.with_table_alias("c").id == Order.c.with_table_alias("p").user_id,
    alias="p",
).select(Order.c.with_table_alias("c").id, Order.c.with_table_alias("p").id).to_sql()[0]
# SELECT `c`.`id`, `p`.`id` FROM `app`.`orders`
#   JOIN `app`.`orders` AS `p` ON `c`.`id` = `p`.`user_id`
```

### Cross-dataset joins

Each side qualifies its own range, so one statement can span two datasets with no
extra configuration:

```python
Order.query().join(User, on=Order.c.user_id == User.c.id).select(
    Order.c.id, User.c.name
).to_sql()[0]
# SELECT `orders`.`id`, `users`.`name` FROM `app`.`orders`
#   JOIN `crm`.`users` ON `orders`.`user_id` = `users`.`id`
```

The join condition carries no dataset on either side, which is what keeps the
statement within BigQuery's two-part column form. Cross-**dataset** is the limit:
a cross-**project** join needs both ranges to carry a project, and the expression
layer does not carry one — see
[Only the dataset level is carried](#only-the-dataset-level-is-carried).

### Set operations

`UNION`, `INTERSECT` and `EXCEPT` name no object of their own, so there is nothing
for them to qualify. Each branch keeps its own dataset:

```python
Order.query().select(Order.c.id).union(User.query().select(User.c.id)).to_sql()[0]
# SELECT `orders`.`id` FROM `app`.`orders`
#   UNION DISTINCT SELECT `users`.`id` FROM `crm`.`users`
```

The explicit `DISTINCT` keyword is this dialect's rendering: it always writes
either ` ALL` or ` DISTINCT`, and BigQuery's set-operator grammar accepts both
spellings.

> ```
> query_expr
>   [ { INNER | [ { FULL | LEFT } [ OUTER ] ] } ]
>   { UNION { ALL | DISTINCT } | INTERSECT DISTINCT | EXCEPT DISTINCT }
>   ...
> ```
>
> — [Set operators][set-operators]

[set-operators]: https://cloud.google.com/bigquery/docs/reference/standard-sql/query-syntax#set_operators

### CTEs

A CTE is named for the rest of the query, not for the database, so its own name is
bare. The query inside it still carries the model's dataset:

```python
inner = QueryExpression(
    dialect=d,
    select=[Column(d, "id", table="orders", schema_name="app")],
    from_=[TableExpression(d, "orders", schema_name="app")],
)
main = QueryExpression(
    dialect=d,
    select=[Column(d, "id", table="recent_orders")],
    from_=[TableExpression(d, "recent_orders")],
)

WithQueryExpression(d, [CTEExpression(d, "recent_orders", inner)], main).to_sql()[0]
# WITH `recent_orders` AS (SELECT `orders`.`id` FROM `app`.`orders`)
#   SELECT `recent_orders`.`id` FROM `recent_orders`
```

Unlike some backends in this family, the query builder reaches that path here:
`supports_basic_cte()` answers `True`, so `CTEQuery` constructs without raising.

Bare is also what BigQuery wants. A `WITH` clause shadows a permanent table of
the same name for the rest of the query *unless* the table name is qualified, so
qualifying the CTE reference would change which object is read.

## Declaring a dataset on a model

```python
from typing import ClassVar, Optional

class Order(ActiveRecord):
    __table_name__ = "orders"
    __schema_name__ = "app"                 # -> `app`.`orders`
    c: ClassVar[FieldProxy] = FieldProxy()

    id: Optional[int] = None
    user_id: Optional[int] = None
    total: Optional[float] = None
```

`__schema_name__` is optional and defaults to `None`, which means unqualified.
On BigQuery that default is the one to avoid, and the reason is not a matter of
taste — see
[There is no session-level current dataset](#there-is-no-session-level-current-dataset).

The dataset is read once, through `schema_name()`, and reaches each range
expression as it is built. `Order.c.field` snapshots it when the expression is
constructed, not when the query runs, so changing `__schema_name__` afterwards
does not rewrite a condition that already exists; rebuild it. The core guide
describes the binding in full.

A model without `__schema_name__` renders an unqualified range:

```python
PlainOrder.query().select(PlainOrder.c.id).to_sql()[0]
# SELECT `plain_orders`.`id` FROM `plain_orders`
```

`SELECT *` needs no qualification and is rendered without any:

```python
Order.query().to_sql()[0]
# SELECT * FROM `app`.`orders`
```

Do not fold the dataset into `__table_name__`. The identifier is quoted as a
single unit, so the result is a table whose name contains a dot:

```python
class Dotted(ActiveRecord):
    __table_name__ = "app.orders"

Dotted.query().select(Dotted.c.id).to_sql()[0]
# SELECT `app.orders`.`id` FROM `app.orders`
```

## DDL takes a dataset of its own

`__schema_name__` selects the read/write dataset. It is **not** consulted when DDL
is built — a migration has to name the dataset it means — but every statement that
names a dataset-bearing object accepts a `schema_name` of its own:

```python
CreateTableExpression(
    d, TableExpression(d, "orders", schema_name="app"), columns=cols
).to_sql()[0]
# CREATE TABLE `app`.`orders` (`id` INT64)

DropTableExpression(d, TableExpression(d, "orders", schema_name="app"),
                    if_exists=True).to_sql()[0]
# DROP TABLE IF EXISTS `app`.`orders`

CreateViewExpression(d, "v_orders", query, schema_name="app").to_sql()[0]
# CREATE VIEW `app`.`v_orders`  AS SELECT `orders`.`id` FROM `app`.`orders`
```

(The double space in the `CREATE VIEW` fragment above is what the renderer emits.)

The DML statements take a qualified `TableExpression` and qualify the same way.
Without a `WHERE` clause they render the range and nothing else, which is also
the shortest way to see that no dataset reaches a predicate:

```python
InsertExpression(
    d, TableExpression(d, "users", schema_name="app"),
    ValuesSource(d, [[Literal(d, "x")]]), columns=["name"],
).to_sql()
# ('INSERT INTO `app`.`users` (`name`) VALUES (?)', ('x',))

UpdateExpression(
    d, TableExpression(d, "users", schema_name="app"), {"name": Literal(d, "x")}
).to_sql()
# ('UPDATE `app`.`users` SET `name` = ?', ('x',))

DeleteExpression(d, [TableExpression(d, "users", schema_name="app")]).to_sql()
# ('DELETE FROM `app`.`users`', ())
```

A predicate built from a model's field carries the table name and the column
name, never the dataset — see
[Columns never carry the dataset](#columns-never-carry-the-dataset).

In emulator mode (`api_endpoint` set) `update()` and `delete()` need the dataset for
one more purpose: the emulator reports no affected-row count, so the backend
recovers it by counting matching rows first, qualifying that `SELECT COUNT(*)`
with `options.schema_name`. A DML statement issued without a dataset resolves
against nothing there either.

Two DDL statements are refused rather than qualified, because BigQuery does not
have the clause:

```python
DropViewExpression(d, "v_orders", schema_name="app", if_exists=True).to_sql()
# UnsupportedFeatureError: 'BigQuery' dialect does not support DROP VIEW IF
# EXISTS. Suggestion: BigQuery does not support DROP VIEW IF EXISTS.

CreateViewExpression(d, "v_orders", query, schema_name="app", if_not_exists=True).to_sql()
# UnsupportedFeatureError: 'BigQuery' dialect does not support CREATE VIEW IF
# NOT EXISTS. Suggestion: BigQuery does not support CREATE VIEW IF NOT EXISTS.
```

`CREATE OR REPLACE VIEW` is available in their place.

### `CREATE SCHEMA` and `DROP SCHEMA` create and delete datasets

Both statements are rendered through the dataset name as a single quoted
identifier:

```python
CreateSchemaExpression(d, "sales").to_sql()[0]
# CREATE SCHEMA `sales`

CreateSchemaExpression(d, "sales", if_not_exists=True).to_sql()[0]
# CREATE SCHEMA IF NOT EXISTS `sales`

DropSchemaExpression(d, "sales", if_exists=True).to_sql()[0]
# DROP SCHEMA IF EXISTS `sales`
```

`authorization=` is refused, and `cascade=True` is refused as well:

```python
CreateSchemaExpression(d, "sales", authorization="app_user").to_sql()
# UnsupportedFeatureError: 'BigQuery' dialect does not support CREATE SCHEMA
# AUTHORIZATION. Suggestion: BigQuery does not support CREATE SCHEMA
# AUTHORIZATION.

DropSchemaExpression(d, "sales", cascade=True).to_sql()
# UnsupportedFeatureError: 'BigQuery' dialect does not support DROP SCHEMA
# CASCADE. Suggestion: BigQuery does not support DROP SCHEMA CASCADE.
```

**The `CASCADE` refusal is narrower than the server.** BigQuery's own `DROP SCHEMA`
grammar offers both behaviours:

> ```
> DROP [ EXTERNAL ] SCHEMA [ IF EXISTS ] [ project_name . ] dataset_name
>   [ CASCADE | RESTRICT ]
> ```
>
> `CASCADE`: Deletes the dataset and all resources within the dataset, such as
> tables, views, and functions. You must have permission to delete the resources,
> or else the statement returns an error.
>
> — [`DROP SCHEMA` statement][ddl-drop-schema]

[ddl-drop-schema]: https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language#drop_schema_statement

`supports_schema_cascade()` answers `False` and `format_drop_schema_statement`
raises on `cascade=True`, so `DROP SCHEMA ... CASCADE` cannot be issued through
the expression layer even though BigQuery accepts the statement. Dropping a
non-empty dataset therefore needs a hand-written statement. Note also that
neither schema DDL statement has a field for the `project_name` both grammars
accept — see
[Only the dataset level is carried](#only-the-dataset-level-is-carried).

BigQuery also has `ALTER SCHEMA` and `UNDROP SCHEMA`. Neither has an expression in
the core layer, so there is nothing to render or to qualify.

### Materialized views

All four materialized view statements take `schema_name` and qualify the view:

```python
BigQueryCreateMaterializedViewExpression(d, "mv", query=inner, schema_name="app").to_sql()[0]
# CREATE MATERIALIZED VIEW `app`.`mv` AS SELECT `orders`.`id` FROM `app`.`orders`

BigQueryDropMaterializedViewExpression(d, "mv", schema_name="app", if_exists=True).to_sql()[0]
# DROP MATERIALIZED VIEW IF EXISTS `app`.`mv`

BigQueryAlterMaterializedViewSetOptionsExpression(
    d, "mv", schema_name="app",
    options={"enable_refresh": True, "refresh_interval_minutes": 30},
).to_sql()[0]
# ALTER MATERIALIZED VIEW `app`.`mv` SET OPTIONS(enable_refresh = true, refresh_interval_minutes = 30)
```

BigQuery has no `REFRESH MATERIALIZED VIEW` statement, so
`supports_refresh_materialized_view()` answers `False`. Refresh is configured
through `OPTIONS(enable_refresh=..., refresh_interval_minutes=...)` at creation
and changed with `ALTER MATERIALIZED VIEW ... SET OPTIONS(...)`.

**The replica statement qualifies both names with the same dataset.** That is the
only `schema_name` it has:

```python
BigQueryCreateMaterializedViewReplicaExpression(
    d, "mv_replica", "mv_src", schema_name="app",
    replication_interval_seconds=600,
).to_sql()[0]
# CREATE MATERIALIZED VIEW `app`.`mv_replica`
#   OPTIONS(replication_interval_seconds = 600) AS REPLICA OF `app`.`mv_src`
```

BigQuery's documented example puts the replica and its source in different
datasets and gives each its own fully qualified name:

> ```
> CREATE MATERIALIZED VIEW `myproject.bq_dataset.mv_replica`
> OPTIONS ( replication_interval_seconds = 600 )
> AS REPLICA OF `myproject.s3_dataset.my_s3_mv`
> ```
>
> — [`CREATE MATERIALIZED VIEW` statement][ddl-create-mv]

[ddl-create-mv]: https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language#create_materialized_view_statement

So a replica whose source lives in another dataset — the case that matters for
cross-region replication — cannot be expressed through this expression. The
statement has to be written by hand.

### Statements this dialect does not format

Sequence DDL is not implemented on this backend, so `schema_name` on it never
reaches a renderer:

```python
CreateSequenceExpression(d, "s_orders", schema_name="app").to_sql()
# AttributeError: BigQueryDialect has no formatting method
# 'format_create_sequence_statement' (required by CreateSequenceExpression).
```

`ALTER TABLE ... ADD/DROP INDEX` is refused at the capability level
(`supports_alter_table_index_actions()` answers `False`), while `CREATE INDEX`
and `DROP INDEX` do render and take a `schema_name` for both the index name and
the table it is built on:

```python
CreateIndexExpression(d, "idx_orders_id", "orders", ["id"], schema_name="app").to_sql()[0]
# CREATE INDEX `app`.`idx_orders_id` ON `app`.`orders` (`id`)

DropIndexExpression(d, "idx_orders_id", schema_name="app").to_sql()[0]
# DROP INDEX `app`.`idx_orders_id`
```

BigQuery has no secondary indexes. Clustering and search indexes are separate
resources that this library's expression layer does not model, and the flags say
so: `supports_index_introspection()` and `supports_fulltext_index()` both answer
`False`. `supports_create_index()` and `supports_drop_index()` still answer `True`,
which is why the two statements above render rather than raise.

## There is no session-level current dataset

This is the second thing to settle, and it changes how a missing dataset should be
handled: on BigQuery there is nothing to fall back on, so a dataset is either
stated explicitly or the statement is not qualified at all.

A dataset on BigQuery is bound per query rather than held as connection state.
BigQuery's own notion of a default dataset is a property of the query, not of a
session:

> `@@dataset_id`
>
> STRING, Read and write. ID of the default dataset in the current project. This
> ID is used when a dataset is not specified for a project in the query. You can
> use the `SET` statement to assign `@@dataset_id` to another dataset ID in the
> current project.
>
> — [System variables reference][system-variables]

[system-variables]: https://cloud.google.com/bigquery/docs/reference/system-variables

The same is true at the API level: the default dataset is a field of the query
request.

> `defaultDataset`
>
> object (`DatasetReference`) Optional. Specifies the default datasetId and
> projectId to assume for any unqualified table names in the query. If not set,
> all table names in the query string must be qualified in the format
> `'datasetId.tableId'`.
>
> — [`jobs.query` request body][jobs-query]

[jobs-query]: https://cloud.google.com/bigquery/docs/reference/rest/v2/jobs/query

### `get_current_schema()` raises

There is no current dataset to read back, so both backends refuse the question
rather than answering it with a guess:

```python
backend.get_current_schema()             # sync
await async_backend.get_current_schema()  # async
```

```
UnsupportedFeatureError: 'BigQuery' dialect does not support reading the current
schema. Suggestion: A dataset is bound per query rather than tracked as session
state, so it cannot be read back from the server. Pass schema_name explicitly
instead.
```

The suggestion is the whole of the advice: **pass `schema_name` explicitly**.
Code that reads the current schema to decide whether to qualify a name has no
portable form on this backend. Give the namespace to the model, or pass it to the
statement, and do not build a fallback out of "the current one".

### What the connection's `dataset` field does, and does not do

`BigQueryConnectionConfig.dataset` exists, and it is worth being exact about its
role, because it is *not* a default dataset for generated SQL. It is read in two
places, both of them about the connection rather than about a query:

- `introspect_and_adapt()` reads it and calls `datasets.get` on it as an existence
  check; with no dataset configured it lists a single dataset instead as a
  connectivity smoke test. Failures are logged and do not prevent use. The
  docstring is explicit that the call is informational: BigQuery exposes a stable
  Standard SQL feature set, so no capability is adapted from it.
- `ping()` reads it to list the dataset's tables, falling back to the literal
  `'default'` when it is unset.

It is **not** sent as the query job's `default_dataset`. `_build_job_config()`
builds a `QueryJobConfig` carrying `query_parameters` and nothing else, and the
REST fast path taken when `api_endpoint` is set posts a request body of `query`,
`useLegacySql`, `timeoutMs` and `maxResults` — no `defaultDataset` field. Given
the `defaultDataset` contract quoted above, the consequence is direct: **a model
without `__schema_name__` renders an unqualified table name that has nothing to
resolve against.** The test suite's own provider makes the same assumption,
setting `__schema_name__` on every model it configures because "without it the
emulator client would resolve bare table names against nothing".

Declare `__schema_name__` on every model on this backend. There is no connection
setting that supplies the dataset for you.

## Only the dataset level is carried

BigQuery's fully qualified table name has three parts, and the reference states the
count:

> A table name can be a
> [fully qualified table name (table path)][lexical] that includes up to three
> quoted or unquoted identifiers:
>
> - An optional project ID
> - An optional dataset name
> - A required table name.
>
> For example: `myproject.mydataset.mytable`

[lexical]: https://cloud.google.com/bigquery/docs/reference/standard-sql/lexical

**This library currently carries one of them.** Stated plainly:

> **The table, view, column and index expressions in this backend accept a
> `schema_name` and nothing above it. `TableExpression`, `Column`,
> `WildcardExpression` has no project field,
> and no dialect hook adds one. A dataset is always rendered as exactly one
> quoted segment followed by one dot, so a dotted value stays inside that
> segment.** (`Column` and `WildcardExpression` discard the value; see
> [Columns never carry the dataset](#columns-never-carry-the-dataset).)

```python
TableExpression(d, "orders", schema_name="myproj.app").to_sql()[0]
# `myproj.app`.`orders`
```

The two segments are quoted separately, so the dot inside the first one is part of
that identifier rather than a path separator. Whether BigQuery reads
`` `myproj.app`.`orders` `` as a project plus a dataset, or rejects it because the
first element contains a dot, was not verified here — a project ID cannot contain
a dot, so a dotted `schema_name` is not a way to reach another project either
way.

The route that does reach the documented three-part spelling is `name`, because a
name is quoted as one identifier and a dotted quoted identifier is how BigQuery
writes a path:

```python
TableExpression(d, "myproj.app.orders").to_sql()[0]
# `myproj.app.orders`
```

That is the form BigQuery's own examples use — `` `myproject.bq_dataset.mv_replica` ``
in the materialized view replica statement, for instance. It puts the whole path
in one quoted identifier, so it is not the same shape as `schema_name` plus
`name`, and a model cannot produce it from both fields at once.

The same one-level limit applies to the dataset DDL: BigQuery's `CREATE SCHEMA` and
`DROP SCHEMA` grammars both accept `[ project_name . ]`, and neither expression
here has a field for it.

So a statement that genuinely has to cross projects needs one of:

- a `name` written as a dotted path, which puts the project and the dataset in the
  table name instead of in `schema_name`;
- a hand-written statement;
- a connection whose jobs execute in the intended project, so that BigQuery's
  `@@project_id` supplies the project level and the two-part name resolves there.
  This one depends on how the job's project is chosen, which this repository does
  not exercise.

## What introspection does on this backend

Short answer: **there is no BigQuery introspector in this package, and no
`INFORMATION_SCHEMA` query is generated.** The dataset is not read from a catalog
view; it is read from the connection config, in the two places described above.

The umbrella flag and the granular ones disagree, which is worth knowing before
writing code against either:

```python
dialect.supports_introspection()             # True

dialect.supports_table_introspection()        # False
dialect.supports_column_introspection()      # False
dialect.supports_view_introspection()        # False
dialect.supports_trigger_introspection()      # False
dialect.supports_index_introspection()       # False
dialect.supports_database_info()             # False
dialect.supports_foreign_key_introspection() # False
dialect.get_supported_introspection_scopes() # []
```

Every metadata query formatter therefore refuses:

```python
TableInfoExpression(d, "orders").to_sql()
# UnsupportedFeatureError: 'BigQuery' dialect does not support table
# introspection.
```

The backend itself carries no introspector instance either: `BigQueryBackend` does
not include the core `IntrospectorBackendMixin`, and has no `introspector`
attribute. Metadata for a dataset has to come from the BigQuery API — `datasets.get`,
`tables.list`, `tabledata.list` — or from a hand-written `INFORMATION_SCHEMA`
query.

## The empty string, and when it is caught

`""` is a mistake, not a way of saying "unqualified" — that is what `None` means.
It is rejected, but **not when the expression is built**. An expression only
collects parameters at that point, so strict validation happens while the
statement is rendered, where the statement is known to be whole. The failure
therefore arrives later than you would expect:

```python
class Bad(ActiveRecord):
    __table_name__ = "empties"
    __schema_name__ = ""

Bad.schema_name()                        # ''           -- no error
Bad.c.id                                 # Column       -- no error
Bad.query()                              # ActiveQuery  -- no error
Bad.query().select(Bad.c.id)             # ActiveQuery  -- no error
Bad.query().select(Bad.c.id).to_sql()    # ValueError   -- here
```

The message names the expression that validated the value. At model level that is
the column, because `FieldProxy` builds the column carrying the dataset and
`format_column` validates before the range does:

```
ValueError: Column.schema_name must be a non-empty string; use None for an
unqualified reference
```

Built directly, the range is named instead:

```
ValueError: TableExpression.schema_name must be a non-empty string; use None for
an unqualified reference
```

A blank string is rejected the same way as an empty one — the check strips
whitespace first, so `"   "` is refused too. A non-string is rejected with its own
message:

```
ValueError: TableExpression.schema_name must be a string or None, not int
```

The reason to reject rather than treat `""` as absent: `format_table` decides
whether to qualify from `bool(expr.schema_name)`, which is false for `""`, and
takes the unqualified branch. A caller who asked for `` `app`.`orders` `` would get
`` `orders` `` with no error and no warning. What is measured here is that
unqualified rendering; what the server then says about it was not observed, and
the error would be about a table that resolves against no dataset rather than about
an empty schema name — which points somewhere other than the mistake.

## Common mistakes

**Reading `schema_name` as BigQuery's table schema.** Two unrelated meanings share
the word on BigQuery, and the `CREATE SCHEMA` reference says so: the statement
uses SCHEMA for "a logical collection of tables, views, and other resources", the
equivalent of a dataset, and explicitly not for a table's column definitions. In
this library `schema_name` always means the first.

**Expecting a `current_schema()` to fall back on.** There is no session-level
current dataset on BigQuery and `get_current_schema()` raises rather than
returning a value or inferring one from the config. There is nothing to fall back
to, so the code shape that works elsewhere — look up the current namespace, and
qualify only when it differs — has no BigQuery equivalent. Qualify explicitly.

**Leaving `__schema_name__` unset and relying on the connection.** The connection's
`dataset` field is not sent as the job's `default_dataset`, so the rendered bare
name has nothing to resolve against. This is the mistake most likely to reach a
real BigQuery project, because the generated SQL looks correct. See
[There is no session-level current dataset](#there-is-no-session-level-current-dataset).

**Expecting the dataset on column references.** BigQuery takes a table name or an
alias plus a column name; a dataset is never a column prefix. A three-part
reference such as `` SELECT `app`.`orders`.`id` `` is not what this backend emits
under any combination of `schema_name` and alias. See
[`schema_name` names a dataset, and columns never carry one](#schema_name-names-a-dataset-and-columns-never-carry-one).

**Expecting `project.dataset.table` to be renderable.** The expressions carry one
namespace level, `schema_name`, and render it as exactly one quoted segment. See
[Only the dataset level is carried](#only-the-dataset-level-is-carried).

**A dot in `__table_name__` is not a namespace.** Each identifier is quoted as a
single unit, so the dot stays inside it:

```python
class Dotted(ActiveRecord):
    __table_name__ = "app.orders"

Dotted.query().select(Dotted.c.id).to_sql()[0]
# SELECT `app.orders`.`id` FROM `app.orders`
```

**A dot in `__schema_name__` is not two levels either.**

```python
TableExpression(d, "orders", schema_name="myproj.app").to_sql()[0]
# `myproj.app`.`orders`
```

**Dropping a non-empty dataset and expecting `CASCADE` to work.** BigQuery supports
`DROP SCHEMA ... CASCADE`, and this backend refuses it, because
`supports_schema_cascade()` answers `False`. See
[`CREATE SCHEMA` and `DROP SCHEMA` create and delete datasets](#create-schema-and-drop-schema-create-and-delete-datasets).

**Creating a replica of a view in another dataset.** The replica statement has one
`schema_name` and applies it to both the replica and its source. See
[Materialized views](#materialized-views).

**Expecting construction to raise.** Nothing rejects a bad `schema_name` until the
statement renders. A model-level mistake therefore survives every step up to and
including query building, and fails at the point the SQL is assembled.

**Looking for metadata introspection.** `supports_introspection()` answers `True`
and every granular introspection flag answers `False`; the query formatters raise.
See [What introspection does on this backend](#what-introspection-does-on-this-backend).

**Declaring a dataset in the wrong case.** The renderer preserves case, and dataset
names are case-sensitive by default, so `` `app` `` does not find a dataset created
as `APP`. See [Rendering](#rendering).

## Recommended layering

- **Declare `__schema_name__` on every model.** There is no connection-level
  default dataset on this backend, so an unqualified range has nothing to resolve
  against. This is the one rule with no exception.
- **One dataset per model, stated once.** `__schema_name__` on a shared base class
  covers a family of models; see the patterns in the core guide.
- **Several datasets** — set `__schema_name__` on the models that differ. Cross-
  dataset joins need no extra configuration, each side qualifying its own range,
  and column references stay two-part throughout, so the generated SQL is no larger
  than it would be unqualified.
- **Several projects** — a separate connection per project, plus a `name` written as
  a dotted path where a statement genuinely has to cross projects. Widening
  `schema_name` does not reach a project on this backend.
