# 数据库内省 (Database Introspection)

BigQuery 后端回答三个层次的问题：项目与其 dataset **声明**了什么（`INFORMATION_SCHEMA`）、它的列**装了什么**（三个读取行的数据族），以及它**完全拒绝**的运维层。`backend.introspector` 是这一切的入口，本页的每个答案都是 BigQuery 自己的：这个目录暴露哪些视图、填充哪些列，以及引擎为读取这些数据收取多少费用。

**费用就是重点。** BigQuery 按读取的字节计费，因此这三个数据族是本后端最昂贵的问题，其代价与表的规模成正比，而与 schema 的大小无关。一次列画像（profile）就是对该整张表的一次扫描，而这次扫描是一个计费事件。不要因为它是"元数据"就以为便宜：元数据本身免费，行不免费。

## 概览

`backend.introspector` 提供：

- **项目与 dataset**：`@@project_id`，以及 `INFORMATION_SCHEMA.SCHEMATA`（唯一在项目级作答的视图）
- **表与视图**：`INFORMATION_SCHEMA.TABLES` / `VIEWS`，并把 dataset 级的 partition 读取归约到每张表的已存字节
- **列**：`INFORMATION_SCHEMA.COLUMNS`，其投影是唯一能说明某个端点到底携带了哪些列的问题
- **主键**：`TABLE_CONSTRAINTS` ⋈ `KEY_COLUMN_USAGE`；不存在索引目录
- **表选项与分区**：`TABLE_OPTIONS` 与 `PARTITIONS`
- **数据，三种方式**：列画像、取值清单与重叠度测量，每一种都是一次或多次计费读取

在 BigQuery 上，核心的 `schema` 参数承载的是一个 **dataset**：只传 dataset 时由已配置的 project 限定，或传 `project.dataset` 去读另一个 project 里的 dataset。当参数与连接配置都没有提供时，构造器抛出带这条指示的错误，而不是猜测。

## BigQuery 回答了什么

内省契约中的每个问题在方言上都有一个探针，而探针问的是眼前这个项目，而不是这个产品。下表是 BigQuery 对全部问题的回答，另加本后端为自己那一族声明的 dataset 开关。

先读 `False` 行：回答 `False` 的探针说的是"这个问题无法向此项目提出"，而不是"答案为空或为零"。

| 探针 | BigQuery 的回答 | 它把关的问题 |
|------|-----------------|--------------|
| `supports_introspection()` | `True` | 任何关于 schema 的问题 |
| `supports_database_info()` | `True` | 本次查询运行在哪个项目 |
| `supports_table_introspection()` | `True` | dataset 中的表与视图 |
| `supports_column_introspection()` | `True` | 列及其声明 |
| `supports_index_introspection()` | `False` | 索引 |
| `supports_foreign_key_introspection()` | `False` | 外键及其动作 |
| `supports_view_introspection()` | `True` | 视图及其定义 |
| `supports_trigger_introspection()` | `False` | 触发器 |
| `supports_table_storage_introspection()` | `True` | 每张表的已存字节 |
| `supports_runtime_stats()` | `False` | 服务自身一直在做什么 |
| `supports_table_stats()` | `False` | 每表使用计数 |
| `supports_index_stats()` | `False` | 每索引使用计数 |
| `supports_unused_indexes_detection()` | `False` | 无使用记录的索引 |
| `supports_object_dependencies()` | `False` | 对象依赖图 |
| `supports_ddl_extraction()` | `False` | 重建一个对象的文本 |
| `supports_ddl_extraction_native()` | `False`（继承） | 该文本是否为引擎自己的 |
| `supports_column_data_profile()` | `True` | 一张表每列装了什么 |
| `supports_column_value_sample()` | `True` | 出现了哪些值，各出现多少次 |
| `supports_join_coverage()` | `True` | 两列的值域重叠多少 |
| `supports_partition_info()` | `True` | 一张表的分区 |
| `supports_extensions()` | `False`（继承） | 已安装的附加组件 |
| `supports_dataset_introspection()` | `True` | BigQuery 自己的 dataset 族 |

三个 `False` 行并不是"引擎做不到"，而是"目录里没有这个事实"，并且每一行都说明了缺的是哪一部分。

