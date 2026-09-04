# protocol/

Protocol conformance for BigQuery-specific capability protocols (STRUCT,
ARRAY, JSON, GEOGRAPHY) and dialect formatting gates.

| File | Description |
|------|-------------|
| `test_protocol_conformance.py` | `supports_struct/array/json/geography` on the mixins and the composed dialect. |
| `test_protocol_capabilities.py` | Dialect capability methods and formatting (backtick identifiers, `?` positional placeholders) — marked `requires_protocol`. |
