"""BigQuery SQL dialect implementation."""
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from rhosocial.activerecord.backend.dialect.base import SQLDialectBase
from rhosocial.activerecord.backend.dialect.protocols import (
    CTESupport, FilterClauseSupport, WindowFunctionSupport, MergeSupport,
    AdvancedGroupingSupport, ArraySupport, ExplainSupport,
    QualifyClauseSupport, UpsertSupport, LateralJoinSupport,
    JoinSupport, ViewSupport, SchemaSupport, IndexSupport,
    ConstraintSupport, IntrospectionSupport, TransactionControlSupport,
    SQLFunctionSupport, JSONSupport, TruncateSupport,
)
from rhosocial.activerecord.backend.dialect.mixins import (
    CTEMixin, FilterClauseMixin, WindowFunctionMixin, JSONMixin,
    AdvancedGroupingMixin, ArrayMixin, ExplainMixin, MergeMixin,
    QualifyClauseMixin, UpsertMixin, LateralJoinMixin, JoinMixin,
    ViewMixin, SchemaMixin, IndexMixin, TableMixin, ConstraintMixin,
    IntrospectionMixin, TruncateMixin,
    # Core generic mixins (backend-agnostic implementations)
    PredicateMixin, ExpressionMixin, DQLMixin, DMLMixin,
    SetOperationMixin, IdentifierMixin, DateTimeMixin,
    DDLColumnMixin, DDLTypeMixin, TransactionControlMixin,
    CollationMixin,
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
    IntrospectionMixin, TruncateMixin,
    PredicateMixin, ExpressionMixin, DQLMixin, DMLMixin,
    SetOperationMixin, IdentifierMixin, DateTimeMixin,
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
):
    def __init__(self, version: Tuple[int, ...] = (3, 0, 0), **kwargs):
        super().__init__(**kwargs)
        self.version = version

    # -- DataType formatting -------------------------------------------------
    # Registry entries driving ``format_data_type()`` (see DDLTypeMixin),
    # mapping the generic expression-layer types onto BigQuery Standard SQL
    # column types.

    from rhosocial.activerecord.backend.dialect.mixins.ddl_type import DDLTypeMixin as _DDLT
    from rhosocial.activerecord.backend.expression.types import (
        BigIntType, BlobType, BooleanType, CharType, DateTimeType, DateType,
        DecimalType, DoubleType, FloatType, IntegerType, JsonBType, JsonType,
        RealType, SmallIntType, TextType, TimeType, TimeTzType, TimestampType,
        TimestampTzType, TinyIntType, VarCharType,
    )

    @_DDLT.handles(TinyIntType, SmallIntType, IntegerType, BigIntType)
    def _fmt_int64(self, data_type) -> Tuple[str, tuple]:
        return "INT64", ()

    @_DDLT.handles(RealType, FloatType, DoubleType)
    def _fmt_float64(self, data_type) -> Tuple[str, tuple]:
        return "FLOAT64", ()

    @_DDLT.handles(DecimalType)
    def _fmt_numeric(self, data_type) -> Tuple[str, tuple]:
        if getattr(data_type, "precision", None) is not None:
            scale = getattr(data_type, "scale", 0) or 0
            return f"NUMERIC({data_type.precision}, {scale})", ()
        return "NUMERIC", ()

    @_DDLT.handles(BooleanType)
    def _fmt_bool(self, data_type) -> Tuple[str, tuple]:
        return "BOOL", ()

    @_DDLT.handles(CharType)
    def _fmt_char(self, data_type) -> Tuple[str, tuple]:
        length = getattr(data_type, "length", None)
        return (f"STRING({length})", ()) if length else ("STRING", ())

    @_DDLT.handles(VarCharType)
    def _fmt_varchar(self, data_type) -> Tuple[str, tuple]:
        length = getattr(data_type, "length", None)
        return (f"STRING({length})", ()) if length else ("STRING", ())

    @_DDLT.handles(TextType)
    def _fmt_string(self, data_type) -> Tuple[str, tuple]:
        return "STRING", ()

    @_DDLT.handles(DateType)
    def _fmt_date(self, data_type) -> Tuple[str, tuple]:
        return "DATE", ()

    @_DDLT.handles(TimeType, TimeTzType)
    def _fmt_time(self, data_type) -> Tuple[str, tuple]:
        return "TIME", ()

    @_DDLT.handles(DateTimeType)
    def _fmt_datetime(self, data_type) -> Tuple[str, tuple]:
        return "DATETIME", ()

    @_DDLT.handles(TimestampType, TimestampTzType)
    def _fmt_timestamp(self, data_type) -> Tuple[str, tuple]:
        return "TIMESTAMP", ()

    @_DDLT.handles(BlobType)
    def _fmt_bytes(self, data_type) -> Tuple[str, tuple]:
        return "BYTES", ()

    @_DDLT.handles(JsonType, JsonBType)
    def _fmt_json(self, data_type) -> Tuple[str, tuple]:
        return "JSON", ()

    def format_identifier(self, identifier: str) -> str:
        return f"`{identifier}`"

    def get_parameter_placeholder(self, index: int = 0) -> str:
        # BigQuery supports positional `?` parameters. The expression system
        # always emits placeholders with the default index, so named
        # `@param_N` placeholders would collide; positional is the only
        # safe choice here.
        return "?"

    def supports_cte(self) -> bool:
        return True

    def supports_window_functions(self) -> bool:
        return True

    def supports_window_frame_clause(self) -> bool:
        # BigQuery supports ``ROWS BETWEEN`` / ``RANGE BETWEEN`` (the window
        # frame clause is part of the OVER clause in standard BigQuery SQL).
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
        # BigQuery has no EXPLAIN statement; query plans are obtained via
        # dry-run jobs / INFORMATION_SCHEMA instead.
        return False

    def supports_explain_plan(self) -> bool:
        return False

    def supports_advanced_grouping(self) -> bool:
        return True

    def supports_arrays(self) -> bool:
        return True

    def supports_schema(self) -> bool:
        return True

    def supports_views(self) -> bool:
        return True

    def supports_truncate(self) -> bool:
        # BigQuery supports ``TRUNCATE TABLE`` for fast all-row deletion.
        # Used by the test providers' per-test table reset instead of a bare
        # ``DELETE FROM`` (BigQuery Standard SQL requires a WHERE clause on
        # every DELETE, so ``DELETE FROM t`` is a syntax error here).
        return True

    def supports_truncate_table_keyword(self) -> bool:
        return True

    # -- Set operations -----------------------------------------------------
    # BigQuery Standard SQL supports UNION/INTERSECT/EXCEPT, but each operator
    # must be followed by ALL or DISTINCT (a bare ``UNION`` is a syntax
    # error). The generic SetOperationMixin emits a bare ``UNION`` for the
    # ``all_=False`` case, so the formatter is overridden here.

    def supports_union(self) -> bool:
        return True

    def supports_union_all(self) -> bool:
        return True

    def supports_intersect(self) -> bool:
        return True

    def supports_except(self) -> bool:
        return True

    def format_set_operation_expression(
        self, left, right, operation, alias, all_,
        order_by_clause=None, limit_offset_clause=None, for_update_clause=None,
    ) -> Tuple[str, tuple]:
        from rhosocial.activerecord.backend.expression.query_sources import SetOperationExpression

        def _render(expr) -> Tuple[str, list]:
            sql, params = expr.to_sql()
            # BigQuery requires chained/mixed set operations to be grouped with
            # parentheses, e.g. ``(A UNION DISTINCT B) UNION DISTINCT C``.
            if isinstance(expr, SetOperationExpression):
                sql = f"({sql})"
            return sql, list(params)

        left_sql, left_params = _render(left)
        right_sql, right_params = _render(right)
        qualifier = " ALL" if all_ else " DISTINCT"
        base_sql = f"{left_sql} {operation}{qualifier} {right_sql}"
        all_params = left_params + right_params
        sql_parts = [base_sql]
        if alias:
            sql_parts.append(f"AS {self.format_identifier(alias)}")
        for clause in (order_by_clause, limit_offset_clause, for_update_clause):
            if clause:
                clause_sql, clause_params = clause.to_sql()
                sql_parts.append(clause_sql)
                all_params.extend(clause_params)
        return " ".join(sql_parts), tuple(all_params)

    def supports_introspection(self) -> bool:
        return True

    def supports_returning_clause(self) -> bool:
        return False

    def format_column(self, name, table=None, alias=None, schema_name=None):
        """Column references are never schema-qualified in BigQuery.

        BigQuery resolves columns as ``table.column`` (or bare ``column``);
        a three-part ``dataset.table.column`` reference parses as an invalid
        combination for the emulator (and is at best a project-qualified
        interpretation on real BigQuery), so ``schema_name`` is dropped
        here. Table references themselves remain schema-qualified via
        :meth:`format_table`.
        """
        if table:
            col_sql = f"{self.format_identifier(table)}.{self.format_identifier(name)}"
        else:
            col_sql = self.format_identifier(name)
        if alias:
            return f"{col_sql} AS {self.format_identifier(alias)}", ()
        return col_sql, ()

    def format_wildcard(self, table=None, schema_name=None):
        """Wildcard references in BigQuery use the (2-part) table name only."""
        if table:
            wildcard_sql = f"{self.format_identifier(table)}.*"
        else:
            wildcard_sql = "*"
        return wildcard_sql, ()

    def supports_returning_insert(self) -> bool:
        # BigQuery has no RETURNING clause on INSERT/UPDATE/DELETE.
        return False

    def supports_returning_update(self) -> bool:
        return False

    def supports_returning_delete(self) -> bool:
        return False

    def supports_auto_increment(self) -> bool:
        # BigQuery tables have no server-side AUTO_INCREMENT/IDENTITY key
        # generation; the backend fills missing primary keys client-side.
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