- **索引。** BigQuery 不创建任何用户可见的索引，`INFORMATION_SCHEMA` 也没有索引视图。主键是**约束**而非索引，因此它仍能通过内省器的约束读取拿到——`get_primary_key()` 与 `list_indexes()` 都从 `TABLE_CONSTRAINTS` ⋈ `KEY_COLUMN_USAGE` 回答——但索引族本身没有可执行的东西，`IndexType` 为 `UNKNOWN`，其背后并没有索引结构。
- **外键。** `TABLE_CONSTRAINTS` 报告存在某个外键，`KEY_COLUMN_USAGE` 报告它的列，但两者都不给出被引用表及其列，BigQuery 也没有 `REFERENTIAL_CONSTRAINTS` 视图。返回一个 `referenced_table` 为空的外键比不返回更糟，因此 `list_foreign_keys()` 返回空列表，构造器直接拒绝，而不是编造另一侧。
- **触发器。** BigQuery 没有触发器，因此没有触发器目录视图，`list_triggers()` 返回空列表。

`supports_extensions()` 按核心的原因继承 `False`：这里没有映射任何附加组件目录。`supports_partition_info()` 为 `True`，因为 `INFORMATION_SCHEMA.PARTITIONS` 能回答它；`supports_dataset_introspection()` 是本后端在核心探针集合之外自己的开关。

`True` 只承诺语句能渲染、项目会接受它。它不说明答案的形状，也不说明价格；每个族的价格都在描述该族的地方写明。

## 目录类答案从哪来

| 族 | 方法 | BigQuery 来源 |
|----|------|---------------|
| 数据库信息 | `get_database_info()` | `SELECT @@project_id AS catalog_name` |
| Dataset | `list_datasets()` | `INFORMATION_SCHEMA.SCHEMATA` |
| 表 | `list_tables()` | `INFORMATION_SCHEMA.TABLES` + 一次 dataset 级 `PARTITIONS` 读取 |
| 列 | `list_columns()` | `INFORMATION_SCHEMA.COLUMNS`，按投影提问 |
| 主键 | `get_primary_key()`、`list_indexes()` | `TABLE_CONSTRAINTS` ⋈ `KEY_COLUMN_USAGE` |
| 视图 | `list_views()`、`get_view_info()` | `INFORMATION_SCHEMA.VIEWS` |
| 表选项 | `list_table_options()` | `INFORMATION_SCHEMA.TABLE_OPTIONS` |
| 分区 | `list_partitions()` | `INFORMATION_SCHEMA.PARTITIONS` |
| 存储 | `get_table_storage_info()`、`list_tables()` | 组合 `TABLE_OPTIONS`、`PARTITIONS` 与 `COLUMNS` |

以下后果按读者遇到的顺序列出：

- **数据库信息是项目，不是服务器。** `@@project_id` 是有文档的只读系统变量，且没有可通过 SQL 读取的服务器版本。报告出来的版本是本后端的功能级别（默认为 `3.0.0`），记录在 `extra["version_source"]` 里，而不会被当作服务器发行版。`name` 是项目，已配置的 dataset 与 location 放在 `extra`。
- **表。** `TABLE_TYPE` 是 BigQuery 自己的拼写——`BASE TABLE`、`CLONE`、`SNAPSHOT`、`EXTERNAL`、`VIEW`、`MATERIALIZED VIEW`——映射到核心枚举，其中 `CLONE` 与 `SNAPSHOT` 计为基础表，原始拼写保留在 `extra["bigquery_table_type"]`。`include_system` 被忽略：`TABLES` 视图不列出系统表。表记录还把目录的 `ddl` 文本与 `is_typed` / `is_insertable_into` 标志放在 `extra` 里。
- **Dataset。** `SCHEMATA` 是唯一在项目级作答的视图，也是唯一接受 region 限定符的视图（`region-us`、`region-europe-north1` 等）。它报告 dataset 的位置、DDL 文本、默认排序规则与创建/修改时间。
- **视图。** `check_option` 在 BigQuery 上被文档规定永远为 `NULL`；仍然查询它，是为了让解析出的对象能这样说，而不是假定如此。`use_standard_sql` 放在 `extra`。
- **表选项。** 选项以每行一个选项返回——`description`、`expiration_timestamp`、`labels`、`partition_expiration_days`、`require_partition_filter`、`refresh_interval_minutes`，以及外部表的那几个——因此同一选项名可能以不同的 `option_type` 出现多次。正因为如此，它们保持为行，而不折叠成一个字典。
- **分区。** 未分区表的 `partition_id` 为 `NULL`；分区键为 `NULL` 的那一行所在分区的 `partition_id` 为 `__NULL__`。每行带行数、逻辑字节、计费字节、最后修改时间与存储层级。省略表名时，同一个问题会问整个 dataset——每张表每个分区一行。
- **已存字节。** 一张表的 `size_bytes` 是其各分区 `total_billable_bytes` 之和，来自**一次** dataset 级读取的归约，而不是每张表读一次。没有任何分区行的表——视图——保持 `None`，表示"引擎不为这个对象存字节"，这与零是不同的答案。`data_size_bytes` 与 `index_size_bytes` 保持 `None`，因为托管存储没有可拆分出去的索引部分；分区级行本身留在 `PARTITIONS` 族里，比共同最低要求更细。

