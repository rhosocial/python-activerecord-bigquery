"""BigQuery SQL dialect implementation."""
from typing import Any, Dict, Tuple

from rhosocial.activerecord.backend.dialect.base import SQLDialectBase
from rhosocial.activerecord.backend.dialect.protocols import (
    CTESupport, FilterClauseSupport, WindowFunctionSupport, MergeSupport,
    AdvancedGroupingSupport, ArraySupport, ExplainSupport,
    QualifyClauseSupport, UpsertSupport, LateralJoinSupport,
    JoinSupport,
    # The object protocols derive from NamespaceSupport, so a subclass has to
    # precede its base: C3 will not accept NamespaceSupport ahead of them.
    ViewObjectSupport, IndexObjectSupport,
    ConstraintSupport, IntrospectionSupport, TransactionControlSupport,
    SQLFunctionSupport, JSONSupport, TruncateSupport,
    # One protocol per TYPE / DOMAIN statement, in place of the two umbrella
    # protocols this backend used to inherit. BigQuery supports none of them,
    # and each switch answers False through the core mixins above.
    CreateTypeSupport, AlterTypeSupport, DropTypeSupport,
    CreateDomainSupport, AlterDomainSupport, DropDomainSupport,
    NamespaceSupport,
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
    # The two auto-increment mechanisms: BigQuery declares the parameterised
    # identity clause through BigQueryIdentityColumnMixin, and inherits
    # AutoIncrementMixin so the parameterless AUTO_INCREMENT marker refuses
    # through its probe (False) rather than through a missing formatter.
    IdentityColumnMixin, AutoIncrementMixin,
    RelationSourceMixin,
    # One format_<kind>_object per catalogue kind, all of them core's spelling,
    # and NamespaceMixin for the levels behind them. BigQuery overrides none.
    TableNameMixin, ViewNameMixin, MaterializedViewNameMixin,
    ForeignTableNameMixin, IndexNameMixin, SequenceNameMixin,
    TriggerNameMixin, FunctionNameMixin, ProcedureNameMixin,
    TypeNameMixin, DomainNameMixin, SynonymNameMixin,
    SchemaNameMixin, DatabaseNameMixin, PropertyGraphNameMixin,
    NamespaceMixin,
    # ``LPAD``/``RPAD``/``REPEAT`` are nodes with default formatters, and
    # BigQuery spells all three natively (string_functions: ``LPAD`` /
    # ``RPAD`` truncate at ``return_length`` and refuse a negative one or an
    # empty ``pattern``; ``REPEAT(original, repetitions)`` refuses a negative
    # count), so the shared defaults are the answer for those three and no
    # override is needed. ``TRIM`` differs and is overridden by
    # BigQueryTrimMixin (below) for the reason documented there.
    LpadMixin, RepeatMixin, RpadMixin,
)
from .protocols import (
    BigQueryArraySupport,
    BigQueryColumnQualificationSupport,
    BigQueryGeographySupport,
    BigQueryJSONSupport,
    BigQueryMaterializedViewSupport,
    BigQuerySchemaSupport,
    BigQueryStructSupport,
)
from .mixins import (
    BigQueryStructMixin, BigQueryArrayMixin,
    BigQueryJSONMixin, BigQueryGeographyMixin,
    # New mixins from dialect.py split
    BigQueryTypeSupportMixin,
    BigQueryDQLMixin,
    BigQuerySchemaMixin,
    BigQueryNamespaceMixin,
    BigQueryDDLColumnMixin,
    BigQueryCapabilityMixin,
    BigQueryColumnTypeMixin,
    BigQueryIdentityColumnMixin,
    BigQueryIdentifierMixin,
    BigQueryMaterializedViewMixin,
    # Transaction formatting owns the refusals for the lock-wait pair
    # (WAIT / NO WAIT) that BigQuery's grammar does not have; core's generic
    # renderer would drop them silently. Before TransactionControlMixin.
    BigQueryTransactionMixin,
    # TRIM is the one of the four string nodes BigQuery spells differently:
    # the direction lives in the function name, so BigQueryTrimMixin must
    # outrank core's TrimMixin in the MRO. LPAD, RPAD and REPEAT are the
    # shared spellings verbatim here.
    BigQueryTrimMixin,
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
    # Identity is a parameterised column clause, so its spelling lives with the
    # column DDL mixin and ahead of core's IdentityColumnMixin. BigQuery's
    # grammar makes the option parentheses literal; the probes come from the
    # documented Preview feature.
    BigQueryIdentityColumnMixin,
    BigQueryIdentifierMixin,
    BigQueryMaterializedViewMixin,  # Before ViewMixin to override materialized view DDL
    # Transaction formatting: core's TransactionControlMixin drops the
    # lock-wait pair silently, so the refusals live here, ahead of it.
    BigQueryTransactionMixin,
    # TRIM is the one of the four string nodes BigQuery spells differently:
    # the direction lives in the function name, so this must outrank core's
    # TrimMixin, which appears in the generic block below. LPAD, RPAD and
    # REPEAT are the shared spellings verbatim here, so the generic mixins
    # answer for those three unchanged.
    BigQueryTrimMixin,
    # The backend's one naming-side mixin: both levels rendered, and
    # validate_catalog_name narrowed, because a BigQuery path is
    # project.dataset.object and a project with no dataset is not a name.
    # Before core's NamespaceMixin and before the object protocols, which derive
    # from NamespaceSupport -- C3 linearisation gives the first name priority,
    # and moving this after NamespaceMixin would render every BigQuery name
    # unqualified and still produce well-formed SQL.
    BigQueryNamespaceMixin,
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
    # LPAD/RPAD/REPEAT are the three of the four string nodes BigQuery spells
    # natively, so the shared defaults are the answer for them unchanged;
    # TRIM is the one with a local override above.
    LpadMixin, RepeatMixin, RpadMixin,
    # The two auto-increment mechanisms. BigQueryIdentityColumnMixin (above)
    # owns the identity spelling and its probes; core's IdentityColumnMixin
    # keeps the protocol in the MRO, and AutoIncrementMixin supplies the
    # parameterless AUTO_INCREMENT formatter, whose probe answers False here.
    IdentityColumnMixin, AutoIncrementMixin,
    # The FROM side of a named object. BigQuery has no time-travel clause, so
    # the branch of format_named_relation that would need a temporal formatter
    # is never taken and TemporalTableMixin stays off the dialect.
    RelationSourceMixin,
    # Column types. BigQueryColumnTypeMixin (from .mixins, above) states the
    # whole eighteen-entry table: the rebuilt core declares no generic
    # common-type table to compose behind it, so this is the answer the model
    # layer reads and it may move as a unit without disturbing the order
    # around it.
    BigQueryColumnTypeMixin,
    # One format_<kind>_object per catalogue kind, all of them core's spelling,
    # and NamespaceMixin for the levels behind them. BigQuery overrides none.
    TableNameMixin, ViewNameMixin, MaterializedViewNameMixin,
    ForeignTableNameMixin, IndexNameMixin, SequenceNameMixin,
    TriggerNameMixin, FunctionNameMixin, ProcedureNameMixin,
    TypeNameMixin, DomainNameMixin, SynonymNameMixin,
    SchemaNameMixin, DatabaseNameMixin, PropertyGraphNameMixin,
    NamespaceMixin,
    BigQueryStructMixin, BigQueryArrayMixin,
    BigQueryJSONMixin, BigQueryGeographyMixin,
    CTESupport, FilterClauseSupport, WindowFunctionSupport, MergeSupport,
    AdvancedGroupingSupport, ArraySupport, ExplainSupport,
    QualifyClauseSupport, UpsertSupport, LateralJoinSupport,
    JoinSupport, ViewObjectSupport, IndexObjectSupport,
    ConstraintSupport, IntrospectionSupport, TransactionControlSupport,
    SQLFunctionSupport, JSONSupport, TruncateSupport,
    BigQueryStructSupport, BigQueryArraySupport,
    BigQueryJSONSupport, BigQueryGeographySupport,
    BigQuerySchemaSupport,
    BigQueryColumnQualificationSupport,
    BigQueryMaterializedViewSupport,
    CreateTypeSupport, AlterTypeSupport, DropTypeSupport,
    CreateDomainSupport, AlterDomainSupport, DropDomainSupport,
    NamespaceSupport,
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
