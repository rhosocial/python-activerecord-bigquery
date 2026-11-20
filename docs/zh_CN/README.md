# rhosocial-activerecord BigQuery 后端文档

BigQuery 后端是 [rhosocial-activerecord](https://github.com/rhosocial/python-activerecord)
的 Google BigQuery 后端实现。它使用 `google-cloud-bigquery` 客户端，同时提供同步后端与
**原生**异步后端，并明确说明 BigQuery 云数仓语义与可移植模型之间的差异：本库的 `schema_name`
对应 **dataset**，列引用永不携带它，也不存在会话级的当前 dataset 可供回退。

本系列章节只讲述**本后端**。模型 API、查询构造器与方言无关的表达式节点属于核心库，此处不再重复。

## 目录 (Table of Contents)

1. **[简介](introduction/README.md)**
    * **[概述](introduction/README.md)**：本后端的职责与 BigQuery 特有事实
    * **[与核心库的关系](introduction/relationship.md)**：职责划分
    * **[支持版本](introduction/supported_versions.md)**：Python 3.10–3.14、客户端与特性级别
    * **[能力边界](introduction/capability_boundaries.md)**：支持什么、拒绝什么

2. **[安装](installation/README.md)**
    * **[安装指南](installation/installation.md)**：包与凭据
    * **[连接配置](installation/configuration.md)**：project、dataset、location、凭据与模拟器设置

3. **[快速入门](getting_started/README.md)**
    * **[快速开始](getting_started/quick_start.md)**：配置、连接并渲染第一条查询

4. **[建模](modeling/README.md)**
    * **[Schema 命名空间与 dataset](modeling/schema_namespace.md)**：声明 `__schema_name__`、
      反引号标识符、dataset 感知的命名、dataset DDL 与物化视图
    * **[BigQuery 字段类型](modeling/field_types.md)**：STRUCT、ARRAY、JSON、GEOGRAPHY、
      BIGNUMERIC 与时间类型

5. **[查询](querying/README.md)**
    * **[查询 BigQuery 原生类型](querying/bigquery_types.md)**：反引号标识符、嵌套类型、JSON 访问
    * **[时间表达式（`seconds_between`）](querying/seconds_between.md)**：
      `TIMESTAMP_DIFF(end, start, MILLISECOND) / 1000.0`、参数顺序、绑定顺序、符号以及一毫秒精度上限

6. **[DDL](ddl/README.md)**
    * **[BigQuery DDL 要点](ddl/README.md)**：dataset、视图、identity 列、OPTIONS 与被拒绝的子句

7. **[能力](capabilities/README.md)**
    * **[事务与 DML](capabilities/transactions.md)**：会话级事务、无 `RETURNING`、影响行数
    * **[限制与不支持的功能](capabilities/limits.md)**：查询作业、单级命名空间与被拒绝的特性

8. **[内省](introspection/README.md)**
    * **[数据库内省](introspection/README.md)**：从 `INFORMATION_SCHEMA` 回答什么、三个数据族背后的
      计费扫描、例程（routines）、两套 `COLUMNS` 投影、模拟器回退，以及十五个 CLI 类型

9. **[命令行](cli/README.md)**
    * **[CLI 用法](cli/README.md)**：`python -m rhosocial.activerecord.backend.impl.bigquery`

10. **[测试](testing/README.md)**
    * **[测试配置](testing/README.md)**：`goccy/bigquery-emulator`、匿名凭据与模拟器特有差异

## 关键结论速览

| 问题 | 结论 |
|---|---|
| `schema_name` 指什么？ | dataset |
| 限定表渲染为 | `` `app`.`orders` `` |
| 列引用 | 永不带 dataset：`` `orders`.`id` `` |
| 取别名之后 | `` `o`.`id` `` |
| 当前 schema | 不存在。BigQuery 没有会话级命名空间，`get_current_schema()` 抛 `UnsupportedFeatureError` |
| `CREATE SCHEMA` / `DROP SCHEMA` | 支持（即 dataset DDL） |
| schema DDL 的 `CASCADE` / `AUTHORIZATION` | 不支持 |
| 异步 | 原生，使用客户端自身的异步支持 |
| `RETURNING` | 不支持；用单独的 `SELECT` 或 `MERGE` |

## 相关文档

- **[Schema 命名空间（核心库指南）](https://github.com/rhosocial/python-activerecord/tree/main/docs/en_US/modeling/schema_namespace.md)**：
  所有后端共同遵循的、与方言无关的规则

## 可运行示例

仓库根目录的 `examples/` 目录提供示例：
[`named_connections`](../../examples/named_connections/example.py)、
[`named_procedures`](../../examples/named_procedures/example.py)、
[`named_queries`](../../examples/named_queries/example.py)。

---

> ⚠️ **依赖说明**：本后端依赖核心库 `rhosocial-activerecord`，请与核心库一并安装，
> 不要单独安装本后端。
