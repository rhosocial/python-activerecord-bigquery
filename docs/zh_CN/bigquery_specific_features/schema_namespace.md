# docs/zh_CN/bigquery_specific_features/schema_namespace.md

# BigQuery Schema 命名空间

> 本文只讲本后端特有的部分：`schema_name` 在这里指向什么、为什么 BigQuery 的列引用
> 永远不带 dataset、取了表别名之后用什么去标识一个范围、为什么没有「当前
> dataset」可以退让、三段式名字里表达式层只带得了哪一级，以及 dataset 相关的 DDL
> 与物化视图语句各自怎么使用这个值。
>
> 模型层的通用部分——怎么在模型上声明 `__schema_name__`、dataset 何时进入 SQL、
> DDL 的边界、各后端支持矩阵——由核心库（`python-activerecord` 仓库）的
> `docs/modeling/schema_namespace.md` 讲，见
> [`docs/zh_CN/modeling/schema_namespace.md`][core-zh]。

[core-zh]: https://github.com/rhosocial/python-activerecord/tree/main/docs/zh_CN/modeling/schema_namespace.md

## 本文结论的验证方式

文中每一段 SQL 都由 `BigQueryDialect` 配合表达式层渲染得出，没有连接真实服务端：

```
PYTHONPATH=src .venv3.14-ubuntu26.04/bin/python
```

这条命令假定装好的 core 就是本文描述的那一份。若不是，两段 import 都要钉在同一分支上，
且后端在前：

```
PYTHONPATH=<core-worktree>/src:src <venv>/bin/python
```

`BigQueryDialect` 以元组形式接收版本号，`(3, 0, 0)` 是默认值，本页所有示例用的
都是它。模型层的示例是把两个模型配置到
`BigQueryConnectionConfig(project="test", dataset="app")` 上之后读 `to_sql()` 得到的。

描述服务端而非渲染器的部分——不加限定的表名会怎样、三段式名字是否被接受、
`@@dataset_id` 的语义——来自 BigQuery 自身的文档。本仓库没有可用的 BigQuery
实例；测试套件使用的 `goccy/bigquery-emulator` 在撰写本页时也未运行。凡属此类
内容均在正文中标明。本文对应 `rhosocial-activerecord-bigquery` 1.0.0.dev1。

## `schema_name` 指向 dataset，而列引用不带它

这一点要先说清楚，因为它同时决定了 `schema_name` 的含义，以及它在生成 SQL 里
出现的范围。

`BigQueryDialect` 实现了核心库的 `SchemaSupport` 协议，凡是核心库期待出现
`schema_name` 的地方都能接受，`supports_schema()` 的返回值是 `True`：

```python
dialect.supports_schema()                # True
dialect.supports_create_schema()         # True
dialect.supports_drop_schema()           # True
dialect.supports_schema_if_not_exists()  # True
dialect.supports_schema_if_exists()      # True
dialect.supports_schema_authorization()  # False
dialect.supports_schema_cascade()        # False
```

这个值指的是 **dataset**，也就是 BigQuery 用来装表、视图与其他资源的容器。
`CREATE SCHEMA` 的参考文档把这一点写在明处，因为这个词本身容易引起误解：

> **Key Point:** This SQL statement uses the term SCHEMA to refer to a logical
> collection of tables, views, and other resources. The equivalent concept in
> BigQuery is a dataset. In this context, SCHEMA does not refer to BigQuery table
> schemas.
>
> —— [`CREATE SCHEMA` 语句][ddl-create-schema]

[ddl-create-schema]: https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language#create_schema_statement

这段引文同时排除了这个词的第二种读法。在 BigQuery 自己的词汇里，「schema」也指
单张表的列定义，两种含义在服务端并存；本库里的 `schema_name` 始终是前一种，
不会是后一种。

dataset 是查询用来指名对象时所在的容器。表在 dataset 里，dataset 在 project 里，
同一个 project 下的各个 dataset 互不相关：`` `app`.`orders` `` 与
`` `crm`.`orders` `` 是两张恰好同名的表。

### 渲染

标识符用反引号引用，每一段各自成为一个带反引号的标识符：

| 表达式 | SQL |
|---|---|
| `TableExpression(d, "orders", schema_name="app")` | `` `app`.`orders` `` |
| `TableExpression(d, "orders")` | `` `orders` `` |
| `TableExpression(d, "orders", schema_name="app", alias="o")` | `` `app`.`orders` AS `o` `` |


`format_identifier` 把值里自带的反引号写成两个，因此本该提前闭合引用的字符仍留在
同一个标识符内部：

```python
TableExpression(d, "orders", schema_name="app`x").to_sql()[0]
# `app``x`.`orders`

