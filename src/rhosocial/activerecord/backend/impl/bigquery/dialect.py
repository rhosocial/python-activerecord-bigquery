"""BigQuery SQL dialect implementation."""
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from rhosocial.activerecord.backend.dialect.base import SQLDialectBase
from rhosocial.activerecord.backend.dialect.protocols import (
    CTESupport, FilterClauseSupport, WindowFunctionSupport, MergeSupport,
    AdvancedGroupingSupport, ArraySupport, ExplainSupport,
    QualifyClauseSupport, UpsertSupport, LateralJoinSupport,
    JoinSupport, ViewSupport, SchemaSupport, IndexSupport,
    ConstraintSupport, IntrospectionSupport, TransactionControlSupport,
    SQLFunctionSupport, JSONSupport,
)
from rhosocial.activerecord.backend.dialect.mixins import (
    CTEMixin, FilterClauseMixin, WindowFunctionMixin, JSONMixin,
    AdvancedGroupingMixin, ArrayMixin, ExplainMixin, MergeMixin,
    QualifyClauseMixin, UpsertMixin, LateralJoinMixin, JoinMixin,
    ViewMixin, SchemaMixin, IndexMixin, TableMixin, ConstraintMixin,
    IntrospectionMixin,
)
from .protocols import (
    BigQueryStructSupport, BigQueryArraySupport,
    BigQueryJSONSupport, BigQueryGeographySupport,
)
from .mixins import (
    BigQueryStructMixin, BigQueryArrayMixin,
    BigQueryJSONMixin, BigQueryGeographyMixin,
)


class BigQueryDialect(
    SQLDialectBase,
    CTEMixin, FilterClauseMixin, WindowFunctionMixin, JSONMixin,
    AdvancedGroupingMixin, ArrayMixin, ExplainMixin, MergeMixin,
    QualifyClauseMixin, UpsertMixin, LateralJoinMixin, JoinMixin,
    ViewMixin, SchemaMixin, IndexMixin, TableMixin, ConstraintMixin,
    IntrospectionMixin,
    BigQueryStructMixin, BigQueryArrayMixin,
    BigQueryJSONMixin, BigQueryGeographyMixin,
    CTESupport, FilterClauseSupport, WindowFunctionSupport, MergeSupport,
    AdvancedGroupingSupport, ArraySupport, ExplainSupport,
    QualifyClauseSupport, UpsertSupport, LateralJoinSupport,
    JoinSupport, ViewSupport, SchemaSupport, IndexSupport,
    ConstraintSupport, IntrospectionSupport, TransactionControlSupport,
    SQLFunctionSupport, JSONSupport,
    BigQueryStructSupport, BigQueryArraySupport,
    BigQueryJSONSupport, BigQueryGeographySupport,
):
    def __init__(self, version: Tuple[int, ...] = (3, 0, 0), **kwargs):
        super().__init__(**kwargs)
        self.version = version

    def format_identifier(self, identifier: str) -> str:
        return f"`{identifier}`"

    def get_parameter_placeholder(self, index: int = 0) -> str:
        return "@param_{}".format(index)

    def supports_cte(self) -> bool:
        return True

    def supports_window_functions(self) -> bool:
        return True

    def supports_json_operations(self) -> bool:
        return True

    def supports_merge(self) -> bool:
        return True

    def supports_qualify_clause(self) -> bool:
        return False

    def supports_upsert(self) -> bool:
        return True

    def supports_lateral_join(self) -> bool:
        return False

    def supports_explain(self) -> bool:
        return True

    def supports_advanced_grouping(self) -> bool:
        return True

    def supports_arrays(self) -> bool:
        return True

    def supports_schema(self) -> bool:
        return True

    def supports_views(self) -> bool:
        return True

    def supports_introspection(self) -> bool:
        return True

    def supports_returning_clause(self) -> bool:
        return False

    def format_limit_offset(self, sql: str, limit: Optional[int] = None, offset: Optional[int] = None) -> str:
        if limit is not None:
            sql += f" LIMIT {limit}"
        if offset is not None:
            sql += f" OFFSET {offset}"
        return sql

    def get_type_mappings(self) -> Dict[str, Any]:
        return {
            "INTEGER": "INT64",
            "TEXT": "STRING",
            "REAL": "FLOAT64",
            "BOOLEAN": "BOOL",
            "TIMESTAMP": "TIMESTAMP",
            "DATE": "DATE",
            "DECIMAL": "BIGNUMERIC",
        }
