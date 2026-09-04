# tests/rhosocial/activerecord_bigquery_test/feature/backend/ddl/test_create_table_expression_diff.py
"""BigQuery coverage for expression-level CREATE TABLE diffing.

The generic diff pipeline (``CreateTableExpressionDiffMixin`` on
``SQLDialectBase``, dataclasses in
``rhosocial.activerecord.backend.expression.statements.ddl_diff``) is covered
backend-agnostically in the core repository. This module pins the
BigQuery-specific hook configuration against BigQuery's ALTER TABLE facts:

- ``_supports_alter_column_type()`` → False: BigQuery has no
  ``ALTER COLUMN TYPE`` and column types are immutable in place; type changes
  route to a rebuild plan.
- ``_supports_alter_column_properties()`` → False: BigQuery has no column
  ``DEFAULT`` (so ``SET/DROP DEFAULT`` does not exist) and nullability can
  only be relaxed (``DROP NOT NULL``), never tightened (``SET NOT NULL``).
  The generic mixin emits all four property operations or none, so property
  changes must rebuild.
- ``_supports_alter_table_index_actions()`` → False: BigQuery has no
  traditional indexes (only ``CREATE/DROP SEARCH INDEX``), so index changes
  route to a rebuild plan and the ADD/DROP INDEX renderers are rejected.
- ``format_alter_column_action`` (generic ``ALTER COLUMN ...`` renderer) is
  never reached by the diff pipeline because the two hooks above are False.
- ``format_modify_column_action`` (inherited from ``DDLColumnMixin``) raises
  ``UnsupportedFeatureError`` — BigQuery has no ``MODIFY COLUMN``.
- ``ALTER TABLE ADD COLUMN``/``DROP COLUMN`` are supported (BigQuery cannot
  add REQUIRED columns, but the diff never produces them here), so column
  add/drop stays on the in-place path.

All cases are expression-level only — no database connection is used.
"""

import pytest

from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError
from rhosocial.activerecord.backend.dialect.protocols import CreateTableExpressionDiffSupport
from rhosocial.activerecord.backend.expression import DiffPlan, RebuildPlan
from rhosocial.activerecord.backend.expression.statements.ddl_alter import (
    AddColumn,
    AddIndex,
    AddTableConstraint,
    DropColumn,
    DropIndex,
    ModifyColumn,
    RenameTable,
)
from rhosocial.activerecord.backend.expression.statements.ddl_table import (
    ColumnConstraint,
    ColumnConstraintType,
    ColumnDefinition,
    CreateTableExpression,
    ForeignKeyConstraint,
    IndexDefinition,
    TableConstraint,
    TableConstraintType,
    TableOptions,
)
from rhosocial.activerecord.backend.expression.types import (
    DecimalType,
    IntegerType,
    TextType,
    VarCharType,
)
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect
from rhosocial.activerecord.backend.impl.dummy.dialect import DummyDialect


def _col(name, dtype, *constraints):
    return ColumnDefinition(name=name, data_type=dtype, constraints=list(constraints))


def _pk():
    return ColumnConstraint(constraint_type=ColumnConstraintType.PRIMARY_KEY)


def _not_null():
    return ColumnConstraint(constraint_type=ColumnConstraintType.NOT_NULL)


def _default(value):
    return ColumnConstraint(constraint_type=ColumnConstraintType.DEFAULT, default_value=value)


def _expr(dialect, columns, indexes=None, table_constraints=None, **kwargs):
    return CreateTableExpression(
        dialect=dialect,
        table=kwargs.pop("table", "items"),
        columns=columns,
        indexes=indexes,
        table_constraints=table_constraints,
        **kwargs,
    )


@pytest.fixture
def dialect():
    return BigQueryDialect()


# ---------------------------------------------------------------------------
# Hook configuration / protocol conformance
# ---------------------------------------------------------------------------

