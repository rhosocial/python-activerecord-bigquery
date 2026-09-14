# src/rhosocial/activerecord/backend/impl/bigquery/mixins/ddl.py
"""BigQuery DDL column/index mixin."""
from __future__ import annotations

from typing import Any, Tuple, TYPE_CHECKING

from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError

if TYPE_CHECKING:
    from rhosocial.activerecord.backend.expression.statements.ddl_alter import AddIndex, DropIndex


class BigQueryDDLColumnMixin:
    """BigQuery ALTER TABLE DDL hooks.

    BigQuery cannot change column types in place or add/drop indexes
    via ALTER TABLE.
    """

    def format_add_index_action(self, action: AddIndex) -> Tuple[str, tuple]:
        """BigQuery has no ALTER TABLE ADD INDEX."""
        raise UnsupportedFeatureError(
            self.name,
            "ALTER TABLE ADD INDEX",
            suggestion="Use CREATE SEARCH INDEX to create a search index on the table.",
        )

    def format_drop_index_action(self, action: DropIndex) -> Tuple[str, tuple]:
        """BigQuery has no ALTER TABLE DROP INDEX."""
        raise UnsupportedFeatureError(
            self.name,
            "ALTER TABLE DROP INDEX",
            suggestion="Use DROP SEARCH INDEX ... ON <table> to remove a search index.",
        )

    def alter_column_type_action(self, old_col: Any, new_col: Any) -> Any:
        """Never reachable while _supports_alter_column_type() is False."""
        raise NotImplementedError(
            f"{type(self).__name__} does not support in-place column type "
            f"changes; rebuild the table instead (see RebuildPlan)."
        )


__all__ = ['BigQueryDDLColumnMixin']
