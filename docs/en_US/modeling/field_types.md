# BigQuery field types

BigQuery's type system is richer than the portable set. This page lists the types this
backend calls out specifically; the mapping of portable Python types to columns is handled
by the core type-adapter machinery and is not repeated here.

## Backend-side value wrappers

The package ships three small wrappers for the nested families:

```python
from rhosocial.activerecord.backend.impl.bigquery.types import (
    BigQueryArray,
    BigQueryJSON,
    BigQueryStruct,
)

struct = BigQueryStruct({"street": "Main", "zip": "10001"})
arr = BigQueryArray([1, 2, 3])
doc = BigQueryJSON({"a": 1})
```

They are the natural Python-side representations of `STRUCT`, `ARRAY` and `JSON` values
passed through the adapters.

| BigQuery type | Notes in this backend |
|---|---|
| `STRUCT` / `RECORD` | Named nested fields; rendered with backticked identifiers |
| `ARRAY` | Ordered list; cannot be the direct argument of `MIN` / `MAX` in introspection |
| `JSON` | First-class type with `JSON_QUERY` / `JSON_VALUE` access; see below |
| `GEOGRAPHY` | GIS type; projected as `NULL` in column profiles because it is not orderable |
| `BIGNUMERIC` | Exact high-precision numeric; the adapter registers it for BigQuery |
| `TIMESTAMP` / `DATETIME` | An instant versus a zoneless civil time; `seconds_between` needs `TIMESTAMP` |
| `INT64`, `FLOAT64`, `BOOL`, `STRING`, `BYTES`, `DATE`, `TIME` | Standard scalar families |

## JSON access

BigQuery does not spell JSON extraction the way some other engines do. The dialect answers
`JSON_QUERY` and `JSON_VALUE` to the `->` / `->>` operations respectively:

```python
# column -> '$.a.b'     -> JSON_QUERY(`payload`, '$.a.b')
# column ->> '$.a.b'    -> JSON_VALUE(`payload`, '$.a.b')
```

The path is a SQL string literal; bind parameters are not spliced into it. See
[Querying BigQuery native types](../querying/bigquery_types.md).

## Identifiers are backtick-quoted

Every identifier is wrapped in backticks and an embedded backtick is doubled:

```python
# `My Dataset`.`orders`
# `app``x`.`orders`
```

The renderer never folds case, and dataset names are case-sensitive by default, so
`` `app` `` and `` `APP` `` are different datasets. See
[Schema namespaces and datasets](schema_namespace.md#rendering).

## Generated keys

BigQuery has no `AUTO_INCREMENT`. For a server-generated key use an identity column
(`GENERATED ... AS IDENTITY`); a plain auto-increment marker is refused. Generated columns
are always stored — `VIRTUAL` generated columns are not supported.
