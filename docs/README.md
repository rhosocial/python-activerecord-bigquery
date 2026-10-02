# rhosocial-activerecord-bigquery

BigQuery backend implementation for [rhosocial-activerecord](https://github.com/rhosocial/python-activerecord).

## Documentation / 文档

Please select your language / 请选择语言：

- [English Documentation](en_US/README.md)
- [中文文档 (Chinese)](zh_CN/README.md)

## Overview

The BigQuery backend brings the ActiveRecord pattern to Google BigQuery through the
`google-cloud-bigquery` REST driver. BigQuery has no session-level namespace state: the
dataset is bound per query, and column references never carry the dataset.

For the main ActiveRecord framework documentation, please visit the
[python-activerecord docs](https://github.com/rhosocial/python-activerecord/tree/docs/docs).