class TestProtocolConformance:

    def test_dialect_satisfies_diff_protocol(self, dialect):
        assert isinstance(dialect, CreateTableExpressionDiffSupport)

    def test_mixin_provides_entry_point(self):
        from rhosocial.activerecord.backend.dialect.mixins.ddl_diff import (
            CreateTableExpressionDiffMixin,
        )
        assert hasattr(CreateTableExpressionDiffMixin, "diff_create_table")

    def test_type_changes_rebuild(self, dialect):
        # ALTER COLUMN TYPE is not BigQuery DDL; column types are immutable
        # in place and changes require recreating the table.
        assert dialect._supports_alter_column_type() is False

    def test_property_changes_rebuild(self, dialect):
        # No SET/DROP DEFAULT (BigQuery has no column DEFAULT) and nullability
        # can only be relaxed, never tightened.
        assert dialect._supports_alter_column_properties() is False

    def test_index_actions_rebuild(self, dialect):
        # Only SEARCH INDEX exists; no ALTER TABLE ADD/DROP INDEX.
        assert dialect._supports_alter_table_index_actions() is False

    def test_alter_column_type_action_raises(self, dialect):
        with pytest.raises(NotImplementedError):
            dialect.alter_column_type_action(_col("x", IntegerType()), _col("x", TextType()))

    def test_add_index_renderer_rejects(self, dialect):
        action = AddIndex(dialect, index=IndexDefinition(name="idx_x", columns=["id"]))
        with pytest.raises(UnsupportedFeatureError):
            dialect.format_add_index_action(action)

    def test_drop_index_renderer_rejects(self, dialect):
        action = DropIndex(dialect, index="idx_x")
        with pytest.raises(UnsupportedFeatureError):
            dialect.format_drop_index_action(action)

    def test_modify_column_renderer_rejects(self, dialect):
        action = ModifyColumn(dialect, column=_col("x", TextType()))
        with pytest.raises(UnsupportedFeatureError):
            dialect.format_modify_column_action(action)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation:

    def test_cross_dialect_raises(self, dialect):
        old = _expr(dialect, [_col("id", IntegerType(), _pk())])
        new = _expr(DummyDialect(), [_col("id", IntegerType(), _pk())])
        with pytest.raises(ValueError, match="different dialects"):
            old.diff(new)

    def test_cross_table_raises(self, dialect):
        old = _expr(dialect, [_col("id", IntegerType(), _pk())])
        new = _expr(dialect, [_col("id", IntegerType(), _pk())], table="other")
        with pytest.raises(ValueError, match="different tables"):
            old.diff(new)


# ---------------------------------------------------------------------------
# No change
# ---------------------------------------------------------------------------

class TestNoChange:

    def test_identical_definitions_empty_plan(self, dialect):
        cols = [_col("id", IntegerType(), _pk()), _col("name", TextType())]
        plan = _expr(dialect, cols).diff(_expr(dialect, cols))
        assert isinstance(plan, DiffPlan)
        assert not plan.has_changes
        assert plan.alters == []
        assert plan.rebuild is None

    def test_diff_is_symmetric_for_no_change(self, dialect):
        cols = [_col("id", IntegerType(), _pk())]
        old = _expr(dialect, cols)
        new = _expr(dialect, cols)
        assert old.diff(new).has_changes == new.diff(old).has_changes


# ---------------------------------------------------------------------------
# Column add / drop (in-place — BigQuery supports both)
# ---------------------------------------------------------------------------