## BigQuery 拒绝的六个运维族

六个全部回答 `False`，而且它们是继承来的，而不是在这里声明的——方言不覆盖核心探针，因为没有任何 `INFORMATION_SCHEMA` 视图能回答该问题。

| 族 | 探针 | 原因 |
|----|------|------|
| 未使用索引 | `supports_unused_indexes_detection()` | 没有未使用索引视图，也没有可报告的索引 |
| 表计数 | `supports_table_stats()` | `INFORMATION_SCHEMA` 不保存使用计数 |
| 运行时指标 | `supports_runtime_stats()` | 没有运行时指标视图 |
| 索引计数 | `supports_index_stats()` | 没有每索引计数，也没有索引可计数 |
| 依赖 | `supports_object_dependencies()` | 目录中没有依赖图 |
| DDL | `supports_ddl_extraction()` | 这里没有映射任何原生提取族 |

这里的 `False` 是"无法在此提出这个问题"，不是"什么都没用过"。它并不表示某张表从未被读、或该项目没有依赖；它表示无法**通过这一层**向目录提问，CLI 会直接拒绝该族，而不是执行一条服务会拒绝的语句、或打印一行看起来像"答案为零"的空结果。

`ddl` 族值得特别说明，因为表记录的 `extra` 字典里确实带着 `TABLES.ddl`：那段文本是目录在列表查询中返回的内容，不是一个 DDL 提取族。`ddl` 探针回答 `False`，因为这里没有该族的语句；CLI 仍提供该子命令，只是为了让"问它"成为一次能力拒绝，而不是未知命令。

## 费用：每个数据族都是一次计费读取

| 族 | 方法 | 价格 |
|----|------|------|
| 列画像 | `list_column_data_profiles(table)` | 对整张表扫描一次，计费 |
| 取值清单 | `sample_column_values(table, column, limit=100)` | 对整张表分组扫描一次，计费，另加排序 |
| 连接覆盖度 | `estimate_join_coverage(left..., right...)` | 每列各读一次，且两个方向各一遍 |

没有可按列读取的统计目录。`INFORMATION_SCHEMA.COLUMNS` 描述一列**声明**了什么——类型、可空性、默认值——而没有任何视图报告它的行里装了什么：没有空值比例、没有去重计数、没有边界。因此这里的每个数字都是被问时才计算，对查询看到的行是精确的，并以读取的字节付费。

`COUNT(DISTINCT ...)` 是精确写法，语句用的就是它；`APPROX_COUNT_DISTINCT` 更便宜但只是近似，由采样得出的数字必须标记为 `source='sample'` 而不是 `'aggregate'`。这个标签的存在就是为了让调用方能分辨，而本后端给出精确答案——这同样是它要付一次完整读取的原因。

列画像还会先读一次列目录，不只是为了列名：每一列声明的类型决定了能对它提出哪些聚合。那次元数据读取按 `INFORMATION_SCHEMA` 的字节计价，而不是按表的字节，因此相对于随后发生的读取很便宜。

## 列画像：一行宽记录，绝不用 `UNION ALL`

列画像被刻意投影为**一行宽记录**，而不是每列一个 `UNION ALL` 分支，这既是计费决定，也是写法决定。

