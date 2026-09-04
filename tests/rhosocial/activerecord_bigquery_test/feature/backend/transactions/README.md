# transactions/

Transaction management tests. BigQuery uses session-level (multi-statement)
transactions — no savepoints.

| File | Description |
|------|-------------|
| `test_transaction_backend.py` | `BigQueryTransactionManager` presence and savepoint context behavior. |
