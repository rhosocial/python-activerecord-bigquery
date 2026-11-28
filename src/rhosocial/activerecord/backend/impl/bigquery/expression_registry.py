# src/rhosocial/activerecord/backend/impl/bigquery/expression_registry.py
"""BigQuery's expression table: core's kinds merged with BigQuery's own.

``BIGQUERY_EXPRESSIONS`` is the mapping this backend's expression package
declares. The published table is the merge of core's mapping and that one --
never a sibling backend's, and no dialect takes part.

Both mappings are data (``kind -> fully qualified class name``); resolution
imports a class only when an artifact names its kind.
"""

from rhosocial.activerecord.backend.expression_registry import (
    CORE_EXPRESSIONS,
    ExpressionRegistry,
    collect_expressions,
    merge_expressions,
)

#: The kinds BigQuery's own expression package declares.
BIGQUERY_EXPRESSIONS = collect_expressions(
    "rhosocial.activerecord.backend.impl.bigquery.expression"
)

#: BigQuery's table: core's kinds plus BigQuery's own, frozen.
BIGQUERY_EXPRESSION_REGISTRY = ExpressionRegistry(
    merge_expressions(CORE_EXPRESSIONS, BIGQUERY_EXPRESSIONS)
).freeze()

__all__ = ["BIGQUERY_EXPRESSIONS", "BIGQUERY_EXPRESSION_REGISTRY"]