`UNION ALL` 的每个分支都会读取同一张表，并且各自计费。一张五十列的表若写成五十个分支，就会为同样的数字扫描五十遍。单个投影只扫一遍，因此这是引擎能给出的最便宜的精确答案——不过"最便宜的精确"仍然是一次完整扫描，也是本后端提供的最贵的内省。

行式形态还有第二个对调用方很重要的后果：它让每列的边界避开共同类型解析。union 会在各分支之间解析出一个共同类型，所以 `min_value` 在一个分支携 `INT64`、在另一个分支携 `STRING`，会是类型错误而不是强制转换。而在这里，每个槽位只属于一列，边界被转成 `STRING` 仅仅是为了给它一个结果名。

这一行按**位置**命名——`c1_name`、`c1_null_count`、`c1_distinct_count`、`c1_min`、`c1_max`，然后是 `c2_...`——因为列名可以包含目录允许的任何字符，而这些名字是解析器要读取的固定词。解析器再按核心自己的规则把这一行透视回每列一个画像，因此 `null_fraction` 的推导规则、以及"缺失的数字意味着什么"，都不会在这里被写第二遍。

## 不透明类型按名称投影为 `NULL`

BigQuery 拒绝对不可排序的列计算 `MIN` 和 `MAX`——`ARRAY`、`STRUCT`/`RECORD`、`JSON`、`GEOGRAPHY` 与 `RANGE`——并且对其中若干类型同样拒绝 `COUNT(DISTINCT ...)`，因为它们也不可分组。如果语句在这些位置点名了这样的列，它就无法为那些**能读**的列作答：服务会在分析阶段拒绝整条查询。

所以内省器把不透明列（名字来自它刚读过的列目录）交给格式化器，后者把它们的去重计数与两个边界投影为 SQL `NULL`，同时仍然统计它们的空值以及表的行数。这三个槽位以 `None` 到达，并保持 `None`。

这次投影保留的区分，正是读者最需要的那一条：**`NULL` 是引擎拒绝测量的数字，而不是它测到零。** 空字符串、零与缺失的边界是三个不同的答案，只有第三个才是不透明列的画像所说的。空值计数对任何类型都可回答，因此那个槽位永远是一个测量值。

空列清单渲染出的行只带表自身的事实、没有列分组；解析器把它读作空画像，这是一张没有列的表的真相，而不是错误。对零行求和得到 `NULL` 而不是编造一个零，因此空表的空值计数是缺失，而不是 `0`。

## 取值清单与连接覆盖度

**取值清单**是对该列的一次 `GROUP BY` 加一次分组排序——与列画像同样的一次计费扫描，另加排序。没有任何预计算，因此它是与画像分开的探针：只想要最频繁取值的调用方，不应为画像计算的那些聚合付费。

- `ORDER BY COUNT(*) DESC` 才让答案成为"最频繁的取值"而不是"最先出现的取值"；并列时按取值排序，因此同一查询的两次运行结果一致。
- `LIMIT` 是绑定参数，调用方的整数永远不会被拼进语句文本。
- `GROUP BY` 会把 `NULL` 分到一组，因此含 `NULL` 的列会有一个 `value` 为 `None` 的条目。解析器不会跳过它：在这份清单里，`NULL` 是该值域的一员。
- BigQuery 无法分组的列——`ARRAY`、`STRUCT`、`JSON`、`GEOGRAPHY`——会被**服务**拒绝，错误信息里点名该列。这是引擎对所选列的规则，而不是本族的缺口，服务报错比一份悄悄漏掉它的清单是更好的答案。
- `frequency` 保持 `None`：引擎报告的是计数，而分母是行数，这条查询并不携带它。

**连接覆盖度**测量两侧各自有多少去重取值也存在于另一侧。两个比例来自同一条语句——同一投影里的两个标量子查询，一行只由子查询组成时不需要 `FROM`。每个比例都统计另一侧非 `NULL` 取值上的 `IN` 谓词下的去重取值数，再除以该侧的去重非 `NULL` 取值数。`IS NOT NULL` 在两侧都明确写出，而不是依赖隐式行为；`NULLIF(..., 0)` 让没有任何可匹配值的列回答 `NULL` 而非 `0.0`，从而"没有匹配上"与"没有可匹配的"保持区分。BigQuery 对两个 `INT64` 计数的 `/` 已经给出 `FLOAT64`，因此这里没有 `* 1.0`。

