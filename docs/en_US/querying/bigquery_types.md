# Querying BigQuery native types

This page covers the question that follows from
[BigQuery field types](../modeling/field_types.md): once a model has nested or
BigQuery-native columns, how do identifiers and queries around them behave? The core query
API itself is documented in the core library.

## Backtick identifiers

BigQuery quotes identifiers with backticks, one pair per segment:

```python
TableExpression(d, "orders", schema_name="app").to_sql()[0]
# `app`.`orders`

TableExpression(d, "orders", schema_name="app", alias="o").to_sql()[0]
# `app`.`orders` AS `o`
```

An embedded backtick is escaped by doubling it, so `` app`x `` stays inside one identifier
as `` `app``x` ``. `need_quote=False` selects the unquoted branch and warns on a reserved
word. The renderer preserves case; it does not fold it.

## Dataset-aware naming

The dataset qualifies the range in `FROM` and stops there:

```python
Order.query().select(Order.c.id).to_sql()[0]
# SELECT `orders`.`id` FROM `app`.`orders`
```

A column reference is a table name or an alias plus a column name — never a dataset. A
dataset on a column that also has a table is dropped (the `FROM` clause already names the
relation); a dataset on a column with **no** table raises `UnsupportedFeatureError`, because
BigQuery has no form for it. After an alias the prefix becomes the alias (`` `o`.`id` ``).

Cross-dataset joins need no extra configuration: each side qualifies its own range and the
join condition stays two-part. Cross-**project** names are not carried by the expression
layer. All of this is spelled out, with the SQL for each case, in
[Schema namespaces and datasets](../modeling/schema_namespace.md).

## STRUCT and ARRAY

Nested fields are read through the usual GoogleSQL field access and `UNNEST`; the
expressions render with the same backtick identifier policy:

```sql
SELECT `o`.`address`.`city` FROM `app`.`orders` AS `o`;
SELECT `item` FROM `app`.`orders`, UNNEST(`items`) AS `item`;
```

A `STRUCT` field access is a column reference with an extra path step, not a dataset
qualification. The introspector cannot measure bounds on nested families: `ARRAY` and
`STRUCT` columns are projected as `NULL` in a column profile rather than being passed to
`MIN` / `MAX`. See
[Opaque types are projected as `NULL` by name](../introspection/README.md#opaque-types-are-projected-as-null-by-name).

## JSON

BigQuery's `JSON` type uses `JSON_QUERY` for a document and `JSON_VALUE` for text:

```python
# `payload` -> '$.a.b'   -> JSON_QUERY(`payload`, '$.a.b')
# `payload` ->> '$.a.b'  -> JSON_VALUE(`payload`, '$.a.b')
```

The path is emitted as a literal and quoted/escaped by the dialect; a missing or empty path
defaults to `$`. There is no `JSON_EXTRACT` here. Like `ARRAY` and `STRUCT`, a `JSON` column
cannot be grouped or bounded in the data introspection families.

## GEOGRAPHY

`GEOGRAPHY` is a first-class BigQuery type. It is not orderable or groupable in the
introspection aggregates, so a profile counts its nulls but leaves its distinct count and
both bounds `None`. A value sample over such a column is refused by the server with an
error naming the column, which is the honest answer.

## Time

Use `TIMESTAMP` operands for elapsed-time expressions. BigQuery also has a zoneless
`DATETIME` and a separate `DATETIME_DIFF`; the `seconds_between` node deliberately writes
the instant form. See [Temporal expressions](seconds_between.md).