class TestColumnChanges:

    def test_added_column_renders_bq_add_column(self, dialect):
        old = _expr(dialect, [_col("id", IntegerType(), _pk())])
        new = _expr(dialect, [_col("id", IntegerType(), _pk()), _col("bio", TextType())])
        plan = old.diff(new)
        assert plan.rebuild is None and plan.has_changes
        (alter,) = plan.alters
        (action,) = alter.actions
        assert isinstance(action, AddColumn)
        assert action.column.name == "bio"
        sql, params = alter.to_sql()
        assert sql == "ALTER TABLE `items`  ADD COLUMN `bio` STRING"
        assert params == ()

    def test_added_nullable_column_is_not_required(self, dialect):
        """BigQuery cannot ADD a REQUIRED column; the diff only ever adds the
        new column definition as given — a nullable column renders without
        NOT NULL, which BigQuery accepts."""
        old = _expr(dialect, [_col("id", IntegerType(), _pk())])
        new = _expr(dialect, [_col("id", IntegerType(), _pk()), _col("bio", TextType())])
        sql, _ = old.diff(new).alters[0].to_sql()
        assert "NOT NULL" not in sql

    def test_removed_column_renders_bq_drop_column(self, dialect):
        old = _expr(dialect, [_col("id", IntegerType(), _pk()), _col("bio", TextType())])
        new = _expr(dialect, [_col("id", IntegerType(), _pk())])
        plan = old.diff(new)
        (alter,) = plan.alters
        assert isinstance(alter.actions[0], DropColumn)
        assert alter.actions[0].column_name == "bio"
        sql, _ = alter.to_sql()
        assert sql == "ALTER TABLE `items`  DROP COLUMN `bio`"

    def test_rename_is_not_detected(self):
        """Renaming is rendered as drop + add (rename detection needs user intent)."""
        d = BigQueryDialect()
        old = _expr(d, [_col("id", IntegerType(), _pk()), _col("a", TextType())])
        new = _expr(d, [_col("id", IntegerType(), _pk()), _col("b", TextType())])
        plan = old.diff(new)
        kinds = {type(a).__name__ for a in plan.alters[0].actions}
        assert kinds == {"DropColumn", "AddColumn"}

    def test_added_and_removed_in_one_statement(self, dialect):
        old = _expr(dialect, [_col("id", IntegerType(), _pk()), _col("a", TextType())])
        new = _expr(dialect, [_col("id", IntegerType(), _pk()), _col("b", TextType())])
        plan = old.diff(new)
        assert len(plan.alters[0].actions) == 2


# ---------------------------------------------------------------------------
# Column property changes → RebuildPlan (no ALTER COLUMN vocabulary)
# ---------------------------------------------------------------------------

class TestColumnPropertyChanges:

    def test_set_default_rebuilds(self, dialect):
        # BigQuery has no column DEFAULT; SET DEFAULT is not BigQuery DDL.
        old = _expr(dialect, [_col("status", TextType())])
        new = _expr(dialect, [_col("status", TextType(), _default("ok"))])
        plan = old.diff(new)
        assert plan.alters == []
        rp = plan.rebuild
        assert rp is not None
        assert "property change not supported in-place" in rp.reason
        assert "status" in rp.reason

    def test_drop_default_rebuilds(self, dialect):
        old = _expr(dialect, [_col("status", TextType(), _default("ok"))])
        new = _expr(dialect, [_col("status", TextType())])
        plan = old.diff(new)
        assert plan.alters == []
        assert plan.rebuild is not None

    def test_set_not_null_rebuilds(self, dialect):
        # BigQuery nullability can only be relaxed (DROP NOT NULL), never
        # tightened (SET NOT NULL) — and the generic mixin emits all four
        # property operations or none, so this rebuilds too.
        old = _expr(dialect, [_col("name", TextType())])
        new = _expr(dialect, [_col("name", TextType(), _not_null())])
        plan = old.diff(new)
        assert plan.alters == []
        assert plan.rebuild is not None
        assert "property change not supported in-place" in plan.rebuild.reason

    def test_drop_not_null_rebuilds(self, dialect):
        # Even the one property operation BigQuery could execute (DROP NOT
        # NULL) rebuilds, because the mixin cannot emit it in isolation.
        old = _expr(dialect, [_col("name", TextType(), _not_null())])
        new = _expr(dialect, [_col("name", TextType())])
        plan = old.diff(new)
        assert plan.alters == []
        assert plan.rebuild is not None

    def test_property_change_plan_has_no_alter_column_actions(self, dialect):
        """The AlterColumn path is never taken: no SET_DEFAULT/SET_NOT_NULL
        action can appear in a BigQuery diff plan."""
        old = _expr(dialect, [_col("name", TextType(), _not_null())])
        new = _expr(dialect, [_col("name", TextType(), _default("x"))])
        plan = old.diff(new)
        assert plan.rebuild is not None
        assert plan.alters == []