这一行同时携带两个比例，因为单独一个没有意义：左侧 1.0 与右侧 0.2 并列，说明被检验的取值都存在于另一侧，而那个值域的大部分并未被覆盖；一个平均分数则两者都描述不了。价格是两侧各读一次自己的去重值域、再做一次交集，并且因为两个方向都要报告而做两遍。其中每一次读取都计费，这使它成为本族中最昂贵的测量。回答 `True` 是正确的，因为探针问的是引擎**能不能**回答，而不是能不能便宜地回答：代价写在本页，而不是写进一个声称 BigQuery 无法测量自己数据的 `False`。

```python
from rhosocial.activerecord.backend.impl.bigquery.backend import BigQueryBackend
from rhosocial.activerecord.backend.impl.bigquery.config import BigQueryConnectionConfig

config = BigQueryConnectionConfig(
    project="my-project",
    dataset="my_dataset",
    location="US",
    credentials_path="/path/to/key.json",
    # api_endpoint="http://localhost:9050",  # CI 使用的模拟器
)
backend = BigQueryBackend(connection_config=config)
backend.connect()

# 一次扫描，一次账单。返回的是一行宽记录，画像按列展开。
for profile in backend.introspector.list_column_data_profiles("orders"):
    print(
        profile.column_name,
        profile.source,          # 'aggregate'：精确，代价是读取的字节
        profile.row_count,
        profile.null_fraction,
        profile.distinct_count,  # ARRAY、STRUCT、JSON、GEOGRAPHY、RANGE 上为 None
        profile.min_value,       # 同样这些类型上为 None，这是设计
        profile.max_value,
    )

# 第二次扫描，扫的是同样的字节：只有在它正是你要问的问题时才请求。
for sample in backend.introspector.sample_column_values("orders", "status", limit=20):
    print(sample.value, sample.count)   # NULL 成组时 value 为 None

# 两张表的两列，两侧、两个方向都要读。
coverage = backend.introspector.estimate_join_coverage(
    "orders", "customer_id",
    "customers", "id",
)
print(coverage.left_coverage, coverage.right_coverage)
```

## `COLUMNS` 投影与模拟器

`INFORMATION_SCHEMA.COLUMNS` 不在任何地方报告自己的列，因此唯一能说明某个端点携带了哪些列的问题，就是 `COLUMNS` 问题本身。它没有版本、也没有能力开关：BigQuery 不报告服务器发行版，本后端的版本是功能级别，而不是协商出来的版本。

存在两个投影，它们回答不同的问题。

- `COLUMNS_PROJECTION_FULL` 是 BigQuery **有文档的 24 列顺序**，也是唯一会向真实服务器提出的投影。它还是读取窄清单读不到的族的唯一方式：某列是否生成、计算列由什么计算、身份列的边界是什么、表按哪一列聚簇。
- `_EMULATOR_COLUMNS_PROJECTION` 是这 24 列中的 10 列——本仓库 CI 所运行的 `goccy/bigquery-emulator` 的列覆盖范围。它是那个模拟器的属性，不是 BigQuery 的属性，这也是该常量**私有**、并以模拟器命名的原因：不会向任何真实服务器索取少于有文档清单的列。

回退是"先试再重问"，只做一次并被记住。`list_columns()` 先请求完整清单；若端点使这个问题失败，它就改问窄清单，并把"该端点接受这一份"记下来，供该管理器余生使用。真实服务器从不为回退付费，因为第一个问题就成功；模拟器只付一次失败问题的代价，而不是每张表付一次。窄清单是刚失败那份的子集，因此若它也失败，出错的是表、dataset 或连接——而**第一个**错误正是点名出错对象的那个，抛出的是它。

回退使一个新的区分成为必要，解析器保留了这个区分。一个字段在行中**存在**，本身就是"问过它"的记录——投影选择名字，端点每个被选中的名字返回一个字段——因此缺席的名字从未被问过，它的缺席永远不是端点在回答"否"。于是每个解析出的列在 `extra["columns_asked"]` 里记录它实际被问过的名字，这个名字从行里读出。

