# schema

Dataset support: the naming switches (`BigQueryNamespaceMixin`), what a name
renders to with each combination of project and dataset, and the granular
schema-DDL capability bits. Moved from dialect/ per cross-backend taxonomy
(plan §5.9).

| File | Description |
|------|-------------|
| `test_schema_support.py` | Both levels declared and rendered; `project.table` refused while rendering; object naming as the only path to SQL. |
