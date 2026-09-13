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
)
from rhosocial.activerecord.backend.dialect.mixins import (
    CTEMixin, FilterClauseMixin, WindowFunctionMixin, JSONMixin,
    AdvancedGroupingMixin, ArrayMixin, ExplainMixin, MergeMixin,
    QualifyClauseMixin, UpsertMixin, LateralJoinMixin, JoinMixin,
    ViewMixin, SchemaMixin, IndexMixin, TableMixin, ConstraintMixin,
    IntrospectionMixin, TruncateMixin,
    # Core generic mixins (backend-agnostic implementations)
    PredicateMixin, ExpressionMixin, DQLMixin, DMLMixin,
    SetOperationMixin, DateTimeMixin,
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
):
    def __init__(self, version: Tuple[int, ...] = (3, 0, 0), **kwargs):
        super().__init__(**kwargs)
        self.version = version

    # -- DataType formatting -------------------------------------------------
    # Naming-convention formatters driving ``format_data_type()`` (see
    # ``DDLTypeMixin``), mapping the generic expression-layer types onto
    # BigQuery Standard SQL column types.

    def supports_data_type_tinyint(self) -> bool:
        return True

    def format_data_type_tinyint(self, data_type) -> Tuple[str, tuple]:
        return "INT64", ()

    def supports_data_type_smallint(self) -> bool:
        return True

    def format_data_type_smallint(self, data_type) -> Tuple[str, tuple]:
        return "INT64", ()

    def supports_data_type_integer(self) -> bool:
        return True

    def format_data_type_integer(self, data_type) -> Tuple[str, tuple]:
        return "INT64", ()

    def supports_data_type_bigint(self) -> bool:
        return True

    def format_data_type_bigint(self, data_type) -> Tuple[str, tuple]:
        return "INT64", ()

    def supports_data_type_real(self) -> bool:
        return True

    def format_data_type_real(self, data_type) -> Tuple[str, tuple]:
        return "FLOAT64", ()

    def supports_data_type_float(self) -> bool:
        return True

    def format_data_type_float(self, data_type) -> Tuple[str, tuple]:
        return "FLOAT64", ()

    def supports_data_type_double(self) -> bool:
        return True

    def format_data_type_double(self, data_type) -> Tuple[str, tuple]:
        return "FLOAT64", ()

    def supports_data_type_decimal(self) -> bool:
        return True

    def format_data_type_decimal(self, data_type) -> Tuple[str, tuple]:
        if getattr(data_type, "precision", None) is not None:
            scale = getattr(data_type, "scale", 0) or 0
            return f"NUMERIC({data_type.precision}, {scale})", ()
        return "NUMERIC", ()

    def supports_data_type_boolean(self) -> bool:
        return True

    def format_data_type_boolean(self, data_type) -> Tuple[str, tuple]:
        return "BOOL", ()

    def supports_data_type_char(self) -> bool:
        return True

    def format_data_type_char(self, data_type) -> Tuple[str, tuple]:
        length = getattr(data_type, "length", None)
        return (f"STRING({length})", ()) if length else ("STRING", ())

    def supports_data_type_varchar(self) -> bool:
        return True

    def format_data_type_varchar(self, data_type) -> Tuple[str, tuple]:
        length = getattr(data_type, "length", None)
        return (f"STRING({length})", ()) if length else ("STRING", ())

    def supports_data_type_text(self) -> bool:
        return True

    def format_data_type_text(self, data_type) -> Tuple[str, tuple]:
        return "STRING", ()

    def supports_data_type_date(self) -> bool:
        return True

    def format_data_type_date(self, data_type) -> Tuple[str, tuple]:
        return "DATE", ()

    def supports_data_type_time(self) -> bool:
        return True

    def format_data_type_time(self, data_type) -> Tuple[str, tuple]:
        return "TIME", ()

    def supports_data_type_timetz(self) -> bool:
        return True

    def format_data_type_timetz(self, data_type) -> Tuple[str, tuple]:
        return "TIME", ()

    def supports_data_type_datetime(self) -> bool:
        return True

    def format_data_type_datetime(self, data_type) -> Tuple[str, tuple]:
        return "DATETIME", ()

    def supports_data_type_timestamp(self) -> bool:
        return True

    def format_data_type_timestamp(self, data_type) -> Tuple[str, tuple]:
        return "TIMESTAMP", ()

    def supports_data_type_timestamptz(self) -> bool:
        return True

    def format_data_type_timestamptz(self, data_type) -> Tuple[str, tuple]:
        return "TIMESTAMP", ()

    def supports_data_type_blob(self) -> bool:
        return True

    def format_data_type_blob(self, data_type) -> Tuple[str, tuple]:
        return "BYTES", ()

    def supports_data_type_json(self) -> bool:
        return True

    def format_data_type_json(self, data_type) -> Tuple[str, tuple]:
        return "JSON", ()

    def supports_data_type_jsonb(self) -> bool:
        return True

    def format_data_type_jsonb(self, data_type) -> Tuple[str, tuple]:
        return "JSON", ()

    def format_identifier(self, identifier: str, need_quote: bool = True) -> str:
        """Format a BigQuery identifier using backtick quoting.

        Args:
            identifier: Raw identifier string.
            need_quote: Whether the identifier needs quoting. When False the
                identifier is returned unchanged (with a warning if it is a
                reserved word).
        """
        if not need_quote:
            if self.is_reserved_word(identifier):
                import warnings

                from rhosocial.activerecord.backend.warnings import (
                    IdentifierQuotingWarning,
                )

                warnings.warn(
                    f"Identifier '{identifier}' is a reserved word in {self.name} "
                    f"and may cause SQL errors without quoting.",
                    IdentifierQuotingWarning,
                    stacklevel=2,
                )
            return identifier
        escaped = identifier.replace("`", "``")
        return f"`{escaped}`"


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
        # BigQuery natively supports the QUALIFY clause to filter on the
        # results of window functions.
        return True

    def supports_upsert(self) -> bool:
        return True


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

    def format_set_operation_expression(self, expr) -> Tuple[str, tuple]:
        from rhosocial.activerecord.backend.expression.query_sources import SetOperationExpression

        def _render(node) -> Tuple[str, list]:
            sql, params = node.to_sql()
            # BigQuery requires chained/mixed set operations to be grouped with
            # parentheses, e.g. ``(A UNION DISTINCT B) UNION DISTINCT C``.
            if isinstance(node, SetOperationExpression):
                sql = f"({sql})"
            return sql, list(params)

        left_sql, left_params = _render(expr.left)
        right_sql, right_params = _render(expr.right)
        qualifier = " ALL" if expr.all_ else " DISTINCT"
        base_sql = f"{left_sql} {expr.operation}{qualifier} {right_sql}"
        all_params = left_params + right_params
        sql_parts = [base_sql]
        if expr.alias:
            sql_parts.append(f"AS {self.format_identifier(expr.alias)}")
        for clause in (expr.order_by_clause, expr.limit_offset_clause, expr.for_update_clause):
            if clause:
                clause_sql, clause_params = clause.to_sql()
                sql_parts.append(clause_sql)
                all_params.extend(clause_params)
        return " ".join(sql_parts), tuple(all_params)

    def supports_introspection(self) -> bool:
        return True


    def format_column(self, expr) -> Tuple[str, tuple]:
        """Column references are never schema-qualified in BigQuery.

        BigQuery resolves columns as ``table.column`` (or bare ``column``);
        a three-part ``dataset.table.column`` reference parses as an invalid
        combination for the emulator (and is at best a project-qualified
        interpretation on real BigQuery), so ``schema_name`` is dropped
        here. Table references themselves remain schema-qualified via
        :meth:`format_table`.
        """
        if expr.table:
            col_sql = (
                f"{self.format_identifier(expr.table, expr.table_need_quote)}."
                f"{self.format_identifier(expr.name, expr.name_need_quote)}"
            )
        else:
            col_sql = self.format_identifier(expr.name, expr.name_need_quote)
        if expr.alias:
            col_sql = f"{col_sql} AS {self.format_identifier(expr.alias, expr.alias_need_quote)}"
        return col_sql, ()

    def format_wildcard(self, expr) -> Tuple[str, tuple]:
        """Wildcard references in BigQuery use the (2-part) table name only."""
        if expr.table:
            return f"{self.format_identifier(expr.table, expr.table_need_quote)}.*", ()
        return "*", ()




    def supports_auto_increment(self) -> bool:
        # BigQuery tables have no server-side AUTO_INCREMENT/IDENTITY key
        # generation; the backend fills missing primary keys client-side.
        return False

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
