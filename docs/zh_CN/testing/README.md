# 使用 BigQuery 模拟器测试

CI 与本地集成测试不需要 GCP 凭据，它们针对容器中的 `goccy/bigquery-emulator` 运行。

## 启动模拟器

```bash
bash tests/scripts/start_emulator.sh
```

或直接启动：

```bash
docker run -d -p 9050:9050 -p 9060:9060 \
  ghcr.io/goccy/bigquery-emulator:latest --project=test
```

## 让后端指向它

```python
from google.api_core.client_options import ClientOptions
from google.auth.credentials import AnonymousCredentials
from google.cloud import bigquery

client = bigquery.Client(
    project="test",
    credentials=AnonymousCredentials(),
    client_options=ClientOptions(api_endpoint="http://localhost:9050"),
)
```

在库层面，同样的配置由两个字段表达：

```python
config = BigQueryConnectionConfig(
    project="test",
    dataset="app",
    api_endpoint="http://localhost:9050",
    use_anonymous_credentials=True,
)
```

参见[连接配置](../installation/configuration.md)。

## 模拟器上的差异

* **不计费。** 模拟器是垫片，不会对三个数据内省族的扫描收费。
* **只实现部分 GoogleSQL。** 若某个 `seconds_between` 实测用例无法求值 `TIMESTAMP_DIFF`，
  会带服务器给出的原因跳过，而不是报告渲染器失败。
* **`COLUMNS` 投影更窄。** 模拟器只回答 24 个文档列中的 10 个。`list_columns()` 先请求完整列表，
  失败一次后回退；真实服务器永远不会被要求更少的列。参见
  [`COLUMNS` 投影与模拟器](../introspection/README.md)。
* **不报告影响行数。** `update()` / `delete()` 会预先统计匹配行来补算。参见
  [事务与 DML](../capabilities/transactions.md)。
* **会随运行退化。** 表不断累积时，工作流会在分片之间重启它。
* **验证范围。** 本仓库只针对模拟器验证过；完整 `COLUMNS` 列表路径与 `routines` 实测路径尚未在
  真实服务上运行。参见[已验证的内容](../introspection/README.md)。

一条语句能在模拟器上解析并返回行，说明 BigQuery 应该接受它；但这并不能证明真实项目确实回答过它。
