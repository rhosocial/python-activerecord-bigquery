"""BigQuery SQL dialect implementation."""
from typing import Any, Dict, Tuple

from rhosocial.activerecord.backend.dialect.base import SQLDialectBase
from rhosocial.activerecord.backend.dialect.protocols import (
    CTESupport, FilterClauseSupport, WindowFunctionSupport, MergeSupport,
    AdvancedGroupingSupport, ArraySupport, ExplainSupport,
    QualifyClauseSupport, UpsertSupport, LateralJoinSupport,
    JoinSupport, ViewSupport, SchemaSupport, IndexSupport,
    ConstraintSupport, IntrospectionSupport, TransactionControlSupport,
    SQLFunctionSupport, JSONSupport, TruncateSupport,
    UserDefinedTypeSupport, DomainSupport,
)
from rhosocial.activerecord.backend.dialect.mixins import (
    CTEMixin, WindowFunctionMixin, JSONMixin,
    ArrayMixin, ExplainMixin, MergeMixin,
    UpsertMixin, LateralJoinMixin, JoinMixin,
    ViewMixin, SchemaMixin, IndexMixin, TableMixin, ConstraintMixin,
    IntrospectionMixin, TruncateMixin,
    # Core generic mixins (backend-agnostic implementations)
    PredicateMixin, ExpressionMixin, DQLMixin, DMLMixin,
    SetOperationMixin, DateTimeMixin,
    DDLColumnMixin, DDLTypeMixin, UserDefinedTypeMixin, DomainMixin,
    TransactionControlMixin, CollationMixin,
)
from .protocols import (
    BigQueryStructSupport, BigQueryArraySupport,
    BigQueryJSONSupport, BigQueryGeographySupport,
)
from .mixins import (
    BigQueryStructMixin, BigQueryArrayMixin,
    BigQueryJSONMixin, BigQueryGeographyMixin,
    # New mixins from dialect.py split
    BigQueryTypeSupportMixin,
    BigQueryDQLMixin,
    BigQuerySchemaMixin,
    BigQueryDDLColumnMixin,
    BigQueryCapabilityMixin,
    BigQueryIdentifierMixin,
)


class BigQueryDialect(
    # New BigQuery-specific mixins (BEFORE SQLDialectBase and generic mixins they override)
    BigQueryCapabilityMixin,
    BigQueryTypeSupportMixin,
    UserDefinedTypeMixin,
    DomainMixin,
    BigQueryDQLMixin,
    BigQuerySchemaMixin,
    BigQueryDDLColumnMixin,
    BigQueryIdentifierMixin,
    SQLDialectBase,
    # Generic mixins
    CTEMixin, WindowFunctionMixin, JSONMixin,
    ArrayMixin, ExplainMixin, MergeMixin,
    UpsertMixin, LateralJoinMixin, JoinMixin,
    ViewMixin, SchemaMixin, IndexMixin, TableMixin, ConstraintMixin,
    IntrospectionMixin, TruncateMixin,
    PredicateMixin, ExpressionMixin, DQLMixin, DMLMixin,
    SetOperationMixin, DateTimeMixin,
    DDLColumnMixin, DDLTypeMixin, TransactionControlMixin,
    CollationMixin,
    BigQueryStructMixin, BigQueryArrayMixin,
    BigQueryJSONMixin, BigQueryGeographyMixin,
    CTESupport, FilterClauseSupport, WindowFunctionSupport, MergeSupport,
    AdvancedGroupingSupport, ArraySupport, ExplainSupport,
    QualifyClauseSupport, UpsertSupport, LateralJoinSupport,
    JoinSupport, ViewSupport, SchemaSupport, IndexSupport,
    ConstraintSupport, IntrospectionSupport, TransactionControlSupport,
    SQLFunctionSupport, JSONSupport, TruncateSupport,
    BigQueryStructSupport, BigQueryArraySupport,
    BigQueryJSONSupport, BigQueryGeographySupport,
    UserDefinedTypeSupport, DomainSupport,
):
    def __init__(self, version: Tuple[int, ...] = (3, 0, 0), **kwargs):
        super().__init__(**kwargs)
        self.version = version

    def get_parameter_placeholder(self, position: int = 0) -> str:
        """BigQuery Standard SQL uses ``?`` positional bind markers."""
        return "?"

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

    # -- CREATE TABLE diff (CreateTableExpressionDiffSupport hooks) -----------

    def supports_alter_column_type(self) -> bool:
        """BigQuery cannot change a column type in place."""
        return False

    def supports_alter_column_properties(self) -> bool:
        """No ALTER COLUMN SET DEFAULT in BigQuery."""
        return False

    def supports_alter_table_index_actions(self) -> bool:
        """BigQuery has no ALTER TABLE ADD/DROP INDEX."""
        return False
