"""BigQuery SQL dialect implementation."""
from typing import Any, Dict, Optional, Tuple

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

    def supports_basic_cte(self) -> bool:
        # BigQuery Standard SQL supports WITH clauses (common table
        # expressions). ``supports_cte`` is the protocol-name alias used by
        # some code paths; the CTE mixin gates on this method.
        return True

    def supports_recursive_cte(self) -> bool:
        # BigQuery supports ``WITH RECURSIVE``.
        return True

    def supports_materialized_cte(self) -> bool:
        # BigQuery has no MATERIALIZED hint on CTEs (query caching is
        # automatic), so this stays False.
        return False

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

    # -- Schema DDL -----------------------------------------------------------
    # BigQuery qualifies tables with dataset namespaces, but the runtime DDL
    # surface has no ``CREATE SCHEMA``/``DROP SCHEMA`` statement: datasets are
    # created via the management API (bq mk / datasets.insert), not SQL. The
    # renderers below therefore keep only the statement shapes the emulator and
    # service actually accept and reject the rest.

    def supports_schema_if_not_exists(self) -> bool:
        # ``CREATE SCHEMA IF NOT EXISTS`` is not BigQuery SQL; the management
        # API is the only way to create a dataset (idempotently or not).
        return False

    def supports_schema_if_exists(self) -> bool:
        return False

    def supports_schema_cascade(self) -> bool:
        return False

    def supports_schema_authorization(self) -> bool:
        return False

    def format_create_schema_statement(self, expr: Any) -> Tuple[str, tuple]:
        if expr.if_not_exists or expr.authorization:
            raise ValueError(
                "BigQuery CREATE SCHEMA supports neither IF NOT EXISTS nor "
                f"AUTHORIZATION (dataset {expr.schema_name!r}); datasets are "
                "created via the management API."
            )
        return f"CREATE SCHEMA {self.format_identifier(expr.schema_name)}", ()

    def format_drop_schema_statement(self, expr: Any) -> Tuple[str, tuple]:
        if expr.if_exists or expr.cascade:
            raise ValueError(
                "BigQuery DROP SCHEMA supports neither IF EXISTS nor CASCADE "
                f"(dataset {expr.schema_name!r}); datasets are deleted via "
                "the management API."
            )
        return f"DROP SCHEMA {self.format_identifier(expr.schema_name)}", ()

    # -- CREATE TABLE diff (CreateTableExpressionDiffSupport hooks) -----------
    # The generic ``CreateTableExpressionDiffMixin`` (composed via
    # ``SQLDialectBase``) provides the diff implementation; the hooks below
    # adapt the diff to BigQuery's ALTER TABLE vocabulary.
    #
    # BigQuery ALTER TABLE facts pinned here:
    # - ``ALTER TABLE ADD COLUMN`` / ``DROP COLUMN`` / ``RENAME COLUMN`` exist,
    #   so add/drop column changes stay on the in-place path.
    # - Column type changes have no ALTER action: ``ALTER COLUMN TYPE`` is not
    #   BigQuery DDL and even the underlying column type/mode is immutable —
    #   changing it requires recreating the table. The generic default
    #   (``_supports_alter_column_type() → False``) is kept.
    # - ``ALTER COLUMN SET DEFAULT`` is not part of BigQuery's ALTER TABLE
    #   vocabulary (BigQuery has no column DEFAULT), and nullability can only
    #   be relaxed (``ALTER COLUMN ... DROP NOT NULL``), never tightened
    #   (``SET NOT NULL``). The generic mixin emits all four property
    #   operations or none, so property changes must route to a rebuild plan.
    # - There are no traditional indexes (only ``CREATE/DROP SEARCH INDEX``),
    #   so index changes route to a rebuild plan and the ADD/DROP INDEX
    #   renderers are rejected outright.

    def _supports_alter_column_type(self) -> bool:
        """BigQuery cannot change a column type in place — type changes
        rebuild (generic mixin default, kept for self-documentation)."""
        return False

    def _supports_alter_column_properties(self) -> bool:
        """No ``ALTER COLUMN SET DEFAULT`` in BigQuery and nullability can
        only be dropped, never set — property changes rebuild."""
        return False

    def _supports_alter_table_index_actions(self) -> bool:
        """BigQuery has no ``ALTER TABLE ADD/DROP INDEX`` (only SEARCH
        INDEX DDL) — index changes rebuild, carrying the new index set."""
        return False

    def alter_column_type_action(self, old_col: Any, new_col: Any) -> Any:
        """Never reachable while ``_supports_alter_column_type()`` is False;
        kept raising so an accidental flag flip cannot emit BigQuery-invalid
        type-change DDL."""
        raise NotImplementedError(
            f"{type(self).__name__} does not support in-place column type "
            f"changes; rebuild the table instead (see RebuildPlan)."
        )

    def format_add_index_action(self, action: Any) -> Tuple[str, tuple]:
        """BigQuery has no ``ALTER TABLE ADD INDEX``.

        Raises UnsupportedFeatureError — use ``CREATE SEARCH INDEX`` instead.
        """
        from rhosocial.activerecord.backend.dialect.exceptions import (
            UnsupportedFeatureError,
        )

        raise UnsupportedFeatureError(
            self.name,
            "ALTER TABLE ADD INDEX",
            suggestion="Use CREATE SEARCH INDEX to create a search index on the table.",
        )

    def format_drop_index_action(self, action: Any) -> Tuple[str, tuple]:
        """BigQuery has no ``ALTER TABLE DROP INDEX``.

        Raises UnsupportedFeatureError — use ``DROP SEARCH INDEX ... ON <table>``
        instead.
        """
        from rhosocial.activerecord.backend.dialect.exceptions import (
            UnsupportedFeatureError,
        )

        raise UnsupportedFeatureError(
            self.name,
            "ALTER TABLE DROP INDEX",
            suggestion="Use DROP SEARCH INDEX ... ON <table> to remove a search index.",
        )
