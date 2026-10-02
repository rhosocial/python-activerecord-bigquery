# rhosocial-activerecord BigQuery 后端文档

BigQuery 后端是 [rhosocial-activerecord](https://github.com/rhosocial/python-activerecord)
的 Google BigQuery 后端实现。它使用 `google-cloud-bigquery` 的 REST 驱动。在 BigQuery 上，
本库的 `schema_name` 对应的是 **dataset**；与其它所有后端不同，列引用永远不带 dataset。

## 目录 (Table of Contents)

- **[Schema 命名空间](bigquery_specific_features/schema_namespace.md)**：声明
  `__schema_name__`、列引用为何永不带 dataset、不存在会话级当前 dataset 这一事实，
  以及单级限定的局限

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

## 相关文档

- **[Schema 命名空间（核心库指南）](https://github.com/rhosocial/python-activerecord/tree/docs/docs/modeling/schema_namespace.md)**：
  所有后端共同遵循的、与方言无关的规则

---

> ⚠️ **依赖说明**：本后端依赖核心库 `rhosocial-activerecord`，请与核心库一并安装，
> 不要单独安装本后端。