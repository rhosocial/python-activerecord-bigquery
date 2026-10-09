# dialect/

BigQuery dialect surface: identifier quoting, type mappings, capability flags,
and protocol conformance.

| File | Description |
|------|-------------|
| `test_dialect_formatting.py` | Identifier quoting (backticks). |
| `test_bigquery_materialized_view.py` | The four MATERIALIZED VIEW statements, their BigQuery-only clauses, and the object-kind checks in each formatter. |
| `test_column_schema_validation.py` | A dataset on a bare column is reported, never dropped. |
| `test_expression_fields_match_formatters.py` | Every statement whose formatter qualifies a name builds with the object that carries the namespace, and refuses the wrong object kind. |
| `test_column_suggestion.py` | The eighteen-entry `COLUMN_TYPE_SUGGESTIONS` table and the one `supports_column_operation` narrowing, plus the documentation-only markers (待云验, 议题 A, fix item #8). No server. |
