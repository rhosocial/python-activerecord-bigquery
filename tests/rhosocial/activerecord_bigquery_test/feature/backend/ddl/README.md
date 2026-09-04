# ddl/

DDL behavior of the BigQuery dialect: CREATE TABLE diffing and other
schema-definition semantics.

| File | Description |
|------|-------------|
| `test_create_table_expression_diff.py` | `CreateTableExpression.diff()` against the BigQuery dialect — hook configuration (`_supports_alter_column_type`/`_supports_alter_column_properties`/`_supports_alter_table_index_actions`, all False), DiffPlan/RebuildPlan shapes, rendered ALTER/CREATE/DROP/RENAME SQL. Pure expression-level tests. |

BigQuery ALTER TABLE facts pinned here: `ADD COLUMN`/`DROP COLUMN` are
in-place; type changes, column property changes, and index changes rebuild;
indexes only exist as SEARCH INDEX.