TableExpression(d, "orders", schema_name="My Dataset").to_sql()[0]
# `My Dataset`.`orders`
```

也可以有意地去掉 dataset 那一段的引号：

```python
TableExpression(d, "orders", schema_name="app", schema_need_quote=False).to_sql()[0]
# app.`orders`
```

`schema_need_quote=False` 以及同角色的 `name_need_quote`、`alias_need_quote` 会走
不加引号的分支；在保留字上再设 `need_quote=False`，还会额外发出
`IdentifierQuotingWarning`。

**渲染器从不折叠大小写。** `schema_name` 按写下来的大小写原样输出，而在 BigQuery
上，服务端比较的正是这个大小写：

> Dataset and table names are case-sensitive unless the
> [`is_case_insensitive`][case-insensitive] option is set to `TRUE`.
>
> —— [Case sensitivity][lexical-case]

[lexical-case]: https://cloud.google.com/bigquery/docs/reference/standard-sql/lexical#case_sensitivity
[case-insensitive]: https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language#schema_option_list

因此在没有开启该选项的 dataset 里，`` `app` `` 与 `` `APP` `` 是两个不同的名字；
以 `my_dataset` 建出来的 dataset，不会被声明了
`__schema_name__ = "My_Dataset"` 的模型找到。

### 列引用永远不带 dataset

本库里其它后端都不是这样：未被取别名的范围会把命名空间一路带进针对它构造的列
引用，PostgreSQL 从 `FROM "app"."orders"` 渲染出 `"app"."orders"."id"`。BigQuery
在列上根本不渲染 dataset，这是本后端与这一族其余后端之间最大的一处差别：

```python
Order.query().select(Order.c.id).to_sql()[0]
# SELECT `orders`.`id` FROM `app`.`orders`

Order.query().where(Order.c.id > 1).to_sql()[0]
# SELECT * FROM `app`.`orders` WHERE `orders`.`id` > ?

Order.query().group_by(Order.c.user_id).order_by(Order.c.id).limit(5).to_sql()[0]
# SELECT * FROM `app`.`orders` GROUP BY `orders`.`user_id`
#   ORDER BY `orders`.`id` ASC LIMIT ?

Order.query().group_by(Order.c.user_id).having(Order.c.total > 10).to_sql()[0]
# SELECT * FROM `app`.`orders` GROUP BY `orders`.`user_id`
#   HAVING `orders`.`total` > ?
```

dataset 限定 `FROM` 里的范围，到此为止。列引用是「表名或别名 + 列名」，共两段；
而 BigQuery 文档给出的表名写法只有 `mytable`、`dataset.mytable` 与
`project.dataset.mytable` 三种，列前缀里不会出现 dataset：

> `table_name`
>
> The name (optionally qualified) of an existing table.
>
> ```
> SELECT * FROM Roster;
> SELECT * FROM dataset.Roster;
> SELECT * FROM project.dataset.Roster;
> ```
>
> —— [`FROM` 子句][from-clause]

[from-clause]: https://cloud.google.com/bigquery/docs/reference/standard-sql/query-syntax#from_clause

`BigQueryDialect` 的做法是覆盖 `format_column`，不让核心渲染器去限定列；
`format_wildcard` 对 `table.*` 做的是同一件事：

```python
Column(d, "id", table="orders").to_sql()[0]
# `orders`.`id`

WildcardExpression(d, table="orders").to_sql()[0]
# `orders`.*

WildcardExpression(d).to_sql()[0]
# *
```

`format_wildcard` 是唯一一个既不渲染 `schema_name` 也不校验它的格式化方法，空串
也一样放过：

```python
WildcardExpression(d, table="orders", schema_name="app").to_sql()[0]
# `orders`.*

WildcardExpression(d, table="orders", schema_name="").to_sql()[0]
# `orders`.*
```

输出并没有因此少掉什么：通配符本来就不带 dataset。值得记下的是它与
`format_column` 的不对称——后者会拒绝空串。

覆盖带来的另外两点后果也需要讲清楚，因为它们与核心渲染器不同：

- **列上带了 dataset 又带了 table 时，dataset 不出现在输出里，而这是正确的。** 这个值
  仍会被校验——列上的空串照样抛异常——但 dataset 是冗余而非丢失，因为 FROM 子句已经
  指明了它所属的关系：

  ```python
  Column(d, "id", table="o", schema_name="app").to_sql()[0]
  # `o`.`id`
  ```

- **列上带了 dataset 而没有 table 时，报错而不是丢弃。** 此时没有任何关系可供这个
  命名空间去限定，诚实的做法只有两个：渲染出来，或者拒绝。BigQuery 两者都做不到。
  这种情况过去只发一条 `UserWarning`——测试照样全绿，dataset 却悄悄没了。现在改为
  抛异常：

  ```python
  Column(d, "id", schema_name="app").to_sql()[0]
  # UnsupportedFeatureError: 'bigquery' dialect does not support
  # schema-qualified column references. Suggestion: column 'id' carries
  # schema_name='app' but no table, and bigquery qualifies a column by its
  # relation only; put the dataset on the FROM relation, or pass table=... as well
  ```

  同一份模型定义同时服务 PostgreSQL 与 BigQuery 仍然做得到：把 dataset 声明在模型
  上，让它落到 FROM 的关系上，而不是声明在单个列上。

以上两条同源于一个声明出来的能力 `supports_column_namespace_qualification()`，
它的返回值是 `False`：BigQuery 只通过关系来限定列，从不用命名空间限定列。

列*别名*不受影响：别名属于输出列，不属于范围，因此和不加限定时一样渲染在列上。

```python
Order.query().select(Order.c.id.as_("x")).to_sql()[0]
# SELECT `orders`.`id` AS `x` FROM `app`.`orders`
```

### 别名

既然 dataset 从来到不了列上，别名也就没有改变限定方式：范围照旧带自己的 dataset，
列前缀换成别名。BigQuery 这里是更简单的一种情形——在 PostgreSQL 与 SQL Server
上，带 schema 限定的别名范围引用是语法错误。

```python
TableExpression(d, "orders", schema_name="app", alias="o").to_sql()[0]
# `app`.`orders` AS `o`