# ---------------------------------------------------------------------------
# Type changes → RebuildPlan
# ---------------------------------------------------------------------------

class TestTypeChangeRebuild:

    def test_type_change_yields_rebuild_plan(self, dialect):
        old = _expr(dialect, [_col("id", IntegerType(), _pk()), _col("code", IntegerType())])
        new = _expr(dialect, [_col("id", IntegerType(), _pk()), _col("code", TextType())])
        plan = old.diff(new)
        assert plan.alters == []
        rp = plan.rebuild
        assert isinstance(rp, RebuildPlan)
        assert "type change" in rp.reason
        assert "BigQuery" in rp.reason

    def test_rebuild_plan_shape(self, dialect):
        old = _expr(dialect, [_col("id", IntegerType(), _pk()), _col("code", IntegerType())])
        new = _expr(dialect, [_col("id", IntegerType(), _pk()), _col("code", TextType())])
        rp = old.diff(new).rebuild
        assert rp.create.table_name == "items__rebuild__"
        assert rp.drop_old.table.name == "items"
        assert rp.temp_table_name == "items__rebuild__"
        rename_action = rp.rename.actions[0]
        assert isinstance(rename_action, RenameTable)
        assert rename_action.new_name == "items"
        assert rp.copy_columns == ["id", "code"]
        stmts = rp.ordered_statements()
        assert stmts[0] is rp.create and stmts[1] is rp.drop_old and stmts[2] is rp.rename

    def test_rebuild_plan_renders_bq_sql(self, dialect):
        old = _expr(dialect, [_col("id", IntegerType(), _pk()), _col("code", IntegerType())])
        new = _expr(dialect, [_col("id", IntegerType(), _pk()), _col("code", TextType())])
        rp = old.diff(new).rebuild
        create_sql, _ = rp.create.to_sql()
        drop_sql, _ = rp.drop_old.to_sql()
        rename_sql, _ = rp.rename.to_sql()
        assert create_sql == "CREATE TABLE `items__rebuild__` (`id` INT64 PRIMARY KEY, `code` STRING)"
        assert drop_sql == "DROP TABLE `items`"
        assert rename_sql == "ALTER TABLE `items__rebuild__`  RENAME TO `items`"

    def test_varchar_length_change_rebuilds(self, dialect):
        # STRING(50) → STRING(100): still a data-type equality miss, so rebuild.
        old = _expr(dialect, [_col("name", VarCharType(length=50))])
        new = _expr(dialect, [_col("name", VarCharType(length=100))])
        plan = old.diff(new)
        assert plan.alters == []
        assert plan.rebuild is not None

    def test_numeric_precision_change_rebuilds(self, dialect):
        # NUMERIC(10,2) → NUMERIC(20,4): no in-place type change on BigQuery.
        old = _expr(dialect, [_col("amount", DecimalType(precision=10, scale=2))])
        new = _expr(dialect, [_col("amount", DecimalType(precision=20, scale=4))])
        plan = old.diff(new)
        assert plan.alters == []
        assert plan.rebuild is not None
        assert "type change" in plan.rebuild.reason


# ---------------------------------------------------------------------------
# Index changes → RebuildPlan (no traditional indexes on BigQuery)
# ---------------------------------------------------------------------------

