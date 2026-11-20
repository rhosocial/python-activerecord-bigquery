# 连接配置

`BigQueryConnectionConfig` 组合了核心的 `ConnectionConfig` 与连接池、SSL、字符集、时区、版本和日志
mixin，并增加以下 BigQuery 字段。

| 字段 | 类型 | 含义 |
|---|---|---|
| `project` | `str \| None` | 运行查询作业的 GCP 项目 |
| `dataset` | `str \| None` | 用于连接级检查的 dataset（见下方警告） |
| `location` | `str \| None` | 作业所在区域，例如 `US`、`europe-north1` |
| `credentials_path` | `str \| None` | 服务账号 key 文件路径 |
| `credentials_json` | `dict \| None` | 字典形式的服务账号凭据 |
| `api_endpoint` | `str \| None` | 覆盖客户端 endpoint，例如模拟器的 `http://localhost:9050` |
| `use_anonymous_credentials` | `bool` | 使用 `AnonymousCredentials`；仅用于模拟器 |

两个后端也接受这些作为构造参数；未传 `connection_config=` 时会据此构建配置。

## 真实项目

```python
from rhosocial.activerecord.backend.impl.bigquery.backend import BigQueryBackend
from rhosocial.activerecord.backend.impl.bigquery.config import BigQueryConnectionConfig

config = BigQueryConnectionConfig(
    project="my-gcp-project",
    dataset="app",
    location="US",
    credentials_path="/path/to/key.json",   # 省略则使用 Application Default Credentials
)
backend = BigQueryBackend(connection_config=config)
backend.connect()
```

## 模拟器设置

```python
config = BigQueryConnectionConfig(
    project="test",
    dataset="app",
    api_endpoint="http://localhost:9050",
    use_anonymous_credentials=True,
)
```

设置 `api_endpoint` 后，同步后端走 REST 快速路径，并适用模拟器的有限行为——例如它不报告
影响行数，因此 `update()` / `delete()` 会用 `SELECT COUNT(*)` 预先统计。参见
[使用 BigQuery 模拟器测试](../testing/README.md)。

## `dataset` **不**做什么

> **重要**：`config.dataset` **不是**生成 SQL 的默认 dataset。它只用于连接级工作：
> `introspect_and_adapt()` 用它做存在性检查，`ping()` 用它列表示。它永远不会作为作业的
> `defaultDataset` 发送。因此没有 `__schema_name__` 的模型会渲染出一个没有任何对象可解析的裸表名。

请为每个模型声明 `__schema_name__`。完整解释（包括为什么没有会话级回退）见
[Schema 命名空间与 dataset](../modeling/schema_namespace.md)。

## CLI 使用的环境变量

命令行工具读取参数或环境变量：`--project`（`BIGQUERY_PROJECT` / `GOOGLE_CLOUD_PROJECT`）、
`--dataset`（`BIGQUERY_DATASET`）、`--location`（`BIGQUERY_LOCATION`）、`--credentials-path`
（`BIGQUERY_CREDENTIALS_PATH` / `GOOGLE_APPLICATION_CREDENTIALS`）、`--credentials-json`
（`BIGQUERY_CREDENTIALS_JSON`）与 `--api-endpoint`（`BIGQUERY_API_ENDPOINT`）。
参见 [CLI 用法](../cli/README.md)。