Order.query().select(Order.c.with_table_alias("o").id).to_sql()[0]
# SELECT `o`.`id` FROM `app`.`orders`
```

模型层的范围别名只可能来自 join。范围别名与列访问器用同一个名字构造，并与
`join(..., alias=...)` 配对：

```python
Order.query().join(
    User, on=Order.c.user_id == User.c.with_table_alias("u").id, alias="u"
).select(Order.c.id, User.c.with_table_alias("u").name).to_sql()[0]
# SELECT `orders`.`id`, `u`.`name` FROM `app`.`orders`
#   JOIN `crm`.`users` AS `u` ON `orders`.`user_id` = `u`.`id`
```

自连接要给两侧都取别名：

```python
Order.query().join(
    Order,
    on=Order.c.with_table_alias("c").id == Order.c.with_table_alias("p").user_id,
    alias="p",
).select(Order.c.with_table_alias("c").id, Order.c.with_table_alias("p").id).to_sql()[0]
# SELECT `c`.`id`, `p`.`id` FROM `app`.`orders`
#   JOIN `app`.`orders` AS `p` ON `c`.`id` = `p`.`user_id`
```

### 跨 dataset 的 join

每一侧各自限定自己的范围，因此一条语句横跨两个 dataset 不需要额外配置：

```python
Order.query().join(User, on=Order.c.user_id == User.c.id).select(
    Order.c.id, User.c.name
).to_sql()[0]
# SELECT `orders`.`id`, `users`.`name` FROM `app`.`orders`
#   JOIN `crm`.`users` ON `orders`.`user_id` = `users`.`id`
```

join 条件两侧都不带 dataset，正因如此整条语句都留在 BigQuery 的两段式列引用
形式之内。上限是跨 **dataset**：跨 **project** 的 join 需要两个范围都带上 project，
而表达式层不带这一级，见
[表达式层只带 dataset 一级](#表达式层只带-dataset-一级)。

### 集合操作

`UNION`、`INTERSECT` 与 `EXCEPT` 本身不指名任何对象，因此没有可限定的东西。
每个分支保留自己的 dataset：

```python
Order.query().select(Order.c.id).union(User.query().select(User.c.id)).to_sql()[0]
# SELECT `orders`.`id` FROM `app`.`orders`
#   UNION DISTINCT SELECT `users`.`id` FROM `crm`.`users`
```

那个显式的 `DISTINCT` 关键字来自本方言的渲染方式：它要么写 ` ALL`，要么写
` DISTINCT`，而 BigQuery 的集合操作文法两种拼法都接受。

> ```
> query_expr
>   [ { INNER | [ { FULL | LEFT } [ OUTER ] ] } ]
>   { UNION { ALL | DISTINCT } | INTERSECT DISTINCT | EXCEPT DISTINCT }
>   ...
> ```
>
> —— [Set operators][set-operators]

[set-operators]: https://cloud.google.com/bigquery/docs/reference/standard-sql/query-syntax#set_operators

### CTE

CTE 是给余下这条查询起名字，不是给数据库起名字，因此它自己的名字是裸的。里面的
查询仍然带着模型的 dataset：

```python
inner = QueryExpression(
    dialect=d,
    select=[Column(d, "id", table="orders", schema_name="app")],
    from_=[TableExpression(d, "orders", schema_name="app")],
)
main = QueryExpression(
    dialect=d,
    select=[Column(d, "id", table="recent_orders")],
    from_=[TableExpression(d, "recent_orders")],
)

WithQueryExpression(d, [CTEExpression(d, "recent_orders", inner)], main).to_sql()[0]
# WITH `recent_orders` AS (SELECT `orders`.`id` FROM `app`.`orders`)
#   SELECT `recent_orders`.`id` FROM `recent_orders`
```

与这一族中的某些后端不同，本后端的查询构造器能走到这条路径：
`supports_basic_cte()` 返回 `True`，因此构造 `CTEQuery` 不会抛异常。

裸名也正是 BigQuery 想要的写法。`WITH` 子句会在余下这条查询里遮蔽同名的常驻表，
*除非*该表名被限定，所以给 CTE 引用加上限定反而会改变读取的对象。

## 在模型上声明 dataset

```python
from typing import ClassVar, Optional

class Order(ActiveRecord):
    __table_name__ = "orders"
    __schema_name__ = "app"                 # -> `app`.`orders`
    c: ClassVar[FieldProxy] = FieldProxy()

    id: Optional[int] = None
    user_id: Optional[int] = None
    total: Optional[float] = None
