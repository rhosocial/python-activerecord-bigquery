# BigQuery DDL 要点

DDL 最能体现云数仓模型的特点。关于 dataset 命名的权威、逐例说明见
[Schema 命名空间与 dataset](../modeling/schema_namespace.md)；
本页只是简短索引。

## dataset 就是 schema

`CREATE SCHEMA` / `DROP SCHEMA` 创建和删除的是 **dataset**：

```python
CreateSchemaStatement(d, "sales").to_sql()[0]
# CREATE SCHEMA `sales`

CreateSchemaStatement(d, "sales", if_not_exists=True).to_sql()[0]
# CREATE SCHEMA IF NOT EXISTS `sales`
```

`AUTHORIZATION` 被拒绝；`CASCADE` 即使 BigQuery 自身语法接受，也会在表达式层被拒绝——删除
非空 dataset 需要手写语句。构建 DDL 时不会参考连接配置里的 dataset；迁移必须在语句上写明 dataset。

## 表与视图

* 支持 `CREATE TABLE`、`DROP TABLE IF EXISTS`、`ALTER TABLE ADD/DROP COLUMN IF NOT EXISTS/EXISTS`
  与 `TRUNCATE TABLE`。
* 支持 `CREATE OR REPLACE TABLE` 与 `CREATE TABLE ... LIKE` / `... CLONE`。
* BigQuery 没有 `COMMENT` 关键字；行内表注释渲染为 `OPTIONS(description='...')`。
* 视图使用 `CREATE OR REPLACE VIEW`：`CREATE VIEW ... IF NOT EXISTS` 与 `DROP VIEW IF EXISTS`
  都会被拒绝。
* `AUTO_INCREMENT` 不是 GoogleSQL；请改用 `GENERATED ... AS IDENTITY`。生成列总是存储的，
  不支持 `VIRTUAL`。
* 本后端没有实现序列。

## 物化视图

物化视图用 `MaterializedView` 对象命名目标，其中带 dataset（可选 project）。刷新是创建时的选项，
通过 `ALTER MATERIALIZED VIEW ... SET OPTIONS(...)` 修改——没有 `REFRESH MATERIALIZED VIEW`。
副本语句接收两个视图对象，因此副本与源可以位于不同 dataset。参见
[物化视图](../modeling/schema_namespace.md)。

## 索引与约束

BigQuery 没有二级索引。`CREATE INDEX` / `DROP INDEX` 仍可为语句层渲染，语句上的 `schema_name`
限定的是**索引名**而非表名；索引内省与全文索引支持都回答 `False`。聚簇与搜索索引是独立的资源，
表达式层没有对其建模。
