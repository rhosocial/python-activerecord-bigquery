# 快速开始

下面是最小的程序，展示了本后端唯一必须遵守的规则：**在模型上声明 dataset**。

```python
from typing import ClassVar, Optional

from rhosocial.activerecord import ActiveRecord
from rhosocial.activerecord.backend.impl.bigquery.backend import BigQueryBackend
from rhosocial.activerecord.backend.impl.bigquery.config import BigQueryConnectionConfig
from rhosocial.activerecord.backend.expression import FieldProxy

config = BigQueryConnectionConfig(
    project="my-gcp-project",
    dataset="app",
    location="US",
)
backend = BigQueryBackend(connection_config=config)
backend.connect()


class Order(ActiveRecord):
    __table_name__ = "orders"
    __schema_name__ = "app"          # -> `app`.`orders`
    c: ClassVar[FieldProxy] = FieldProxy()

    id: Optional[int] = None
    note: Optional[str] = None


# 渲染出的 SQL：SELECT `orders`.`id` FROM `app`.`orders`
sql = Order.query().select(Order.c.id).to_sql()[0]
print(sql)
```

注意列引用是两级的：dataset 限定 `FROM` 中的范围，然后到此为止。这是与使用 OLTP 后端的代码
相比变化最大的一点；参见 [Schema 命名空间与 dataset](../modeling/schema_namespace.md)。

## 在模拟器上运行

把配置换成模拟器版本，无需任何 GCP 账号：

```python
config = BigQueryConnectionConfig(
    project="test",
    dataset="app",
    api_endpoint="http://localhost:9050",
    use_anonymous_credentials=True,
)
```

先启动模拟器（见[使用 BigQuery 模拟器测试](../testing/README.md)）。

## 异步

异步后端形态相同，使用客户端自身的异步支持：

```python
from rhosocial.activerecord.backend.impl.bigquery.backend.async_backend import AsyncBigQueryBackend

async_backend = AsyncBigQueryBackend(connection_config=config)
await async_backend.connect()
```

## 下一步

* [BigQuery 字段类型](../modeling/field_types.md)——STRUCT、ARRAY、JSON、GEOGRAPHY、BIGNUMERIC
* [查询 BigQuery 原生类型](../querying/bigquery_types.md)
* [事务与 DML](../capabilities/transactions.md)——会话级事务与无 `RETURNING`
* [CLI 用法](../cli/README.md)——从命令行内省 dataset

可运行示例位于仓库根目录的 `examples/`，包括
[`examples/named_connections/example.py`](../../../examples/named_connections/example.py)。
