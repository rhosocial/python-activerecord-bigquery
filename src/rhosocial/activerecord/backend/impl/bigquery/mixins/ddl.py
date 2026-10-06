# src/rhosocial/activerecord/backend/impl/bigquery/mixins/ddl.py
"""BigQuery DDL column/index mixin."""
from __future__ import annotations

from typing import Any, Tuple, TYPE_CHECKING

from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError

if TYPE_CHECKING:
    from rhosocial.activerecord.backend.expression.objects import Index
    from rhosocial.activerecord.backend.expression.statements.ddl_alter import (
        AddIndex,
        DropIndex,
    )


class BigQueryDDLColumnMixin:
    """BigQuery ALTER TABLE DDL hooks.

    BigQuery cannot change column types in place or add/drop indexes
    via ALTER TABLE.
    """

    def supports_column_comment(self) -> bool:
        """Whether an inline column comment is supported.

        BigQuery has no ``COMMENT`` keyword; a column comment is carried by
        the column's ``OPTIONS(description='...')`` clause.
        """
        return True

    def format_column_comment_clause(self, clause: Any) -> Tuple[str, tuple]:
        """Render a column comment as ``OPTIONS(description='...')``.

        Returns the fragment with a leading space so it composes directly
        after the column definition. Annotated ``Any`` because this formatter is
        reached from ``CREATE TABLE``'s column loop, where the value is whatever
        clause class the dialect dispatches on.
        """
        escaped = self._escape_sql_string(clause.comment)
        return f" OPTIONS(description='{escaped}')", ()

    def format_column_attribute(self, attr: Any) -> Tuple[str, tuple]:
        """Render a column attribute with BigQuery syntax.

        BigQuery requires the collation specification to be a quoted STRING
        literal (``STRING COLLATE 'und:ci'``), not a bare identifier.
        """
        from rhosocial.activerecord.base import CollationAttribute

        if isinstance(attr, CollationAttribute):
            escaped = attr.name.replace("'", "''")
            return f" COLLATE '{escaped}'", ()
        return super().format_column_attribute(attr)

    def format_add_index_action(self, action: AddIndex) -> Tuple[str, tuple]:
        """BigQuery has no ALTER TABLE ADD INDEX."""
        raise UnsupportedFeatureError(
            self.name,
            "ALTER TABLE ADD INDEX",
            suggestion="Use CREATE SEARCH INDEX to create a search index on the table.",
        )

    def format_drop_index_action(self, action: DropIndex) -> Tuple[str, tuple]:
        """BigQuery has no ALTER TABLE DROP INDEX.

        Raises:
            TypeError: ``action.index`` is not an Index. Checked before the
                capability refusal, as core's own formatter does, so a caller who
                passed the wrong object learns that too rather than fixing one
                error and meeting the other.
            UnsupportedFeatureError: Always, for a correct Index.
        """
        from rhosocial.activerecord.backend.expression.objects import Index

        if not isinstance(action.index, Index):
            raise TypeError(
                f"DropIndex.index must be an Index, "
                f"got {type(action.index).__name__}"
            )
        raise UnsupportedFeatureError(
            self.name,
            "ALTER TABLE DROP INDEX",
            suggestion="Use DROP SEARCH INDEX ... ON <table> to remove a search index.",
        )

    def alter_column_type_action(self, old_col: Any, new_col: Any) -> Any:
        """Never reachable while supports_alter_column_type() is False."""
        raise NotImplementedError(
            f"{type(self).__name__} does not support in-place column type "
            f"changes; rebuild the table instead (see RebuildPlan)."
        )


__all__ = ['BigQueryDDLColumnMixin']
