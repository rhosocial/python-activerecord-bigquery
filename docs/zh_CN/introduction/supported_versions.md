# 支持版本

## Python

Python **3.10 至 3.14**，标准（带 GIL）构建。

## 客户端与服务

* 驱动：`google-cloud-bigquery`（REST 客户端）。同步与异步后端都使用该客户端自身的异步支持，
  没有线程池垫片。
* SQL 方言：GoogleSQL（BigQuery Standard SQL），渲染目标不是旧版 SQL。
* 方言特性级别默认为 `3.0.0`。BigQuery 不通过 SQL 暴露服务器版本，因此这个数字是**特性级别**，
  不是协商出来的服务器版本；内省会如实记录，不会把它冒充服务器版本。

## 核心库

本后端针对 `rhosocial-activerecord` 对应的开发线构建。请把两者一起安装，不要单独拉取已发布的
后端——核心表达式层与本方言版本不匹配，是最容易出现节点或探针缺失的原因。参见
[文档首页](../README.md)末尾的依赖说明。

## 模拟器

CI 与本地集成测试使用 `goccy/bigquery-emulator`，而不是真实的 GCP 账号。模拟器只实现 GoogleSQL
的一部分，且 `COLUMNS` 覆盖也不同；差异处理一律偏向真实服务。参见
[使用 BigQuery 模拟器测试](../testing/README.md)以及内省指南中的
[`COLUMNS` 投影与模拟器](../introspection/README.md)。