```

`__schema_name__` 可选，不写就是 `None`，即不加限定。在 BigQuery 上这个默认值
恰恰是要避开的，理由不是取舍问题，见
[没有会话级的当前 dataset](#没有会话级的当前-dataset)。

dataset 只被读一次，经由 `schema_name()`，并在构造各个范围表达式时传下去。
`Order.c.field` 在表达式构造时就把它固定下来，而不是查询运行时才读，因此事后
修改 `__schema_name__` 不会改写已经存在的条件，需要重新构造。绑定的完整规则见
核心库文档。

没有 `__schema_name__` 的模型渲染出的是不带限定的范围：

```python
PlainOrder.query().select(PlainOrder.c.id).to_sql()[0]
# SELECT `plain_orders`.`id` FROM `plain_orders`
```

`SELECT *` 不需要限定，渲染时也不加：

```python
Order.query().to_sql()[0]
# SELECT * FROM `app`.`orders`
```

不要把 dataset 并进 `__table_name__`。标识符是作为一个整体被引用的，结果是一张
名字里含点号的表：

```python
class Dotted(ActiveRecord):
    __table_name__ = "app.orders"

Dotted.query().select(Dotted.c.id).to_sql()[0]
# SELECT `app.orders`.`id` FROM `app.orders`
```

## DDL 各自带自己的 dataset

`__schema_name__` 决定读写的 dataset。构造 DDL 时**不会**去读它——迁移脚本得自己
指明它要的 dataset——凡是名字落在 dataset 之上的语句，都自带一个 `schema_name`
参数：

```python
CreateTableExpression(
    d, TableExpression(d, "orders", schema_name="app"), columns=cols
).to_sql()[0]
# CREATE TABLE `app`.`orders` (`id` INT64)

DropTableExpression(d, TableExpression(d, "orders", schema_name="app"),
                    if_exists=True).to_sql()[0]
# DROP TABLE IF EXISTS `app`.`orders`

CreateViewExpression(d, "v_orders", query, schema_name="app").to_sql()[0]
# CREATE VIEW `app`.`v_orders`  AS SELECT `orders`.`id` FROM `app`.`orders`
```

（上面 `CREATE VIEW` 一段里的两个空格，是渲染器实际的输出。）

DML 语句接受带限定的 `TableExpression`，限定方式一致。不带 `WHERE` 时它们只渲染
范围本身，这也是看清「谓词里没有 dataset」最短的一条路：

```python
InsertExpression(
    d, TableExpression(d, "users", schema_name="app"),
    ValuesSource(d, [[Literal(d, "x")]]), columns=["name"],
).to_sql()
# ('INSERT INTO `app`.`users` (`name`) VALUES (?)', ('x',))

UpdateExpression(
    d, TableExpression(d, "users", schema_name="app"), {"name": Literal(d, "x")}
).to_sql()
# ('UPDATE `app`.`users` SET `name` = ?', ('x',))

DeleteExpression(d, [TableExpression(d, "users", schema_name="app")]).to_sql()
# ('DELETE FROM `app`.`users`', ())
```

由模型字段构造的谓词带的是表名与列名，不带 dataset，见
[列引用永远不带 dataset](#列引用永远不带-dataset)。

模拟器模式（设了 `api_endpoint`）下，`update()` 与 `delete()` 还需要 dataset 办
另一件事：模拟器不返回受影响行数，后端会先数一遍匹配的行来补上，而这条
`SELECT COUNT(*)` 用的正是 `options.schema_name`，并经由语句自身所用的同一个限定名
渲染器输出。在那里，不带 dataset 的 DML 同样无从解析。

有两条 DDL 是被拒绝而不是被限定，因为 BigQuery 没有对应的子句：

```python
DropViewExpression(d, "v_orders", schema_name="app", if_exists=True).to_sql()
# UnsupportedFeatureError: 'BigQuery' dialect does not support DROP VIEW IF
# EXISTS. Suggestion: BigQuery does not support DROP VIEW IF EXISTS.

CreateViewExpression(d, "v_orders", query, schema_name="app", if_not_exists=True).to_sql()
# UnsupportedFeatureError: 'BigQuery' dialect does not support CREATE VIEW IF
# NOT EXISTS. Suggestion: BigQuery does not support CREATE VIEW IF NOT EXISTS.
```

`CREATE OR REPLACE VIEW` 可以顶替这两者的位置。

### `CREATE SCHEMA` 与 `DROP SCHEMA` 建的是 dataset、删的是 dataset

两条语句都把 dataset 名渲染成单个带引号的标识符：

```python
CreateSchemaExpression(d, "sales").to_sql()[0]
# CREATE SCHEMA `sales`

CreateSchemaExpression(d, "sales", if_not_exists=True).to_sql()[0]
# CREATE SCHEMA IF NOT EXISTS `sales`

DropSchemaExpression(d, "sales", if_exists=True).to_sql()[0]
# DROP SCHEMA IF EXISTS `sales`
```

`authorization=` 被拒绝，`cascade=True` 同样被拒绝：

```python
CreateSchemaExpression(d, "sales", authorization="app_user").to_sql()
# UnsupportedFeatureError: 'BigQuery' dialect does not support CREATE SCHEMA
# AUTHORIZATION. Suggestion: BigQuery does not support CREATE SCHEMA
# AUTHORIZATION.

