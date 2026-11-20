# BigQuery 字段类型

BigQuery 的类型系统比可移植类型集更丰富。本页列出本后端特别说明的类型；可移植 Python 类型到
列的映射由核心类型适配器机制处理，此处不重复。

## 后端侧的值包装类

包里为嵌套类型族提供了三个小包装类：

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

它们是通过适配器传入的 `STRUCT`、`ARRAY`、`JSON` 值在 Python 侧最自然的表示。

| BigQuery 类型 | 本后端中的说明 |
|---|---|
| `STRUCT` / `RECORD` | 命名的嵌套字段；以反引号标识符渲染 |
| `ARRAY` | 有序列表；在内省中不能直接作为 `MIN` / `MAX` 的参数 |
| `JSON` | 一等类型，用 `JSON_QUERY` / `JSON_VALUE` 访问；见下文 |
| `GEOGRAPHY` | GIS 类型；因不可排序，在列剖析中投影为 `NULL` |
| `BIGNUMERIC` | 高精度精确数值；适配器为 BigQuery 注册了该类型 |
| `TIMESTAMP` / `DATETIME` | 时刻与无时区的本地时间；`seconds_between` 需要 `TIMESTAMP` |
| `INT64`、`FLOAT64`、`BOOL`、`STRING`、`BYTES`、`DATE`、`TIME` | 标准标量类型族 |

## JSON 访问

BigQuery 的 JSON 提取拼写与某些引擎不同。方言把 `->` / `->>` 操作分别回答为
`JSON_QUERY` 与 `JSON_VALUE`：

```python
# column -> '$.a.b'     -> JSON_QUERY(`payload`, '$.a.b')
# column ->> '$.a.b'    -> JSON_VALUE(`payload`, '$.a.b')
```

路径是 SQL 字符串字面量，绑定参数不会拼接进去。参见
[查询 BigQuery 原生类型](../querying/bigquery_types.md)。

## 标识符用反引号

每个标识符都用反引号包裹，内部的反引号写成两个：

```python
# `My Dataset`.`orders`
# `app``x`.`orders`
```

渲染器不会折叠大小写；dataset 名默认区分大小写，因此 `` `app` `` 与 `` `APP` `` 是两个不同的
dataset。参见 [Schema 命名空间与 dataset](schema_namespace.md)。

## 生成键

BigQuery 没有 `AUTO_INCREMENT`。要生成服务端键，请使用 identity 列
（`GENERATED ... AS IDENTITY`）；普通的自增标记会被拒绝。生成列总是存储的，不支持 `VIRTUAL`。
