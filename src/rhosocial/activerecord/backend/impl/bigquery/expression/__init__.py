# src/rhosocial/activerecord/backend/impl/bigquery/expression/__init__.py
"""BigQuery-specific DDL and introspection expressions."""

from .introspection import (
    BigQueryColumnDataProfileQueryStatement,
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
from .objects import BigQueryPartitionDecoratedTable
from .query_parts import BigQueryTablePartitionByClause
from .statements import (
    BigQueryAlterMaterializedViewSetOptionsStatement,
    BigQueryAlterTableSetOptionsStatement,
    BigQueryCreateMaterializedViewReplicaStatement,
    BigQueryCreateMaterializedViewStatement,
    BigQueryCreateTableStatement,
    BigQueryDropMaterializedViewStatement,
)

__all__ = [
    "BigQueryAlterMaterializedViewSetOptionsStatement",
    "BigQueryAlterTableSetOptionsStatement",
    "BigQueryCreateMaterializedViewStatement",
    "BigQueryCreateMaterializedViewReplicaStatement",
    "BigQueryDropMaterializedViewStatement",
    "BigQueryCreateTableStatement",
    "BigQueryPartitionDecoratedTable",
    "BigQueryTablePartitionByClause",
    "BigQueryDatabaseInfoQueryStatement",
    "BigQueryTableListQueryStatement",
    "BigQueryColumnInfoQueryStatement",
    "BigQueryColumnDataProfileQueryStatement",
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
# Ownership is declared by name, once, below: the names of every expression
# class this package defines are written out whole and the loop matches against
# that declaration, so no prefix test or name slicing guesses at ownership.
# The set covers the introspection statement that is deliberately not
# re-exported above (BigQueryRoutineListQueryStatement); the kind-identity test
# pins the complete list, so adding a node requires declaring it here too.
import importlib as _importlib
import pkgutil as _pkgutil

from rhosocial.activerecord.backend.expression.bases.bases import BaseExpression as _BaseExpression

_BIGQUERY_OWNED_NAMES = frozenset({
    "BigQueryAlterMaterializedViewSetOptionsStatement",
    "BigQueryAlterTableSetOptionsStatement",
    "BigQueryColumnDataProfileQueryStatement",
    "BigQueryColumnInfoQueryStatement",
    "BigQueryCreateMaterializedViewReplicaStatement",
    "BigQueryCreateMaterializedViewStatement",
    "BigQueryCreateTableStatement",
    "BigQueryDatabaseInfoQueryStatement",
    "BigQueryDatasetListQueryStatement",
    "BigQueryDropMaterializedViewStatement",
    "BigQueryIndexInfoQueryStatement",
    "BigQueryPartitionDecoratedTable",
    "BigQueryPartitionListQueryStatement",
    "BigQueryRoutineListQueryStatement",
    "BigQueryTableListQueryStatement",
    "BigQueryTableOptionsQueryStatement",
    "BigQueryTablePartitionByClause",
    "BigQueryViewInfoQueryStatement",
    "BigQueryViewListQueryStatement",
})

for _module_info in _pkgutil.walk_packages(
    __path__, prefix=__name__ + ".", onerror=lambda _error: None
):
    _module = _importlib.import_module(_module_info.name)
    for _value in vars(_module).values():
        if (
            isinstance(_value, type)
            and issubclass(_value, _BaseExpression)
            and _value.__module__ == _module_info.name
            and _value.__name__ in _BIGQUERY_OWNED_NAMES
        ):
            _value.KIND_RESERVED = ("BigQuery",)
del _module_info, _module, _value, _importlib, _pkgutil, _BaseExpression, _BIGQUERY_OWNED_NAMES