DropSchemaExpression(d, "sales", cascade=True).to_sql()
# UnsupportedFeatureError: 'BigQuery' dialect does not support DROP SCHEMA
# CASCADE. Suggestion: BigQuery does not support DROP SCHEMA CASCADE.
```

**`CASCADE` 的拒绝范围比服务端窄。** BigQuery 自己的 `DROP SCHEMA` 文法提供了
两种行为：

> ```
> DROP [ EXTERNAL ] SCHEMA [ IF EXISTS ] [ project_name . ] dataset_name
>   [ CASCADE | RESTRICT ]
> ```
>
> `CASCADE`: Deletes the dataset and all resources within the dataset, such as
> tables, views, and functions. You must have permission to delete the resources,
> or else the statement returns an error.
>
> —— [`DROP SCHEMA` 语句][ddl-drop-schema]

[ddl-drop-schema]: https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language#drop_schema_statement

`supports_schema_cascade()` 返回 `False`，`format_drop_schema_statement` 在
`cascade=True` 时抛异常，因此即便 BigQuery 接受这条语句，`DROP SCHEMA ... CASCADE`
也无法经由表达式层发出。删除非空 dataset 只能手写语句。还要注意，两条 schema DDL
都没有为文法里都有的 `project_name` 留字段，见
[表达式层只带 dataset 一级](#表达式层只带-dataset-一级)。

BigQuery 另外还有 `ALTER SCHEMA` 与 `UNDROP SCHEMA`。核心库里没有对应的表达式，
因此既无从渲染也无从限定。

### 物化视图

四条物化视图语句都把目标命名为一个 `MaterializedView` 对象：dataset 放在对象的
`schema_name` 槽位里，project 放在 `catalog_name` 槽位里。

```python
BigQueryCreateMaterializedViewExpression(
    d, MaterializedView("mv", schema_name="app"), query=inner,
).to_sql()[0]
# CREATE MATERIALIZED VIEW `app`.`mv` AS SELECT `orders`.`id` FROM `app`.`orders`

BigQueryDropMaterializedViewExpression(
    d, MaterializedView("mv", schema_name="app"), if_exists=True,
).to_sql()[0]
# DROP MATERIALIZED VIEW IF EXISTS `app`.`mv`

BigQueryAlterMaterializedViewSetOptionsExpression(
    d, MaterializedView("mv", schema_name="app"),
    options={"enable_refresh": True, "refresh_interval_minutes": 30},
).to_sql()[0]
# ALTER MATERIALIZED VIEW `app`.`mv` SET OPTIONS(enable_refresh = true, refresh_interval_minutes = 30)

BigQueryDropMaterializedViewExpression(
    d, MaterializedView("mv", schema_name="app", catalog_name="myproject"),
).to_sql()[0]
# DROP MATERIALIZED VIEW `myproject`.`app`.`mv`
```

两个槽位各自渲染到该去的地方。只带 project 而没有 dataset 会被拒绝，因为
`project.table` 不是 BigQuery 能解析的路径：

```python
BigQueryDropMaterializedViewExpression(
    d, MaterializedView("mv", catalog_name="myproject"),
).to_sql()
# ValueError: BigQuery renders a project only together with a dataset;
#             MaterializedView 'mv' carries catalog_name='myproject' but no schema_name
```

BigQuery 没有 `REFRESH MATERIALIZED VIEW` 语句，因此
`supports_refresh_materialized_view()` 返回 `False`。刷新在创建时通过
`OPTIONS(enable_refresh=..., refresh_interval_minutes=...)` 配置，之后用
`ALTER MATERIALIZED VIEW ... SET OPTIONS(...)` 修改。

副本语句收**两个 `MaterializedView`**，因此副本与源视图各自独立地挑自己的 dataset——
副本通常与它所镜像的视图不在同一个 dataset 里。

```python
BigQueryCreateMaterializedViewReplicaExpression(
    d,
    MaterializedView("mv_replica", schema_name="app"),
    MaterializedView("mv_src", schema_name="s3_dataset"),
    replication_interval_seconds=600,
).to_sql()[0]
# CREATE MATERIALIZED VIEW `app`.`mv_replica`
#   OPTIONS(replication_interval_seconds = 600) AS REPLICA OF `s3_dataset`.`mv_src`
```

BigQuery 文档里的示例正是这么写的——副本与源放在不同的 dataset，各自给一个全限定名：

> ```
> CREATE MATERIALIZED VIEW `myproject.bq_dataset.mv_replica`
> OPTIONS ( replication_interval_seconds = 600 )
> AS REPLICA OF `myproject.s3_dataset.my_s3_mv`
> ```
>
> —— [`CREATE MATERIALIZED VIEW` 语句][ddl-create-mv]

[ddl-create-mv]: https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language#create_materialized_view_statement

因此跨区域复制是表达得出来的；它仍然加不上的只有 **project** 这一级，因为两个引用都不带
这一级，见[表达式层只带 dataset 一级](#表达式层只带-dataset-一级)。

### 本方言不渲染的语句

sequence 相关的 DDL 在本后端没有实现，因此它上面的 `schema_name` 走不到任何
渲染器：

```python
CreateSequenceExpression(d, "s_orders", schema_name="app").to_sql()
# AttributeError: BigQueryDialect has no formatting method
# 'format_create_sequence_statement' (required by CreateSequenceExpression).
```

`ALTER TABLE ... ADD/DROP INDEX` 在能力标志层面被拒绝
（`supports_alter_table_index_actions()` 返回 `False`），而 `CREATE INDEX` 与
`DROP INDEX` 会渲染。它们上面的 `schema_name` **只限定索引名**，表由它自己的
`TableExpression` 限定，而给那个表传裸字符串会在构造期被拒绝：

```python
CreateIndexExpression(
    d, "idx_orders_id", TableExpression(d, "orders", schema_name="app"), ["id"],
    schema_name="app",
).to_sql()[0]
# CREATE INDEX `app`.`idx_orders_id` ON `app`.`orders` (`id`)

