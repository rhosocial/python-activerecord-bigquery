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

    # ------------------------------------------------------------------
    # CLAUSE ORDER ON THE COLUMN RENDER PATH -- read before reordering anything
    # ------------------------------------------------------------------
    #
    # ``column_schema`` fixes the order of a column definition, and it is the
    # *reverse* of what most backends use in two places.  Official grammar
    # (transcribed 2026-10-12; no BigQuery instance is reachable, so this is
    # 文档（待云验） -- grammar-only):
    #
    #     column_schema :=
    #     { simple_type | STRUCT<field_list> | ARRAY<array_element_schema> }
    #     [PRIMARY KEY NOT ENFORCED | REFERENCES table_name(column_name) NOT ENFORCED]
    #     [ DEFAULT default_expression | embedding_generation | identity_column ]
    #     [NOT NULL]
    #     [OPTIONS(column_option_list)]
    #
    # Two consequences for anything that builds a ``ColumnDefinition``:
    #
    # 1. ``NOT NULL`` comes AFTER the ``DEFAULT`` / identity group.  On MySQL,
    #    MariaDB, PostgreSQL, SQL Server, Oracle and Firebird the nullability
    #    marker leads.  Here it follows, so ``col STRING NOT NULL DEFAULT 'x'``
    #    is not the shape BigQuery accepts -- it wants
    #    ``col STRING DEFAULT 'x' NOT NULL``.
    # 2. The primary key / reference group comes FIRST, before ``DEFAULT``.
    #
    # Why this is a comment and not a sort: core's ``format_column_definition``
    # renders ``attributes``, then ``constraints``, then
    # ``generated_expression``, then ``comment``, each in the order it was
    # built, and ``format_column_attributes`` explicitly does not sort.  So the
    # order is decided by the order the caller appended constraints, which makes
    # it a property of the *call site*, not something a formatter override can
    # guarantee.  Nothing is sorted or reordered here on purpose -- a renderer
    # that "fixed" the order for BigQuery would break the backends whose order
    # is the other way round.
    #
    # The good news, and the reason this backend has no
    # ``format_column_definition`` override at all: the generic renderer already
    # lands on ``column_schema``'s order when the caller supplies the clauses in
    # grammar order.  Measured on this dialect's own DDL, a column declared with
    # ``[REFERENCES ... not_enforced, DEFAULT, NOT NULL]`` and an
    # ``OPTIONS(description=...)`` comment renders as::
    #
    #     `id` STRING(10) REFERENCES `p`(`id`) NOT ENFORCED DEFAULT 'x'
    #          NOT NULL OPTIONS(description='a note')
    #
    # -- group 1, group 2, group 3, group 4, exactly as ``column_schema`` spells
    # them.  The test that locks this is
    # ``tests/.../test_bigquery_constraint_switches.py::TestClauseOrderIsRecordedOnTheRenderPath``;
    # if a core change reorders the clauses, that test is where it should fail.
    # ------------------------------------------------------------------

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
