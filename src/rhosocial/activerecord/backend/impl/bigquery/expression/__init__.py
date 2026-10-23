# src/rhosocial/activerecord/backend/impl/bigquery/expression/__init__.py
"""BigQuery-specific DDL and introspection expressions."""

from .introspection import (
    BigQueryColumnInfoQueryStatement,
    BigQueryDatabaseInfoQueryStatement,
    BigQueryDatasetListQueryStatement,
    BigQueryIndexInfoQueryStatement,
    BigQueryPartitionListQueryStatement,
    BigQueryTableListQueryStatement,
    BigQueryTableOptionsQueryStatement,
    BigQueryViewInfoQueryStatement,
    BigQueryViewListQueryStatement,
)
from .materialized_view import (
    BigQueryAlterMaterializedViewSetOptionsStatement,
    BigQueryCreateMaterializedViewReplicaStatement,
    BigQueryCreateMaterializedViewStatement,
    BigQueryDropMaterializedViewStatement,
)

__all__ = [
    "BigQueryAlterMaterializedViewSetOptionsStatement",
    "BigQueryCreateMaterializedViewStatement",
    "BigQueryCreateMaterializedViewReplicaStatement",
    "BigQueryDropMaterializedViewStatement",
    "BigQueryDatabaseInfoQueryStatement",
    "BigQueryTableListQueryStatement",
    "BigQueryColumnInfoQueryStatement",
    "BigQueryIndexInfoQueryStatement",
    "BigQueryViewListQueryStatement",
    "BigQueryViewInfoQueryStatement",
    "BigQueryDatasetListQueryStatement",
    "BigQueryTableOptionsQueryStatement",
    "BigQueryPartitionListQueryStatement",
]

# ``BigQuery`` is one word. The general derivation -- a run of capitals counts as
# a single word -- splits at the camel-case seam instead, so this backend shipped
# ``big_query_create_materialized_view_expression``: two spellings of one
# identifier, neither of them the word the class is named after. The kind is a
# wire contract (§3), so the identifier is declared whole and the kind is derived
# from that declaration: ``KIND_RESERVED`` is data, not behaviour, so no class
# overrides ``kind()`` and class name, kind and formatting entry keep one source.
#
# The loop walks this package's own modules rather than the ``__all__`` list
# above, for the reason the sqlite and mysql packages give: a hand-maintained
# list can only ever be out of date, and a node defined but not re-exported here
# would silently keep the split spelling.
import importlib as _importlib
import pkgutil as _pkgutil

from rhosocial.activerecord.backend.expression.core import BaseExpression as _BaseExpression

for _module_info in _pkgutil.walk_packages(
    __path__, prefix=__name__ + ".", onerror=lambda _error: None
):
    _module = _importlib.import_module(_module_info.name)
    for _value in vars(_module).values():
        if (
            isinstance(_value, type)
            and issubclass(_value, _BaseExpression)
            and _value.__module__ == _module_info.name
            and _value.__name__.startswith("BigQuery")
        ):
            _value.KIND_RESERVED = ("BigQuery",)
del _module_info, _module, _value, _importlib, _pkgutil, _BaseExpression