CreateIndexExpression(
    d, "idx_shared", TableExpression(d, "orders", schema_name="sales"), ["user_id"],
    schema_name="app",
).to_sql()[0]
# CREATE INDEX `app`.`idx_shared` ON `sales`.`orders` (`user_id`)

CreateIndexExpression(d, "idx_orders_id", "orders", ["id"], schema_name="app")
# TypeError: table must be a TableExpression, got str

DropIndexExpression(d, "idx_orders_id", schema_name="app").to_sql()[0]
# DROP INDEX `app`.`idx_orders_id`
```

BigQuery 没有二级索引；聚簇与搜索索引是另外两类资源，本库的表达式层没有建模，
相关标志如实反映：`supports_index_introspection()` 与
`supports_fulltext_index()` 都返回 `False`。`supports_create_index()` 与
`supports_drop_index()` 仍然是 `True`，`supports_index_schema_qualification()`
也是 `True`，这正是上面两条语句渲染出来而不抛异常、且带限定的索引名也不会在渲染
阶段被拒的原因。

## 没有会话级的当前 dataset

第二件要定下来的事是这一点，它决定了 dataset 缺失时该怎么办：BigQuery 上没有
可以退让的地方，dataset 要么显式给出，要么语句根本不加限定。

在 BigQuery 上，dataset 是逐条查询绑定的，而不是作为连接状态保存。BigQuery 自己
对「默认 dataset」的说法也一样，指的是查询的属性，不是会话的属性：

> `@@dataset_id`
>
> STRING, Read and write. ID of the default dataset in the current project. This
> ID is used when a dataset is not specified for a project in the query. You can
> use the `SET` statement to assign `@@dataset_id` to another dataset ID in the
> current project.
>
> —— [System variables reference][system-variables]

[system-variables]: https://cloud.google.com/bigquery/docs/reference/system-variables

API 层面也是如此：默认 dataset 是查询请求上的一个字段。

> `defaultDataset`
>
> object (`DatasetReference`) Optional. Specifies the default datasetId and
> projectId to assume for any unqualified table names in the query. If not set,
> all table names in the query string must be qualified in the format
> `'datasetId.tableId'`.
>
> —— [`jobs.query` 请求体][jobs-query]

[jobs-query]: https://cloud.google.com/bigquery/docs/reference/rest/v2/jobs/query

### `get_current_schema()` 抛异常

没有当前 dataset 可读，因此两个后端都拒绝这个问题，而不是给出一个猜测值：

```python
backend.get_current_schema()             # 同步
await async_backend.get_current_schema()  # 异步
```

```
UnsupportedFeatureError: 'BigQuery' dialect does not support reading the current
schema. Suggestion: A dataset is bound per query rather than tracked as session
state, so it cannot be read back from the server. Pass schema_name explicitly
instead.
```

那句建议就是全部的要点：**显式传 `schema_name`**。靠读取当前 schema 来决定要不要
加限定的代码，在本后端没有可移植的写法。命名空间要么交给模型，要么直接传给语句，
不要拿「当前那个」来兜底。

### 连接的 `dataset` 字段做什么、不做什么

`BigQueryConnectionConfig.dataset` 确实存在，它扮演什么角色值得说准确，因为它
**不是**生成 SQL 的默认 dataset。它被读到两处，两处关心的都是连接而不是查询：

- `introspect_and_adapt()` 读它并对其调用 `datasets.get` 作为存在性检查；没有配置
  dataset 时改为列出一个 dataset，作为连通性冒烟检查。失败只记日志，不阻止后续
  使用。该方法的文档字符串写明这次调用仅供参考：BigQuery 的 Standard SQL 特性集
  是稳定的，不会据此调整任何能力。
- `ping()` 读它来列出该 dataset 下的表；未设置时退回到字面量 `'default'`。

它**不会**作为查询作业的 `default_dataset` 发出。`_build_job_config()` 构造的
`QueryJobConfig` 只带 `query_parameters`，此外什么都没有；设了 `api_endpoint` 时
走的 REST 快路径，请求体是 `query`、`useLegacySql`、`timeoutMs` 与 `maxResults`，
没有 `defaultDataset` 字段。配上上面引述的 `defaultDataset` 约定，结论很直接：
**没有 `__schema_name__` 的模型会渲染出一个不带 dataset 的表名，而这个表名没有
任何东西可以据以解析。** 测试套件自己的 provider 出于同样的考虑，给它配置的每个
模型都设上了 `__schema_name__`，注释写的是「不加的话模拟器客户端无从解析裸表名」。

在本后端上，给每个模型都声明 `__schema_name__`。没有任何连接配置项会替你补上这个
dataset。

## 表达式层只带 dataset 一级

BigQuery 的全限定表名由三段组成，参考文档把段数写明了：

> A table name can be a
> [fully qualified table name (table path)][lexical] that includes up to three
> quoted or unquoted identifiers:
>
> - An optional project ID
> - An optional dataset name
> - A required table name.
>
> For example: `myproject.mydataset.mytable`

[lexical]: https://cloud.google.com/bigquery/docs/reference/standard-sql/lexical

**本库目前只带其中一级。** 说清楚：

> **本后端的表、视图、列、索引表达式只接受 `schema_name`，不接受它上面的任何一级。
> `TableExpression`、`Column`、`WildcardExpression` 都没有 project 字段，
> 也没有可以补上的方言钩子。
> dataset 一律渲染成恰好一个带引号的段加一个点号，因此写进去的点号会留在这一段
> 内部。**（`Column` 与 `WildcardExpression` 会把这个值丢弃，见
> [列引用永远不带 dataset](#列引用永远不带-dataset)；索引语句上的 `schema_name`
> 只管索引名，表引用自带自己的 dataset。）

```python
TableExpression(d, "orders", schema_name="myproj.app").to_sql()[0]
# `myproj.app`.`orders`
```

两段各自加引号，所以第一段里的点号属于那个标识符，而不是路径分隔符。BigQuery 究竟
把 `` `myproj.app`.`orders` `` 读成「project 加 dataset」，还是因为首段含点号而
拒绝，本页没有验证——project ID 里不可能含点号，因此带点号的 `schema_name` 无论
如何都不是走到另一个 project 的办法。

真正能给出文档所述三段式写法的途径是 `name`：名字是作为一个标识符被引用的，而带
点号的被引号包住的标识符正是 BigQuery 写路径的方式：

```python
TableExpression(d, "myproj.app.orders").to_sql()[0]
# `myproj.app.orders`
```

BigQuery 自己的示例用的就是这种形式，例如物化视图副本语句里的
`` `myproject.bq_dataset.mv_replica` ``。它把整条路径放进一个带引号的标识符，因此
与「`schema_name` 加 `name`」不是同一种形状，模型无法同时从两个字段产出它。

dataset DDL 上有同样的单级限制：BigQuery 的 `CREATE SCHEMA` 与 `DROP SCHEMA` 文法
都接受 `[ project_name . ]`，而这里的表达式都没有为它留字段。

因此，一条确实要跨 project 的语句只能三选一：

- 把 `name` 写成带点号的路径，让 project 与 dataset 都落在表名里而不是
  `schema_name` 里；
- 手写语句；
- 使用作业执行所在 project 就是目标 project 的连接，由 BigQuery 的 `@@project_id`
  提供 project 这一级，两段式名字随之解析。这一条取决于作业的 project 如何确定，
  本仓库不做这类验证。

## 本后端的内省

简短的回答是：**本仓库不提供 BigQuery 内省器，也不生成任何 `INFORMATION_SCHEMA`
查询。** dataset 不是从目录视图读来的，而是从连接配置读来的，就是前面说的那两处。

总开关与各个分项标志并不一致，写代码前值得先知道：

```python
dialect.supports_introspection()             # True

