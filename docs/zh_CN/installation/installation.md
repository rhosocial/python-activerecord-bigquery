# 安装指南

## 安装包

请把后端与核心库一起安装，确保表达式层与方言来自同一开发线：

```bash
pip install rhosocial-activerecord rhosocial-activerecord-bigquery
```

两个发行版都装在 `rhosocial.activerecord` 命名空间下，因此导入后端就是从这个命名空间导入：

```python
from rhosocial.activerecord.backend.impl.bigquery.backend import BigQueryBackend
from rhosocial.activerecord.backend.impl.bigquery.backend.async_backend import AsyncBigQueryBackend
from rhosocial.activerecord.backend.impl.bigquery.config import BigQueryConnectionConfig
```

客户端库（`google-cloud-bigquery`）会作为依赖一并安装。请使用 Python 3.10–3.14 的标准 GIL 构建；
参见[支持版本](../introduction/supported_versions.md)。

## 真实项目的凭据

未提供 key 文件或 JSON 凭据对象时，客户端使用 Application Default Credentials。该账号需要有在
项目中运行作业、读写你指定 dataset 的权限。本地不需要安装任何服务——BigQuery 是托管服务。

## 不使用 GCP 凭据的开发方式

开发与 CI 可以把客户端指向模拟器。模拟器以容器运行，连接配置通过两个额外字段
（`api_endpoint` 与 `use_anonymous_credentials`）选择它。参见
[连接配置](configuration.md)与[使用 BigQuery 模拟器测试](../testing/README.md)。

## 可运行示例

仓库根目录的 `examples/` 目录提供了命名连接、命名过程与命名查询的小程序，从
[`examples/named_connections/example.py`](../../../examples/named_connections/example.py) 开始。