class TestIndexChanges:

    def test_added_index_rebuilds(self, dialect):
        old = _expr(dialect, [_col("id", IntegerType(), _pk())])
        new = _expr(dialect, [_col("id", IntegerType(), _pk())],
                    indexes=[IndexDefinition(name="idx_id", columns=["id"])])
        plan = old.diff(new)
        assert plan.alters == []
        rp = plan.rebuild
        assert rp is not None
        assert "index change" in rp.reason
        # The recreated table carries the new index set.
        assert {i.name for i in rp.create.indexes} == {"idx_id"}

    def test_removed_index_rebuilds(self, dialect):
        old = _expr(dialect, [_col("id", IntegerType(), _pk())],
                    indexes=[IndexDefinition(name="idx_id", columns=["id"])])
        new = _expr(dialect, [_col("id", IntegerType(), _pk())])
        plan = old.diff(new)
        assert plan.alters == []
        assert plan.rebuild is not None
        assert plan.rebuild.create.indexes == []

    def test_redefined_index_rebuilds(self, dialect):
        old = _expr(dialect, [_col("id", IntegerType(), _pk()), _col("code", IntegerType())],
                    indexes=[IndexDefinition(name="idx_code", columns=["code"])])
        new = _expr(dialect, [_col("id", IntegerType(), _pk()), _col("code", IntegerType())],
                    indexes=[IndexDefinition(name="idx_code", columns=["code"], unique=True)])
        plan = old.diff(new)
        assert plan.alters == []
        assert plan.rebuild is not None

    def test_index_change_rebuild_carries_previous_indexes(self, dialect):
        """The rebuild create must keep the untouched index so it is not
        silently lost when the table is recreated."""
        old = _expr(dialect, [_col("id", IntegerType(), _pk()), _col("code", IntegerType())],
                    indexes=[IndexDefinition(name="idx_code", columns=["code"])])
        new = _expr(dialect, [_col("id", IntegerType(), _pk()), _col("code", IntegerType())],
                    indexes=[
                        IndexDefinition(name="idx_code", columns=["code"]),
                        IndexDefinition(name="idx_id", columns=["id"]),
                    ])
        plan = old.diff(new)
        rp = plan.rebuild
        assert rp is not None
        assert {i.name for i in rp.create.indexes} == {"idx_code", "idx_id"}


# ---------------------------------------------------------------------------
# Table constraints
# ---------------------------------------------------------------------------

class TestTableConstraintChanges:

    def test_pk_change_rebuilds(self, dialect):
        old = _expr(dialect, [_col("id", IntegerType()), _col("code", TextType())],
                    table_constraints=[TableConstraint(
                        constraint_type=TableConstraintType.PRIMARY_KEY, columns=["id"])])
        new = _expr(dialect, [_col("id", IntegerType()), _col("code", TextType())],
                    table_constraints=[TableConstraint(
                        constraint_type=TableConstraintType.PRIMARY_KEY, columns=["code"])])
        plan = old.diff(new)
        assert plan.rebuild is not None
        assert "primary key" in plan.rebuild.reason

    def test_named_unique_constraint_add_renders(self, dialect):
        old = _expr(dialect, [_col("id", IntegerType(), _pk()), _col("email", TextType())])
        new = _expr(dialect, [_col("id", IntegerType(), _pk()), _col("email", TextType())],
                    table_constraints=[TableConstraint(
                        constraint_type=TableConstraintType.UNIQUE,
                        name="uq_email", columns=["email"])])
        plan = old.diff(new)
        (alter,) = plan.alters
        assert len(alter.actions) == 1
        assert isinstance(alter.actions[0], AddTableConstraint)
        sql, params = alter.to_sql()
        assert sql == "ALTER TABLE `items`  ADD CONSTRAINT `uq_email` UNIQUE (`email`)"
        assert params == ()

    def test_named_fk_constraint_target_change(self, dialect):
        """Named constraint changes go drop-then-add through the constraint
        action renderers (BigQuery accepts ADD/DROP CONSTRAINT for these)."""
        fk_a = ForeignKeyConstraint(
            name="fk_uid", columns=["uid"], foreign_key_table="a", foreign_key_columns=["id"],
        )
        fk_b = ForeignKeyConstraint(
            name="fk_uid", columns=["uid"], foreign_key_table="b", foreign_key_columns=["id"],
        )
        old = _expr(dialect, [_col("uid", IntegerType())], table_constraints=[fk_a])
        new = _expr(dialect, [_col("uid", IntegerType())], table_constraints=[fk_b])
        plan = old.diff(new)
        assert plan.rebuild is None
        actions = plan.alters[0].actions
        assert len(actions) == 2
        sql, _ = plan.alters[0].to_sql()
        assert "DROP CONSTRAINT `fk_uid`" in sql
        assert "ADD CONSTRAINT `fk_uid` FOREIGN KEY (`uid`) REFERENCES `b`(`id`)" in sql

    def test_unnamed_constraint_change_rebuilds(self, dialect):
        old = _expr(dialect, [_col("id", IntegerType(), _pk()), _col("a", IntegerType())],
                    table_constraints=[TableConstraint(
                        constraint_type=TableConstraintType.UNIQUE, columns=["a"])])
        new = _expr(dialect, [_col("id", IntegerType(), _pk()), _col("a", IntegerType())])
        plan = old.diff(new)
        assert plan.rebuild is not None
        assert "unnamed" in plan.rebuild.reason