dialect.supports_table_introspection()        # False
dialect.supports_column_introspection()      # False
dialect.supports_view_introspection()        # False
dialect.supports_trigger_introspection()      # False
dialect.supports_index_introspection()       # False
dialect.supports_database_info()             # False
dialect.supports_foreign_key_introspection() # False
dialect.get_supported_introspection_scopes() # []
```

于是每个元数据查询格式化方法都会拒绝：

```python
TableInfoExpression(d, "orders").to_sql()
# UnsupportedFeatureError: 'BigQuery' dialect does not support table
# introspection.
```

后端本身也没有内省器实例：`BigQueryBackend` 没有混入核心库的
`IntrospectorBackendMixin`，也没有 `introspector` 属性。某个 dataset 的元数据只能
从 BigQuery API 取——`datasets.get`、`tables.list`、`tabledata.list`——或者自己写一条
`INFORMATION_SCHEMA` 查询。

## 空串，以及它在哪一步被拦下

`""` 是个错误，不是「不加限定」的另一种写法——那件事是 `None`。空串会被拒绝，但
**不是在表达式构造时**。构造阶段表达式只收集参数，因此严格校验发生在渲染阶段，
那时整条语句才是完整的。失败因此比预期来得晚：

```python
class Bad(ActiveRecord):
    __table_name__ = "empties"
    __schema_name__ = ""

