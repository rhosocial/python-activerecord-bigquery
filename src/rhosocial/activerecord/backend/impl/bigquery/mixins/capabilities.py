# src/rhosocial/activerecord/backend/impl/bigquery/mixins/capabilities.py
"""BigQuery capability detection mixin."""


class BigQueryCapabilityMixin:
    """BigQuery capability detection.

    Aggregated capability checks for BigQuery features.
    """

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


__all__ = ['BigQueryCapabilityMixin']
