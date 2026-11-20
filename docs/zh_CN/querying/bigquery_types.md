# 查询 BigQuery 原生类型

[BigQuery 字段类型](../modeling/field_types.md)之后的问题是：当模型带有嵌套列或 BigQuery 原生列时，
标识符与相关查询会如何表现？核心查询 API 本身属于核心库文档。

## 反引号标识符

BigQuery 用反引号包裹标识符，每段一对：

```python
TableExpression(d, "orders", schema_name="app").to_sql()[0]
# `app`.`orders`

TableExpression(d, "orders", schema_name="app", alias="o").to_sql()[0]
# `app`.`orders` AS `o`
```

内部的反引号通过写两次来转义，因此 `` app`x `` 会作为单个标识符 `` `app``x` `` 保留。
`need_quote=False` 会走不引号分支，并对保留字发出警告。渲染器保留大小写。

## dataset 感知的命名

dataset 限定 `FROM` 中的范围，然后到此为止：

```python
Order.query().select(Order.c.id).to_sql()[0]
# SELECT `orders`.`id` FROM `app`.`orders`
```

列引用是表名或别名加列名——永远不是 dataset。列上若同时有表名与 dataset，dataset 会被丢弃
（`FROM` 已经命名了关系）；列上有 dataset 却**没有**表名时会抛 `UnsupportedFeatureError`，因为
BigQuery 没有这种形式。取别名后前缀变成别名（`` `o`.`id` ``）。

跨 dataset 的 join 不需要额外配置：每一侧各自限定自己的范围，join 条件保持两级。跨 **project**
的名称不在表达式层携带。全部规则及每种情况的 SQL 见
[Schema 命名空间与 dataset](../modeling/schema_namespace.md)。

## STRUCT 与 ARRAY

嵌套字段通过常规的 GoogleSQL 字段访问与 `UNNEST` 读取，表达式使用同样的反引号标识符策略：

```sql
SELECT `o`.`address`.`city` FROM `app`.`orders` AS `o`;
SELECT `item` FROM `app`.`orders`, UNNEST(`items`) AS `item`;
```

`STRUCT` 字段访问是多了一级路径的列引用，不是 dataset 限定。内省无法测量嵌套类型的边界：
`ARRAY` 与 `STRUCT` 列在列剖析中投影为 `NULL`，而不是交给 `MIN` / `MAX`。参见
[不透明类型按名称投影为 `NULL`](../introspection/README.md)。

## JSON

BigQuery 的 `JSON` 类型用 `JSON_QUERY` 取文档，用 `JSON_VALUE` 取文本：

```python
# `payload` -> '$.a.b'   -> JSON_QUERY(`payload`, '$.a.b')
# `payload` ->> '$.a.b'  -> JSON_VALUE(`payload`, '$.a.b')
```

路径作为字面量发出，由方言负责引号与转义；路径为空时默认为 `$`。这里没有 `JSON_EXTRACT`。
和 `ARRAY`、`STRUCT` 一样，`JSON` 列无法在数据内省族中分组或求边界。

## GEOGRAPHY

`GEOGRAPHY` 是 BigQuery 的一等类型。它在内省聚合中不可排序、不可分组，所以剖析时只统计空值，
去重数与上下界留为 `None`。对这种列做取值采样会被服务器以点名列名的错误拒绝——这是诚实的答案。

## 时间

耗时表达式请使用 `TIMESTAMP` 操作数。BigQuery 也有无时区的 `DATETIME` 及对应的
`DATETIME_DIFF`；`seconds_between` 节点明确写的是时刻形式。参见
[时间表达式](seconds_between.md)。