# ---------------------------------------------------------------------------
# Structural changes → rebuild
# ---------------------------------------------------------------------------

class TestStructuralChanges:

    def test_table_options_change_rebuilds(self, dialect):
        old = _expr(dialect, [_col("id", IntegerType(), _pk())])
        new = _expr(dialect, [_col("id", IntegerType(), _pk())],
                    table_options=TableOptions(charset="utf8mb4"))
        plan = old.diff(new)
        assert plan.rebuild is not None
        assert "structural" in plan.rebuild.reason

    def test_partition_change_rebuilds(self, dialect):
        """Partition additions/removals always rebuild — no backend ALTERs a
        partition key onto an existing table (BigQuery partitioning is fixed
        at creation time too)."""
        from rhosocial.activerecord.backend.expression.core import Column
        from rhosocial.activerecord.backend.expression.statements.ddl_partition import (
            PartitionClause,
            PartitionStrategy,
        )

        old = _expr(dialect, [_col("id", IntegerType(), _pk()), _col("created", TextType())])
        new = _expr(
            dialect, [_col("id", IntegerType(), _pk()), _col("created", TextType())],
            partition=PartitionClause(
                dialect, PartitionStrategy.RANGE, keys=[Column(dialect, "created")],
            ),
        )
        plan = old.diff(new)
        assert plan.alters == []
        assert plan.rebuild is not None

    def test_temporary_flag_change_rebuilds(self, dialect):
        """Structural fields (temporary/…) are compared by _tables_equal; a
        temporary-only change must not return an empty plan (silent miss)."""
        old = _expr(dialect, [_col("id", IntegerType(), _pk())])
        new = _expr(dialect, [_col("id", IntegerType(), _pk())], temporary=True)
        plan = old.diff(new)
        assert plan.rebuild is not None
        assert "structural" in plan.rebuild.reason


# ---------------------------------------------------------------------------
# Defect regressions (mirrors of the core-repository regression suite)
# ---------------------------------------------------------------------------