Bad.schema_name()                        # ''           -- 无异常
Bad.c.id                                 # Column       -- 无异常
Bad.query()                              # ActiveQuery  -- 无异常
Bad.query().select(Bad.c.id)             # ActiveQuery  -- 无异常
Bad.query().select(Bad.c.id).to_sql()    # ValueError   -- 到这里才抛
```

异常信息里指明的是执行校验的那个表达式。在模型层是列，因为 `FieldProxy` 构造出的
列就带着 dataset，而 `format_column` 比范围先做校验：

```
ValueError: Column.schema_name must be a non-empty string; use None for an
unqualified reference
```

直接构造表达式时，指名的是范围：

```
ValueError: TableExpression.schema_name must be a non-empty string; use None for
an unqualified reference
```

纯空白字符串与空串同样被拒——校验前先去掉首尾空白，因此 `"   "` 也过不去。
非字符串有各自的报错信息：

```
ValueError: TableExpression.schema_name must be a string or None, not int
```

之所以要拒绝而不是把 `""` 当作没有：`format_table` 用
`bool(expr.schema_name)` 判断是否加限定，`""` 使它为假，于是走不加限定的分支。
一个本来要求 `` `app`.`orders` `` 的调用方会拿到 `` `orders` ``，既没有异常也没有
警告。本页实测到的是这个不加限定的渲染结果；服务端随后报什么未经观察，而那样的
报错会指向「一张找不到 dataset 的表」，而不是「一个空的 schema 名」——指向的不是
真正出错的地方。

## 常见错误

**把 `schema_name` 读成 BigQuery 的表 schema。** 在 BigQuery 上这个词有两种毫不
相干的含义，`CREATE SCHEMA` 的参考文档说得很清楚：该语句用 SCHEMA 指「表、视图与
其他资源的逻辑集合」，也就是 dataset 的等价物，并且明确不是指某张表的列定义。
本库里的 `schema_name` 始终是前一种。

**期待有一个 `current_schema()` 可以用来兜底。** BigQuery 上没有会话级的当前
dataset，`get_current_schema()` 抛异常，既不返回值，也不从配置里推断一个。既然没有
可退让的地方，在别的后端上成立的那种写法——先读当前命名空间，只在两者不同时才加
限定——在 BigQuery 上没有对应物。请显式限定。

**不写 `__schema_name__`，指望连接来补。** 连接的 `dataset` 字段不会作为作业的
`default_dataset` 发出，渲染出的裸表名因此无从解析。这是最容易一路跑到真实
BigQuery project 上的错误，因为生成出来的 SQL 看着完全正确。见
[没有会话级的当前 dataset](#没有会话级的当前-dataset)。

**期待列引用带上 dataset。** BigQuery 的列引用是「表名或别名 + 列名」，dataset
不会成为列前缀。`` SELECT `app`.`orders`.`id` `` 这样的三段式引用，无论
`schema_name` 与别名怎么组合，本后端都不会渲染出来。见
[`schema_name` 指向 dataset，而列引用不带它](#schema_name-指向-dataset而列引用不带它)。

**以为 `project.dataset.table` 能渲染出来。** 这些表达式只带一级命名空间
`schema_name`，并且把它渲染成恰好一个带引号的段。见
[表达式层只带 dataset 一级](#表达式层只带-dataset-一级)。

**`__table_name__` 里的点号不是命名空间。** 标识符是作为整体被引用的，点号留在
段内：

```python
class Dotted(ActiveRecord):
    __table_name__ = "app.orders"

Dotted.query().select(Dotted.c.id).to_sql()[0]
# SELECT `app.orders`.`id` FROM `app.orders`
```

**`__schema_name__` 里的点号也不是两级。**

```python
TableExpression(d, "orders", schema_name="myproj.app").to_sql()[0]
# `myproj.app`.`orders`
```

**删除非空 dataset 时指望 `CASCADE` 能用。** BigQuery 支持
`DROP SCHEMA ... CASCADE`，而本后端拒绝它，因为 `supports_schema_cascade()` 返回
`False`。见
[`CREATE SCHEMA` 与 `DROP SCHEMA` 建的是 dataset、删的是 dataset](#create-schema-与-drop-schema-建的是-dataset删的是-dataset)。

**为另一个 dataset 里的视图建副本。** 这件事做得到：副本语句为副本收一个
`TableExpression`、为源视图再收一个，两个 dataset 各自独立挑选。它仍然表达不了的只有
project 这一级。见[物化视图](#物化视图)。

**期待构造时就因为不合法的 `schema_name` 抛异常。** 在语句渲染之前，没有任何环节会拒绝
它。因此模型层的错误能一路活过构造查询的每一步，直到拼装 SQL 时才失败。而给点名表的
语句塞一个裸字符串确实会在构造期被拦下，只是那是 `TypeError`。

**去找元数据内省功能。** `supports_introspection()` 返回 `True`，而各个分项内省
标志都是 `False`，查询格式化方法一律抛异常。见 [本后端的内省](#本后端的内省)。

**dataset 名字的大小写写错。** 渲染器保留大小写，而 dataset 名默认区分大小写，
因此 `` `app` `` 找不到建为 `APP` 的 dataset。见 [渲染](#渲染)。

## 推荐的层次安排

- **给每个模型都声明 `__schema_name__`。** 本后端没有连接级的默认 dataset，
  不带限定的范围因此无从解析。这是唯一没有例外的规则。
- **一个模型一个 dataset，只声明一次。** 在共享的基类上写 `__schema_name__` 就能
  覆盖一族模型；写法见核心库文档中的几种模式。
- **多个 dataset**——只在有差异的模型上写 `__schema_name__`。跨 dataset 的 join
  不需要额外配置，每一侧各自限定自己的范围，而列引用始终是两段，生成的 SQL 并不
  比不加限定时更长。
- **多个 project**——一个 project 一个连接；确实需要跨 project 的语句，把 `name`
  写成带点号的路径。在本后端上把 `schema_name` 写宽是走不到 project 的。
