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
    # Constraint capability switches, all declared locally and all read off the
    # official ``column_schema`` / ``constraint_definition`` / ``ALTER TABLE``
    # grammar (grammar-only: no BigQuery instance is reachable and the CI
    # emulator implements neither ALTER constraint statement).  Before this
    # mixin the backend declared none of them and inherited core's, whose
    # defaults say ``True`` for CHECK, UNIQUE, MATCH, DEFERRABLE and both
    # referential actions -- all of which BigQuery's grammar rejects.  Ahead of
    # core's ConstraintMixin and DDLColumnMixin so those defaults cannot answer.
    BigQueryConstraintMixin,
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
    # shared spellings verbatim here, and BigQueryLiteralValueMixin follows
    # the same pattern (see its position below).
    BigQueryTrimMixin,
    BigQueryLiteralValueMixin,
)


class BigQueryDialect(
    # The bases below come in bundles: a backend mixin, then the core bundle
    # it stands in for. The backend's answer has to come first -- a mixin
    # placed after the class it overrides never wins -- so a new mixin goes
    # immediately before the core mixin it overrides, and the pairing is read
    # off the list. Two positions sit outside that pairing and are called out
    # where they occur: a mixin that overrides a method ``SQLDialectBase``
    # defines has to precede the base, and a mixin that subclasses a core
    # mixin has to precede it too (C3: a subclass precedes its base).
    # New BigQuery-specific mixins (BEFORE SQLDialectBase and generic mixins they override)
    BigQueryCapabilityMixin,
    BigQueryTypeSupportMixin,
    UserDefinedTypeMixin,
    DomainMixin,
    BigQueryDQLMixin,
    BigQuerySchemaMixin,
    BigQueryDDLColumnMixin,
    # Constraint capability switches. Ahead of core's ConstraintMixin and
    # DDLColumnMixin below: every constraint answer BigQuery gives is declared
    # in this package with the official grammar it rests on, so a moved core
    # default cannot silently become BigQuery's contract.  Several values
    # differ from those defaults -- CHECK, UNIQUE, MATCH, DEFERRABLE, ON DELETE,
    # ON UPDATE are all False here and True there.
    BigQueryConstraintMixin,
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
    # Value literals: BigQuery's spellings ahead of SQLDialectBase, whose
    # portable forms this dialect keeps for the kinds this grammar agrees
    # with. A mixin that overrides format_literal and is placed after the
    # class that defines it never wins the lookup, so this position is
    # structural rather than stylistic.
    BigQueryLiteralValueMixin,
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

    def escape_sql_string(self, value: str) -> str:
        """GoogleSQL's string escaping: backslashes, not quote doubling.

        The base helper doubles single quotes, which is the SQL-standard
        convention. GoogleSQL documents the backslash escape ``\\'`` for a
        single quote -- and, because backslashes introduce escape sequences
        there at all, a literal backslash must itself become ``\\\\`` --
        while quote doubling appears nowhere in its escape table (lexical
        structure and syntax: "Escape sequences for string and bytes
        literals"; not server-verified, read 2026-10-17). The backslash is
        escaped first, then the quote, so neither can eat the other's
        escape. This is the dialect-wide policy: every inline string this
        dialect renders goes through it.
        """
        return value.replace("\\", "\\\\").replace("'", "\\'")

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

    # -- CREATE TABLE diff (the ALTER TABLE probes core consults) -------------

    def supports_alter_column_type(self) -> bool:
        """BigQuery cannot change a column type in place."""
        return False

    def supports_alter_column_properties(self) -> bool:
        """No ALTER COLUMN SET DEFAULT in BigQuery."""
        return False

    def supports_alter_table_index_actions(self) -> bool:
        """BigQuery has no ALTER TABLE ADD/DROP INDEX."""
        return False