class TestDefectRegressions:

    def test_fk_table_constraint_signature_branch(self):
        """Regression (core): _constraint_signature accessed
        ``foreign_key_reference`` — an attribute only ColumnConstraint has.
        A TableConstraint carrying ``foreign_key_table`` raised
        AttributeError when routed through the unnamed-constraint signature
        comparison. This exercises the foreign_key_table fallback branch.
        """
        old = _expr(DummyDialect(), [_col("id", IntegerType(), _pk()), _col("uid", IntegerType())])
        new = _expr(
            DummyDialect(), [_col("id", IntegerType(), _pk()), _col("uid", IntegerType())],
            table_constraints=[ForeignKeyConstraint(
                columns=["uid"], foreign_key_table="users", foreign_key_columns=["id"],
            )],
        )
        plan = old.diff(new)
        # unnamed FK constraint added → cannot be dropped by name → rebuild
        assert plan.rebuild is not None
        assert "unnamed" in plan.rebuild.reason

    def test_fk_table_constraint_change_is_detected(self, dialect):
        """The signature must distinguish FK targets — changing the referenced
        table is a real change, not a no-op."""
        fk_a = ForeignKeyConstraint(
            name="fk_uid", columns=["uid"], foreign_key_table="a", foreign_key_columns=["id"],
        )
        fk_b = ForeignKeyConstraint(
            name="fk_uid", columns=["uid"], foreign_key_table="b", foreign_key_columns=["id"],
        )
        old = _expr(dialect, [_col("uid", IntegerType())], table_constraints=[fk_a])
        new = _expr(dialect, [_col("uid", IntegerType())], table_constraints=[fk_b])
        plan = old.diff(new)
        assert plan.rebuild is None  # named constraint → alter path
        assert len(plan.alters[0].actions) == 2  # DropTableConstraint + AddTableConstraint

    def test_unnamed_fk_added_via_bigquery_rebuilds(self, dialect):
        """Unnamed constraint changes rebuild on every backend; pinned here on
        the BigQuery dialect to keep the hook configuration honest."""
        old = _expr(dialect, [_col("id", IntegerType(), _pk()), _col("uid", IntegerType())])
        new = _expr(
            dialect, [_col("id", IntegerType(), _pk()), _col("uid", IntegerType())],
            table_constraints=[ForeignKeyConstraint(
                columns=["uid"], foreign_key_table="users", foreign_key_columns=["id"],
            )],
        )
        plan = old.diff(new)
        assert plan.alters == []
        assert plan.rebuild is not None
        assert "unnamed" in plan.rebuild.reason


# ---------------------------------------------------------------------------
# DiffPlan invariants
# ---------------------------------------------------------------------------

class TestDiffPlanInvariants:

    def test_alters_and_rebuild_mutually_exclusive(self, dialect):
        old = _expr(dialect, [_col("id", IntegerType(), _pk())])
        new = _expr(dialect, [_col("id", IntegerType(), _pk()), _col("x", TextType())])
        plan = old.diff(new)
        assert plan.rebuild is None and plan.alters

        old2 = _expr(dialect, [_col("code", IntegerType())])
        new2 = _expr(dialect, [_col("code", TextType())])
        plan2 = old2.diff(new2)
        assert plan2.rebuild is not None and plan2.alters == []

    def test_plan_rejects_both_fields(self, dialect):
        from rhosocial.activerecord.backend.expression.statements.ddl_alter import (
            AlterTableExpression,
        )
        old = _expr(dialect, [_col("code", IntegerType())])
        new = _expr(dialect, [_col("code", TextType())])
        rp = old.diff(new).rebuild
        assert rp is not None
        alter = AlterTableExpression(dialect, table="t", actions=[])
        with pytest.raises(ValueError, match="mutually exclusive"):
            DiffPlan(alters=[alter], rebuild=rp)

    def test_rebuild_reason_identifies_offending_column(self, dialect):
        """Rebuild reasons name the column that forced the rebuild, so
        callers can diagnose migrations."""
        old = _expr(dialect, [_col("id", IntegerType(), _pk()), _col("code", IntegerType())])
        new = _expr(dialect, [_col("id", IntegerType(), _pk()), _col("code", TextType())])
        rp = old.diff(new).rebuild
        assert "'code'" in rp.reason
