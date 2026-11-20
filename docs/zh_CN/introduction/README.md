# 概述

BigQuery 后端是 [rhosocial-activerecord](https://github.com/rhosocial/python-activerecord)
的 Google BigQuery 实现。它使用原生 `google-cloud-bigquery` 客户端，同时提供同步与异步后端。
它的职责很窄：把核心库的可移植模型与表达式层映射到 BigQuery 的云数仓语义上，并在二者不同之处
明确说明。

本系列文档只讲**本后端**。模型声明、查询构造器与方言无关的表达式节点属于核心库，此处不重复；
涉及共享规则时，页面会给出核心指南的链接。

## BigQuery 的特殊之处

| 关注点 | 本后端中的 BigQuery 行为 |
|---|---|
| 连接标识 | **project** + **dataset**；`location` 选择区域 |
| `schema_name` | 指 dataset，不是表 schema |
| 表引用 | `` `project`.`dataset`.`table` `` / `` `dataset`.`table` `` |
| 列引用 | 永不带 dataset：`` `orders`.`id` `` 或 `` `o`.`id` `` |
| 标识符引号 | 反引号，内部的反引号写成两个 |
| 参数 | 由客户端使用具名 `@param` / 位置查询参数，而非字符串拼接 |
| 异步 | 原生：`AsyncBigQueryBackend`，不是线程池包装 |
| 执行 | 一切都是查询**作业（job）**，结果从作业中读取 |
| 当前 schema | 无——没有会话级命名空间可读回 |

最需要记住的一点：**dataset 是按查询绑定的，不是连接状态**。请在使用到的每个模型上声明
`__schema_name__`；参见 [Schema 命名空间与 dataset](../modeling/schema_namespace.md)。

## 下一步

* [与核心库的关系](relationship.md)——职责划分
* [支持版本](supported_versions.md)——Python 与客户端版本
* [能力边界](capability_boundaries.md)——支持与拒绝的功能
* [连接配置](../installation/configuration.md)——project、dataset、location、凭据与模拟器
* [快速开始](../getting_started/quick_start.md)——最小可运行程序

## 可运行示例

示例位于仓库根目录的 `examples/` 目录（`docs/` 之外）：

* [`examples/named_connections/`](../../../examples/named_connections/example.py)
* [`examples/named_procedures/`](../../../examples/named_procedures/example.py)
* [`examples/named_queries/`](../../../examples/named_queries/example.py)
