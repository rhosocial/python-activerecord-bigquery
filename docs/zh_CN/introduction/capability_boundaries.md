# 能力边界

BigQuery 是托管的列式数仓。一些在 OLTP 数据库里司空见惯的事情在这里没有对应物，本后端会直接
说明，而不是生成服务会拒绝的 SQL。本页是一张地图，细节在对应章节里。

## 支持

| 领域 | 行为 |
|---|---|
| 查询 | `SELECT`、CTE（含递归）、窗口函数、`QUALIFY`、集合运算、`MERGE`、upsert |
| JSON | 一等 `JSON` 类型，使用 `JSON_QUERY` / `JSON_VALUE` 访问 |
| 数组 | 支持 `ARRAY`；支持嵌套 `STRUCT` / `RECORD` |
| DDL | `CREATE` / `DROP` / `ALTER TABLE`、`CREATE SCHEMA`（dataset）、视图、物化视图、克隆与复制 |
| 视图 | 在不支持 `IF NOT EXISTS` 的地方提供 `CREATE OR REPLACE VIEW` |
| Identity | 用 `GENERATED ... AS IDENTITY` 生成键；普通的 `AUTO_INCREMENT` 不是 GoogleSQL |
| 事务 | 会话级 `BEGIN` / `COMMIT` / `ROLLBACK` |
| 异步 | 原生异步后端，API 与同步后端一致 |
| 内省 | `INFORMATION_SCHEMA` 目录，外加三个按量计费的数据族 |

## 拒绝，而非模拟

| 特性 | 替代方式 |
|---|---|
| DML 的 `RETURNING` | 没有该子句；改用单独的 `SELECT` 或 `MERGE` |
| 会话级当前 schema | `get_current_schema()` 抛错；显式传入 dataset |
| `AUTO_INCREMENT` | 被拒绝；改用 identity 列 |
| `VIRTUAL` 生成列 | 被拒绝；BigQuery 生成列总是存储的 |
| `CREATE VIEW ... IF NOT EXISTS`、`DROP VIEW IF EXISTS` | 被拒绝；改用 `CREATE OR REPLACE VIEW` |
| 通过表达式层执行 `DROP SCHEMA ... CASCADE` | 被拒绝；需要手写语句 |
| 二级索引 | 内省没有索引族；聚簇与搜索索引是独立资源 |
| `EXPLAIN` / `EXPLAIN PLAN` | 被拒绝 |
| 序列 | 本后端没有序列 DDL |
| 外键、触发器 | 没有目录视图；读取器返回空，而不是编造另一端 |

拒绝通常以带建议的 `UnsupportedFeatureError` 形式出现，而且往往在发送语句之前就发生——CLI 与
表达式层会先查询 dialect 的 `supports_*` 探针。

## 两个容易踩坑的后果

**每条语句都是一个作业。** 查询作为 BigQuery 作业运行，结果从作业中读取；普通 CRUD 看不到这一点，
但它关系到延迟与模拟器配置方式。

**元数据免费，数据行不免费。** `INFORMATION_SCHEMA` 的目录读取很便宜，但列剖析、取值采样与连接
覆盖率这三个数据族会扫描整表并按读取字节计费。参见
[数据库内省](../introspection/README.md)。