这正是让 `is_generated` 保持诚实的原因。若按 `None` 默认读取，它会变成"否"这个答案，于是消费者会被告知某列不是生成列，而真相是端点从未携带这一事实。相反，只有 `is_generated` 出现在 `columns_asked` 中时，`is_generated` 才是 `True` 或 `False`，否则为 `None`——同样的规则适用于身份标志、身份边界、聚簇位置与舍入模式。要判断"这列是不是生成列"的消费者必须把两者一起读：`extra["columns_asked"]` 说明问题是否被问过；槽位说明答案是什么。

关于同一视图的两个较小事实：`is_hidden` 为 `YES` 的列是伪列，其 `ordinal_position` 为 `NULL`，不属于声明的 schema，因此解析器会跳过它；对于本方言解析器读不了的类型字符串（`STRUCT<...>`、`RANGE<...>`），`parsed_data_type` 为 `None`，并给出一条点名该列的警告——这样一个读不了的类型只降解一列的结构化类型，而不是整个列表。

## 已经验证到什么程度

**只针对模拟器验证过。** CI 中没有任何 GCP 凭据，因此这些测试运行的 shard 是 `goccy/bigquery-emulator`，以容器方式启动，通过 REST 驱动并把 `--api-endpoint` 指向它。本页每条语句都在那里被执行过，值得直说这意味着什么：

- 真实 BigQuery 会回答完整的 24 列 `COLUMNS` 投影，而模拟器只回答 10 列。代码的写法是：向真实服务器请求有文档的清单，只有失败的端点才回退——但完整清单那条路径本身，并未在本仓库的 CI 中对真实服务执行过。
- 模拟器是层壳，不是服务本身：它不计费、并不实现全部功能，而且工作流会在各 shard 之间重启它，因为随着表和作业累积它会退化。在那里能解析并返回行的语句，是 BigQuery **应当**接受的语句；它不是"真实项目已回答过它"的证明。
- 凡是在模拟器与服务之间行为不同的地方——上面的列投影就是可见的一例——代码都写成优先真实服务、并向模拟器降级，而不是反过来。

## 门槛与版本检查

没有门槛，而这是关于引擎的事实，不是缺失的章节。

| 族 | 门槛 | 缺少门槛时是什么样子 |
|----|------|----------------------|
| 所有族 | 无 | — |
| `COLUMNS` 投影 | 不存在版本问题 | 就是 `COLUMNS` 问题本身，先问一次、再重问一次 |

BigQuery 不通过 SQL 报告服务器发行版，本后端的版本是功能级别而非协商版本，因此没有可比对门槛的对象。方言不做版本适配，探针对的是本后端所构造的方言——同一构造的每次调用得到同一个答案。某个端点上失败的 `INFORMATION_SCHEMA` 问题，是通过改用更窄的投影重问来解决的，而不是靠版本门槛。

探针也不检查凭据。探针回答的是目录，不是账号：若本次运行没有凭据或无法访问某个 dataset，客户端会拒绝连接，或服务返回它自己的权限错误，探针不会假装预见到了这一点。

## 命令行内省

```bash
# 项目本身，以及它拥有的 dataset
python -m rhosocial.activerecord.backend.impl.bigquery introspect database \
  --project my-project
python -m rhosocial.activerecord.backend.impl.bigquery introspect datasets \
  --project my-project

# 一个 dataset 的表、视图与分区
python -m rhosocial.activerecord.backend.impl.bigquery introspect tables \
  --project my-project --dataset my_dataset
python -m rhosocial.activerecord.backend.impl.bigquery introspect partitions orders \
  --project my-project --dataset my_dataset

# 一列装了什么：两个命令都会扫描，也都会计费
python -m rhosocial.activerecord.backend.impl.bigquery introspect column-profiles orders \
  --project my-project --dataset my_dataset
python -m rhosocial.activerecord.backend.impl.bigquery introspect value-samples orders \
  --column status --project my-project --dataset my_dataset

# 本后端拒绝的族——被拒绝，而不是回答一行空结果
python -m rhosocial.activerecord.backend.impl.bigquery introspect unused-indexes \
  --project my-project --dataset my_dataset
python -m rhosocial.activerecord.backend.impl.bigquery introspect ddl orders \
  --project my-project --dataset my_dataset
```

