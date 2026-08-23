# Project Overview: rhosocial-activerecord-bigquery

## Project Name
- **Repository Name**: python-activerecord-bigquery
- **Python Package Name**: rhosocial-activerecord-bigquery

## Project Purpose

This project is a BigQuery backend implementation for the `rhosocial-activerecord` Python package. It provides Google Cloud BigQuery data warehouse support with the ActiveRecord pattern interface, including STRUCT, ARRAY, JSON, and standard SQL features.

## Key Design Principles

1. **Backend Implementation**: Extends core ActiveRecord with BigQuery-specific features
2. **Driver**: Uses `google-cloud-bigquery` for database connectivity
3. **Namespace Package**: Integrates with the rhosocial namespace package architecture
4. **Native Async Client**: BigQuery's native async client (google-cloud-bigquery) provides true async support
5. **Cloud-Native Awareness**: BigQuery's project/dataset/table hierarchy, standard SQL dialect, and service account authentication

## Python Version Support

- **Supported**: Python 3.10, 3.11, 3.12, 3.13, 3.14 (standard GIL builds)

## Current Status

This project is under active development. Key features planned:

- BigQueryDialect with backtick identifier quoting and `@param` placeholders
- BigQueryBackend (sync) and AsyncBigQueryBackend (native async)
- BigQueryConnectionConfig with project, dataset, credentials, and location
- Type adapters: STRUCT, ARRAY, JSON, BIGNUMERIC, TIMESTAMP, GEOGRAPHY
- Protocol definitions for BigQuery-specific features
- Transaction management (BigQuery uses session-level transactions)

## BigQuery-Specific Considerations

- **Backtick identifiers**: `` `COLUMN_NAME` `` (BigQuery uses backticks for identifiers)
- **Named parameters**: `@param` or `?` style via query parameters
- **Project/Dataset naming**: Tables referenced as `project.dataset.table`
- **Standard SQL**: BigQuery uses standard SQL by default (not legacy SQL)
- **No native RETURNING clause**: BigQuery does not support `RETURNING` — use separate SELECT or MERGE instead
- **Service account authentication**: Key file or application default credentials
- **Query jobs**: All queries run as jobs; results fetched asynchronously
