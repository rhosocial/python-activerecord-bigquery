# dialect/

BigQuery dialect surface: identifier quoting, type mappings, capability flags,
and protocol conformance.

| File | Description |
|------|-------------|
| `test_dialect_formatting.py` | Identifier quoting (backticks). |
| `test_schema_support.py` | `SchemaSupport` protocol: `supports_schema()` is True (dataset namespaces), granular schema-DDL bits currently False. |
