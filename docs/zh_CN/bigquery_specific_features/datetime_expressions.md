# docs/zh_CN/bigquery_specific_features/datetime_expressions.md

# BigQuery 时间表达式：`seconds_between`

> 本页说明核心 `seconds_between(start, end)` 节点在本后端上的特殊部分：BigQuery
> 用什么写法表达两个时刻之间的时长、参数顺序为何与通用调用相反、结果的精度，
> 以及它接受哪些操作数类型。
>
> 核心节点本身、`TimestampColumn.seconds_between(...)` 入口，以及每个后端都要实现
> 的 `format_seconds_between_expression` 契约，见核心库文档
> [`docs/en_US/backend/expression/functions.md`][core-functions]。

[core-functions]: https://github.com/rhosocial/python-activerecord/tree/main/docs/en_US/backend/expression/functions.md

## 这个节点要回答什么

`seconds_between(start, end)` 就是 `end - start`，以秒计数：

- **有符号**：结束时刻早于开始时刻为负数，相同时刻恰好为零；
- **带小数**：不足一秒的部分要保留；
- **结束在前**：方向是值的一部分，而不是事后再判断。

核心层不提供通用写法，因为各引擎表达“时长”的方式不同。BigQuery 的答案是
“按指定单位计数的一次差值”。

## 写法

```python
from rhosocial.activerecord.backend.expression import TimestampColumn, seconds_between
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect

dialect = BigQueryDialect()
started = TimestampColumn(dialect, "started_at")
ended = TimestampColumn(dialect, "ended_at")

sql, params = seconds_between(dialect, started, ended).to_sql()
# sql == "TIMESTAMP_DIFF(`ended_at`, `started_at`, MILLISECOND) / 1000.0"
# params == ()
```

各部分的作用：

| 片段 | 原因 |
|---|---|
| `TIMESTAMP_DIFF(end, start, MILLISECOND)` | BigQuery 按指定单位计数，结果的正负号携带方向。 |
| `MILLISECOND` | 本写法使用的最细单位，也是结果能带小数的原因。 |
| `/ 1000.0` | 把毫秒计数换算成秒；小数分母让除法保持浮点。 |
| `ended_at` 写在前面 | `TIMESTAMP_DIFF` 的第一个参数是**结束**时刻；通用 `start, end` 必须交换，否则符号会反。 |

换成绑定参数时，结束参数的绑定顺序在前——格式化器按 SQL 的书写顺序收集参数：

```python
seconds_between(dialect, Literal(dialect, start_dt), Literal(dialect, end_dt)).to_sql()
# ("TIMESTAMP_DIFF(?, ?, MILLISECOND) / 1000.0", (end_value, start_value))
```

别名加在整个标量之后，而不是函数内部：

```python
seconds_between(dialect, started, ended).as_("elapsed").to_sql()[0]
# "TIMESTAMP_DIFF(`ended_at`, `started_at`, MILLISECOND) / 1000.0 AS `elapsed`"
```

## 精度：一毫秒

`TIMESTAMP_DIFF` 返回的是指定单位的整数计数。按毫秒计数因此保留到秒的第三位
小数，更小的部分会被丢弃：500 微秒的跨度没有一个完整的毫秒可计，本节点会得到
`0.0` 秒。GoogleSQL 另外支持 `MICROSECOND`，但本节点的框架契约采用毫秒写法；
需要精确到微秒的调用方应直接向服务器请求。

这个限制是**写明的，不是隐藏的**：节点不会对它无法表示的值做舍入，也不会在 SQL
里偷偷加 `ROUND`。结果就是服务器给出的计数除以 `1000.0`。

符号是精确的：`TIMESTAMP_DIFF` 从开始向结束计数，结束更早时返回负计数，除法
把这个符号保留下来。

## 操作数必须是 `TIMESTAMP`

`TIMESTAMP_DIFF` 接受 `TIMESTAMP` 参数。BigQuery 另有不带时区的 `DATETIME`
类型和与之配套的 `DATETIME_DIFF`；本节点表达两个时刻（instant）之间的跨度，
因此写的是 instant 形式。把 `DATETIME` 操作数不做转换直接传入，服务器会报类型
错误——它不会被静默地按会话时区重新解释。

这也是它与 `date_diff` 的有意区别：`date_diff` 渲染
`DATE_DIFF(end, start, part)`，按日期和整单位计数；`seconds_between` 则是带小数
的时刻跨度。

## 本页如何验证

下面的 SQL 片段由本地 `BigQueryDialect()` 与核心 `feature/extract-epoch` 构建
渲染，没有连接服务器：

```
PYTHONPATH=<core-worktree>/src:src .venv3.14/Scripts/python -m pytest \
  tests/rhosocial/activerecord_bigquery_test/feature/backend/expression/test_seconds_between.py
```

live 用例位于
`tests/rhosocial/activerecord_bigquery_test/feature/backend/test_seconds_between_live.py`。
只有在配置了场景、且端点可达时才会运行；本仓库唯一能连到的端点是 CI 使用的
`goccy/bigquery-emulator`。若端点无法求值 `TIMESTAMP_DIFF`——模拟器只实现
GoogleSQL 的一个子集——用例会带着服务器给出的原因跳过，而不是把模拟器的能力
缺口报成格式化器失败。撰写本页时没有模拟器在运行，live 用例的结果是
**skipped: no reachable BigQuery endpoint**；上面关于渲染与绑定顺序的用例是已经
验证的部分。
