# protocol/

Protocol conformance for BigQuery-specific capability protocols (STRUCT,
ARRAY, JSON, GEOGRAPHY) and dialect formatting gates.

BigQuery's two namespaces are declared by core's `NamespaceSupport` and by
`BigQueryNamespaceMixin`; the protocol here that concerns a namespace is
`BigQuerySchemaSupport`, which answers the DDL question (`CREATE SCHEMA` /
`DROP SCHEMA`) rather than the naming one.

| File | Description |
|------|-------------|
| `test_protocol_conformance.py` | `supports_struct/array/json/geography` on the mixins and the composed dialect; that the naming switches are declared by `BigQueryNamespaceMixin` and not by a second protocol restating core's. |
| `test_protocol_capabilities.py` | Dialect capability methods and formatting (backtick identifiers, `?` positional placeholders) — marked `requires_protocol`. |
