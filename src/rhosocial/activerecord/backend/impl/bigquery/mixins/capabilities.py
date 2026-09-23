# src/rhosocial/activerecord/backend/impl/bigquery/mixins/capabilities.py
"""BigQuery capability detection mixin."""

from typing import Tuple


class BigQueryCapabilityMixin:
    """BigQuery capability detection.

    Aggregated capability checks for BigQuery features.
    """

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

    def supports_auto_increment(self) -> bool:
        """BigQuery supports ``GENERATED ... AS IDENTITY`` columns."""
        return True

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


__all__ = ['BigQueryCapabilityMixin']
