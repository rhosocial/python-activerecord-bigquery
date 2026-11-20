# CLI 用法

后端提供命令行模块：

```bash
python -m rhosocial.activerecord.backend.impl.bigquery
```

其 `introspect` 子命令从 `INFORMATION_SCHEMA` 回答元数据问题（三个数据族则来自按量计费的扫描）。

## 连接参数

设置可来自参数或环境变量：`--project`（`BIGQUERY_PROJECT` / `GOOGLE_CLOUD_PROJECT`）、
`--dataset`（`BIGQUERY_DATASET`）、`--location`（`BIGQUERY_LOCATION`）、`--credentials-path`
（`BIGQUERY_CREDENTIALS_PATH` / `GOOGLE_APPLICATION_CREDENTIALS`）、`--credentials-json`
（`BIGQUERY_CREDENTIALS_JSON`）与 `--api-endpoint`（`BIGQUERY_API_ENDPOINT`，例如模拟器的
`http://localhost:9050`）。`--use-async` 通过异步后端执行同样的命令。

## 示例

```bash
# 项目与 dataset
python -m rhosocial.activerecord.backend.impl.bigquery introspect database \
  --project my-project
python -m rhosocial.activerecord.backend.impl.bigquery introspect datasets \
  --project my-project

# 某个 dataset 的表与分区
python -m rhosocial.activerecord.backend.impl.bigquery introspect tables \
  --project my-project --dataset my_dataset
python -m rhosocial.activerecord.backend.impl.bigquery introspect partitions orders \
  --project my-project --dataset my_dataset

# 某列的取值（计费扫描）
python -m rhosocial.activerecord.backend.impl.bigquery introspect value-samples orders \
  --column status --project my-project --dataset my_dataset
```

## 类型与输出

提供十五个内省类型：`tables`、`views`、`routines`、`columns`、`datasets`、`database`、
`partitions`、`column-profiles`、`value-samples`、`join-coverage`、`unused-indexes`、
`table-stats`、`runtime`、`index-stats`、`dependencies`。该列表来自同一张映射，每个类型都受其能力
开关约束，因此不会出现“CLI 提供但探针忘了”的族。不支持的类型以退出码 2 并在 stderr 给出原因。
不提供 `ddl`，因为没有抽取语句。

每种类型都接受 `-o table`（默认）、`json`、`csv` 或 `tsv`；`--rich-ascii` 把表格边框切换为 ASCII。
没有 `info` 子命令，也没有 `--limit`：取值采样使用内省自身的默认值 100。

完整的类型表、NAME 规则与计费扫描警告见
[数据库内省](../introspection/README.md)。
