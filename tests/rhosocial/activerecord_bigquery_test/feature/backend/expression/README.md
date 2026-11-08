# expression/

Expression/SQL formatting: how generic expression-layer constructs render into
BigQuery Standard SQL.

| File | Description |
|------|-------------|
| `test_expressions.py` | Identifier formatting and type mappings (`INTEGER` → `INT64`). |
| `test_datetime_operations.py` | `DATE_DIFF` spelling, argument order, and week-as-`DAY / 7`. |
| `test_seconds_between.py` | `seconds_between` as `TIMESTAMP_DIFF(end, start, MILLISECOND) / 1000.0`: argument order, bind order, alias, and the fractional result. |
