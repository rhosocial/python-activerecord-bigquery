# 限制与不支持的功能

## 执行模型

每条查询都作为**作业**运行，结果从作业中读取。同步与原生异步后端都走这条路径；两者的区别只是
客户端等待与读取结果的方式，不是另一套 SQL 生成器。设置 `api_endpoint` 会让同步后端走 REST
快速路径，供模拟器使用。

## 命名空间限制

* 没有会话级当前 dataset。`get_current_schema()` 抛 `UnsupportedFeatureError`；请显式传入
  `schema_name`。
* 表达式层只携带**一级**命名空间，即 dataset。`TableExpression`、`Column` 与通配符都没有 project
  字段。传给 `schema_name` 的点分值会留在单个引号标识符里；三级路径要写进 `name`。参见
  [只携带 dataset 层级](../modeling/schema_namespace.md)。
* 列永不被 dataset 限定；列上有 dataset 却没有表名时报错。

## 被拒绝的语句与特性

| 特性 | 原因 / 替代方式 |
|---|---|
| `RETURNING` | BigQuery 无此子句；用单独的 `SELECT` 或 `MERGE` |
| `EXPLAIN` / `EXPLAIN PLAN` | 方言不支持 |
| `AUTO_INCREMENT` | 不是 GoogleSQL；用 `GENERATED ... AS IDENTITY` |
| `VIRTUAL` 生成列 | BigQuery 生成列总是存储的 |
| `CREATE VIEW ... IF NOT EXISTS`、`DROP VIEW IF EXISTS` | 用 `CREATE OR REPLACE VIEW` |
| 通过表达式层执行 `DROP SCHEMA ... CASCADE` | 需要手写语句 |
| `DROP TABLE ... CASCADE` / `RESTRICT` | 被拒绝 |
| `WITH DATA` / `WITH NO DATA` | 相关语法中没有该子句 |
| `MATERIALIZED` CTE 提示 | GoogleSQL 自行决定物化 |
| 二级索引 | 没有用户可见的索引；聚簇/搜索索引是独立资源 |
| 序列 | 本后端没有序列 DDL |
| 外键、触发器 | 没有目录视图；读取器返回空，而不是编造数据 |
| 独立的用户自定义类型 | 内省没有类型目录族 |

拒绝表现为带建议的 `UnsupportedFeatureError`；CLI 对探针回答 `False` 的族直接拒绝，而不是执行
服务会拒绝的语句。

## 数据类型边界

BigQuery 会对不可排序或不可分组的列（`ARRAY`、`STRUCT`、`JSON`、`GEOGRAPHY`、`RANGE`）拒绝
`MIN` / `MAX` 与 `COUNT(DISTINCT ...)`。内省的处理方式是把这些槽位投影为 SQL `NULL`，而不是让
整个剖析失败。参见
[不透明类型按名称投影为 `NULL`](../introspection/README.md)。