连接设置来自命令行参数或环境变量：`--project`（`BIGQUERY_PROJECT` 或 `GOOGLE_CLOUD_PROJECT`）、`--dataset`（`BIGQUERY_DATASET`）、`--location`（`BIGQUERY_LOCATION`）、`--credentials-path`（`BIGQUERY_CREDENTIALS_PATH` 或 `GOOGLE_APPLICATION_CREDENTIALS`）、`--credentials-json`（`BIGQUERY_CREDENTIALS_JSON`）、`--api-endpoint`（`BIGQUERY_API_ENDPOINT`，例如模拟器的 `http://localhost:9050`）。`--use-async` 让同样的命令走异步后端。

`--dataset` 选择每个问题所限定的 dataset，它与 schema 参数承载的是同一个东西，因为二者是同一层级。`database` 是唯一限定到项目的问题，因为 `@@project_id` 命名的是项目，而不是 dataset。

没有任何命令会编造答案：没有 dataset 时内省器抛出带确切指示的错误，没有凭据时客户端拒绝连接。两者都以非零退出，并把原因写到 stderr；`--include-system` 会被接受，但没有可包含的内容，因为 `TABLES` 视图不列出系统表。

### 内省类型

| 类型 | 说明 | NAME |
|------|------|------|
| `tables` | dataset 中的表与视图 | 不接受 |
| `views` | dataset 中的视图 | 不接受 |
| `columns` | 一张表的列 | 必填（表） |
| `datasets` | 项目的 dataset | 不接受 |
| `database` | 本次运行所连接的项目 | 不接受 |
| `partitions` | 一张表的分区及其大小 | 必填（表） |
| `column-profiles` | 一张表每列的数据画像 | 必填（表） |
| `value-samples` | 一列最频繁的取值 | 必填（表） |
| `join-coverage` | 两列值域的重叠度 | 必填（左表） |
| `unused-indexes` | 无使用记录的索引 | 不接受 |
| `table-stats` | 每表使用计数 | 不接受 |
| `runtime` | 实时运行时测量 | 不接受 |
| `index-stats` | 每索引使用计数 | 不接受 |
| `dependencies` | 对象依赖图 | 可选（对象） |
| `ddl` | 重建一张表的 DDL | 必填（表） |

十五个类型，公布的清单衍生自同一份把每个类型绑定到其开关的映射，因此不可能出现"CLI 提供了某一族、但探针忘了它"的情况。

`database` 与 `partitions` 之所以在这里，是因为方言回答了它们、CLI 却问不到：`database` 是项目级的问题，`partitions` 是引擎自己的族——每分区一行，带行数与所占字节，比表列表归约到的共同最低要求更细。一个问不到方言所声明内容的 CLI，就是"能回答却无法提问"。

该命令**没有 `info` 子命令**，因此没有第二份输出格式清单：每个 `introspect` 类型都支持 `-o table`（默认）、`json`、`csv` 或 `tsv`，`--rich-ascii` 把表格边框换成 ASCII。也没有 `--limit`：`value-samples` 由内省器自己的默认值（`VALUE_SAMPLE_LIMIT`，100）界定，因此这个数字不会被写两遍。

NAME 按类型分为必填、可选或拒绝，每个类型的规则集中在一张表里，而不是写在需要它的那个分支内部。缺一个必填的 NAME 是不完整的调用（退出码 1）；类型没有相应问题时给出 NAME，是命令拒绝的请求（退出码 2），绝不会出现"解析后被丢掉"的参数——那会让一个单对象问题打印出整个族的清单。`value-samples` 取 `--column`；`join-coverage` 以左表作为 NAME，另加 `--column`、`--right-table` 与 `--right-column`；所选类型不读取的标志会被拒绝（退出码 2），而不是被忽略。

开关回答 `False` 的类型以退出码 2 被拒绝，原因写到 stderr，因为"这个项目无法回答"与"这个 dataset 没有"是不同的答案。`column-profiles` 的扫描提示写到 stderr、位于各行之前，好让读者在看那些以一次扫描换来的数字时就看到价格——同时 stdout 上的机器可读格式保持可解析。
