# src/rhosocial/activerecord/backend/impl/bigquery/mixins/capabilities.py
"""BigQuery capability detection mixin."""

from typing import Dict, Tuple


class BigQueryCapabilityMixin:
    """BigQuery capability detection.

    Aggregated capability checks for BigQuery features.
    """

    #: BigQuery does not accept ``||`` as concatenation at all; the function is
    #: the only spelling.
    STRING_CONCATENATION = "CONCAT"


    def supports_table_comment(self) -> bool:
        """Whether an inline table comment is supported.

        BigQuery has no ``COMMENT`` keyword; a table comment is carried by the
        table's ``OPTIONS(description='...')`` clause.
        """
        return True

    def format_table_comment(self, comment: str) -> Tuple[str, tuple]:
        """Render a table comment as ``OPTIONS(description='...')``.

        The generic ``TableMixin.format_table_comment_clause`` adds the leading
        space and appends the fragment after the column list.
        """
        escaped = self._escape_sql_string(comment)
        return f"OPTIONS(description='{escaped}')", ()

    def supports_cte(self) -> bool:
        return True

    def supports_basic_cte(self) -> bool:
        return True

    def supports_recursive_cte(self) -> bool:
        return True

    def supports_materialized_cte(self) -> bool:
        """Whether the ``AS MATERIALIZED`` / ``AS NOT MATERIALIZED`` CTE hint exists.

        ``False``: the documented grammar is
        ``WITH [RECURSIVE] { non_recursive_cte | recursive_cte }[, ...]`` and
        neither hint string occurs on the query-syntax page; GoogleSQL decides
        materialization itself (recursive CTEs are materialized, non-recursive
        ones are not).

        Declared here because core's ``format_cte_expression`` now consults the
        probe when a hint is requested, so the refusal is this dialect's
        documented answer rather than an inherited default.

        Reference (fetched 2026-10-08):
        https://cloud.google.com/bigquery/docs/reference/standard-sql/query-syntax#with_clause
        """
        return False

    def supports_window_functions(self) -> bool:
        return True

    def supports_window_frame_clause(self) -> bool:
        return True

    def supports_json_operations(self) -> bool:
        return True

    def supports_merge(self) -> bool:
        return True

    def supports_qualify_clause(self) -> bool:
        return True

    def supports_upsert(self) -> bool:
        return True

    def supports_explain(self) -> bool:
        return False

    def supports_explain_plan(self) -> bool:
        return False

    def supports_advanced_grouping(self) -> bool:
        return True

    def supports_arrays(self) -> bool:
        return True

    def supports_views(self) -> bool:
        return True

    def supports_create_or_replace_view(self) -> bool:
        """BigQuery supports CREATE OR REPLACE VIEW."""
        return True

    def supports_if_not_exists_view(self) -> bool:
        """BigQuery does not support IF NOT EXISTS for views."""
        return False

    def supports_truncate(self) -> bool:
        """Whether ``TRUNCATE TABLE`` is supported.

        ``True``: the DML reference documents
        ``TRUNCATE TABLE [[project_name.]dataset_name.]table_name``; truncating
        views, materialized views, models and external tables is not supported,
        but the table statement itself is.  Declared here because core's
        ``format_truncate_statement`` now consults the probe; the answer keeps
        the statement reachable and is this dialect's own.

        Reference (fetched 2026-10-08):
        https://cloud.google.com/bigquery/docs/reference/standard-sql/dml-syntax#truncate_table_statement
        """
        return True

    def supports_truncate_table_keyword(self) -> bool:
        return True

    def supports_union(self) -> bool:
        return True

    def supports_union_all(self) -> bool:
        return True

    def supports_intersect(self) -> bool:
        return True

    def supports_except(self) -> bool:
        return True

    def supports_introspection(self) -> bool:
        return True

    def supports_auto_increment_column(self) -> bool:
        """Whether BigQuery accepts a bare ``AUTO_INCREMENT`` column marker.

        ``False``: ``AUTO_INCREMENT`` is not part of GoogleSQL. BigQuery's
        server-generated column mechanism is the parameterised
        ``GENERATED ... AS IDENTITY`` clause, which is a different node
        (``IdentityClause``) with its own probes; see
        :class:`~...mixins.identity_column.BigQueryIdentityColumnMixin`.

        This replaces the old ``supports_auto_increment()`` probe, which
        answered ``True`` for the standard clause without any renderer ever
        consulting it. The two mechanisms are now declared separately, and
        this one is declined explicitly.
        """
        return False

    def supports_generated_columns(self) -> bool:
        """BigQuery supports GENERATED ALWAYS AS columns."""
        return True

    def supports_stored_generated_columns(self) -> bool:
        """BigQuery generated columns are always stored."""
        return True

    def supports_virtual_generated_columns(self) -> bool:
        """BigQuery does not support VIRTUAL generated columns."""
        return False

    def supports_create_table_like(self) -> bool:
        """BigQuery supports CREATE TABLE ... LIKE (metadata copy)."""
        return True

    def supports_create_table_clone(self) -> bool:
        """BigQuery supports CREATE TABLE ... CLONE / COPY."""
        return True

    def supports_with_data_clause(self) -> bool:
        """Whether the ``WITH [NO] DATA`` population clause exists anywhere.

        ``False`` for all three consumers core's formatters consult:

        * ``CREATE TABLE ... AS query_statement`` -- the CREATE TABLE grammar
          ends at ``[ AS query_statement ]``;
        * ``CREATE MATERIALIZED VIEW ... AS query_expression`` -- the view is
          populated at creation time and the MV grammar has no such clause;
        * ``REFRESH MATERIALIZED VIEW`` -- not a BigQuery statement at all
          (refresh is an ``OPTIONS(enable_refresh=...)`` concern), so the
          statement gate answers first.

        Neither page contains the strings "WITH DATA" or "WITH NO DATA".
        Declared here because core's CTAS renderer now consults the probe, so
        an explicit request is refused by name instead of emitting
        server-rejected SQL.

        References (fetched 2026-10-08):
        https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language#create_table_statement
        https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language#create_materialized_view_statement
        """
        return False

    def supports_create_or_replace_table(self) -> bool:
        """BigQuery supports CREATE OR REPLACE TABLE."""
        return True

    def supports_add_column_if_not_exists(self) -> bool:
        """BigQuery supports ALTER TABLE ADD COLUMN IF NOT EXISTS."""
        return True

    def supports_drop_column_if_exists(self) -> bool:
        """BigQuery supports ALTER TABLE DROP COLUMN IF EXISTS."""
        return True

    def supports_if_exists_table(self) -> bool:
        """BigQuery supports DROP TABLE IF EXISTS."""
        return True

    def supports_drop_table_cascade(self) -> bool:
        """BigQuery does not support CASCADE for DROP TABLE."""
        return False

    def supports_drop_table_restrict(self) -> bool:
        """BigQuery does not support RESTRICT for DROP TABLE."""
        return False

    def supports_json_type(self) -> bool:
        """BigQuery has a JSON type and the functions that read it.

        Declared here rather than in BigQueryJSONMixin: that mixin is not on
        the dialect's MRO at all, and this one sits well before the core
        JSONMixin, so a probe written later would never be reached.
        """
        return True

    #: The JSON path functions BigQuery spells this way. Declared so the
    #: "no foreign syntax" contract can tell a function this dialect has from
    #: one it inherited, and BigQuery has no supports_json_function otherwise.
    _JSON_FUNCTION_NAMES = ("JSON_QUERY", "JSON_VALUE")

    def supports_functions(self) -> Dict[str, bool]:
        """Return supported SQL functions as function_name -> bool mapping.

        BigQuery has no functions module of its own: it renders with the core
        factories and spells them its own way. So the honest answer is the core
        set, less the ones BigQuery spells differently and plus the JSON
        functions declared above.

        The method existed only as a Protocol, so calling it returned None and
        a test asking whether a function was supported raised AttributeError on
        the result rather than skipping the test. An empty mapping would be a
        lie in the other direction — it would skip tests BigQuery passes.
        """
        from ....expression.functions import __all__ as core_functions

        #: Core factories that exist but that BigQuery has no formatter for.
        #: Checked against the core list so a name that is not there does not
        #: masquerade as a decision: naming a function that does not exist
        #: reads as coverage while changing nothing.
        not_available = {
            "json_extract",   # MySQL/MariaDB spelling; BigQuery uses JSON_QUERY
            "xmltable",      # BigQuery has no XMLTABLE
        }
        result = {name: name not in not_available for name in core_functions}
        for name in self._JSON_FUNCTION_NAMES:
            result[name.lower()] = True
        return result

    def supports_json_function(self, function_name: str) -> bool:
        """Whether a named JSON function is available on this server."""
        return function_name.upper() in self._JSON_FUNCTION_NAMES

    def format_json_function_expression(self, expr) -> Tuple[str, tuple]:
        """Render a JSON path with JSON_QUERY / JSON_VALUE.

        The core default emits JSON_EXTRACT and JSON_UNQUOTE, and BigQuery has
        neither — it spells them JSON_QUERY and JSON_VALUE. `->` asks for a
        document and `->>` for text, which is the same distinction those two
        functions draw.
        """
        from ....expression import bases

        if isinstance(expr.column, bases.BaseExpression):
            col_sql, col_params = expr.column.to_sql()
        else:
            col_sql, col_params = self.format_identifier(str(expr.column)), ()

        path = _jsonpath_literal(self, expr.path)
        if expr.operation == "->>":
            sql = f"JSON_VALUE({col_sql}, {path})"
        else:
            sql = f"JSON_QUERY({col_sql}, {path})"

        if expr.alias:
            sql = f"{sql} AS {self.format_identifier(expr.alias)}"
        return sql, col_params



def _jsonpath_literal(dialect, path: str) -> str:
    """Render a jsonpath as a bound-parameter-free SQL string literal.

    BigQuery's JSON functions take the path as a literal, and the shared form
    already is one: ``$.a.b`` needs no rewriting, only quoting and escaping,
    which format_literal is there to do.
    """
    return dialect.format_literal(str(path or "").strip() or "$")

__all__ = ['BigQueryCapabilityMixin']
