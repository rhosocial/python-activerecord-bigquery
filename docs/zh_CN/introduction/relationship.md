# 与核心库的关系

本后端是插件，不是分支。`rhosocial-activerecord` 提供模型声明、查询构造器与表达式树；
BigQuery 包提供方言、连接配置、存储后端与元数据读取器，使这些可移植对象能在 BigQuery 上运行。

## 核心库提供什么

* `ActiveRecord` 模型、`FieldProxy`、`ActiveQuery` 与表达式节点
* `ConnectionConfig` 基类及后端组合进自身 config 的 mixin
* 后端与方言协议、类型适配器机制、内省契约
* 解释以上全部内容的文档——参见[核心库文档](https://github.com/rhosocial/python-activerecord/tree/main/docs/en_US)

这些都不在本章重复。本页出现“核心层渲染……”时，指的是该行为定义在核心库、此处只是消费它。

## 本包增加什么

| 层 | BigQuery 实现 |
|---|---|
| 方言 | `BigQueryDialect`——反引号标识符、`@param` 风格绑定、GoogleSQL 拼写 |
| 配置 | `BigQueryConnectionConfig`——project、dataset、location、凭据、API endpoint |
| 后端 | `BigQueryBackend`（同步）与 `AsyncBigQueryBackend`（原生异步） |
| 事务 | 会话级 `BEGIN` / `COMMIT` / `ROLLBACK` 管理器，同步与异步各一份 |
| 类型 | `BigQueryStruct`、`BigQueryArray`、`BigQueryJSON` 及类型适配器 |
| 表达式 | BigQuery 专有的内省与物化视图语句 |
| 元数据 | 基于 `INFORMATION_SCHEMA` 的 `BigQueryIntrospector` / `AsyncBigQueryIntrospector` |
| CLI | `python -m rhosocial.activerecord.backend.impl.bigquery` |

## 两条值得注意的边界

**表达式层只携带一级命名空间。** `TableExpression`、`Column` 与通配符节点接受
`schema_name`（dataset），但没有 project 字段。三级名称只有把点分路径写进 `name` 才能达到。
完整规则见 [Schema 命名空间与 dataset](../modeling/schema_namespace.md)。

**内省探针回答的是服务，而不是版本。** BigQuery 不通过 SQL 暴露服务器版本，因此方言不会像
自托管引擎那样做版本协商；探针给出的是本后端声明的答案。参见
[数据库内省](../introspection/README.md)。

## 以命名空间包方式安装

两个发行版都装在 `rhosocial.activerecord` 命名空间下。参见[安装指南](../installation/installation.md)。
