# 事务与 DML

## 会话级事务

BigQuery 的事务依附于会话。后端的事务管理器用 `BEGIN TRANSACTION` 开启，成功时提交，出错时回滚：

```python
with backend.transaction():
    # 语句在 BigQuery 会话内执行
    ...
```

异步后端有对应的异步管理器。`isolation_level` 为了 API 兼容而接受，但不会映射到任何 BigQuery
子句。保存点由管理器用计数器维护，而不是服务器端的保存点语句。

> **模拟器注意**：若某个 endpoint 拒绝 `ROLLBACK`（模拟器可能如此），会记录一条警告；**原始**
> 异常仍会照常抛出，因此回滚失败不会掩盖导致错误的根因。

## 没有 `RETURNING`

BigQuery 的 `INSERT` / `UPDATE` / `DELETE` 没有 `RETURNING` 子句，渲染出的 DML 不返回行。要取回
受影响的行，可以用相同谓词另发一条 `SELECT`，或把操作写成 `MERGE`。这是服务限制，不是可开关的设置。

## 影响行数

普通 endpoint 上，DML 结果携带作业的影响行数。模拟器模式下（`api_endpoint` 已设置），模拟器不
报告该数字，于是 `update()` / `delete()` 会先用相同谓词执行 `SELECT COUNT(*)` 来补算。这个预统计
用 `options.schema_name` 通过语句本身的限定名渲染器来限定——这也是要为每个模型声明
`__schema_name__` 的又一个理由。参见
[DDL 需要自己的 dataset](../modeling/schema_namespace.md)。

## 变更语句的谓词不带 dataset

dataset 限定 DML 语句的目标表：

```python
UpdateStatement(
    d, TableExpression(d, "users", schema_name="app"), {"name": Parameter(d, "x")}
).to_sql()
# ('UPDATE `app`.`users` SET `name` = ?', ('x',))
```

由模型字段构造的谓词只带表名和列名，不带 dataset。参见
[列永不携带 dataset](../modeling/schema_namespace.md)。
