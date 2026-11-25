# tests/rhosocial/activerecord_bigquery_test/feature/backend/ddl/test_drop_table_constraint_address.py
"""BigQuery addresses DROP CONSTRAINT by name, never by declaration kind.

Core's ``DropTableConstraintAction`` now carries either a ``constraint_name`` or
a ``constraint`` declaration (and either may be absent).  This backend overrides
neither the action nor the formatter: ``format_drop_table_constraint_action``
resolves through core's ``DDLColumnMixin`` to the name-only implementation, which
refuses a declaration-only action with ``UnsupportedFeatureError`` naming
``DROP CONSTRAINT by kind`` before anything renders.

That guard rests on this backend's own ``supports_drop_constraint_by_kind()``,
declared ``False`` in ``mixins/constraint.py``.  The tests below pin the
refusal -- so a hostile or merely moved core default cannot silently turn it
into a render or an empty string -- and pin the name-only spelling byte for
byte so the accepted path cannot drift while the refusal is being watched.

These are construction and rendering tests: no instance is required.
"""

import pytest

from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError
from rhosocial.activerecord.backend.expression import AlterTableStatement
from rhosocial.activerecord.backend.expression.objects import Table
from rhosocial.activerecord.backend.expression.statements.ddl_alter import (
    DropTableConstraintAction,
)
from rhosocial.activerecord.backend.expression.statements.ddl_table import (
    TableConstraint,
    TableForeignKeyConstraint,
    TablePrimaryKeyConstraint,
)
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect


@pytest.fixture
def dialect():
    return BigQueryDialect()


def _foreign_key(dialect):
    """A named, real foreign key: BigQuery's only nameable constraint kind."""
    return TableConstraint(
        dialect,
        branch=TableForeignKeyConstraint(
            dialect, ["a"], (Table(dialect, "parent"), ["id"])
        ),
        name="fk",
        not_enforced=True,
    )


def _alter_table(dialect, action):
    return AlterTableStatement(dialect, table=Table(dialect, "t"), actions=[action])


class TestDropConstraintByKindIsRefused:
    """A declaration-only drop is refused by name; nothing is rendered."""

    def test_the_probe_is_false(self, dialect):
        """The refusal's hinge: BigQuery spells no ``DROP <kind>`` production.

        See ``BigQueryConstraintMixin.supports_drop_constraint_by_kind`` for the
        grammar that decided it.
        """
        assert dialect.supports_drop_constraint_by_kind() is False

    def test_a_declaration_only_drop_is_refused_by_kind(self, dialect):
        """The error names the missing feature, not the missing name."""
        action = DropTableConstraintAction(dialect, constraint=_foreign_key(dialect))

        with pytest.raises(UnsupportedFeatureError) as exc:
            _alter_table(dialect, action).to_sql()

        assert exc.value.feature_name == "DROP CONSTRAINT by kind"
        assert "address the constraint by name instead" in str(exc.value)

    def test_the_action_itself_refuses_before_the_statement_can_join_it(self, dialect):
        """Refused at the action, so no action-list spelling can sneak past."""
        action = DropTableConstraintAction(dialect, constraint=_foreign_key(dialect))

        with pytest.raises(UnsupportedFeatureError) as exc:
            action.to_sql()

        assert exc.value.feature_name == "DROP CONSTRAINT by kind"

    def test_a_primary_key_declaration_is_refused_the_same_way(self, dialect):
        """BigQuery creates primary keys but cannot drop one -- by any address.

        A primary key has no name on BigQuery, and the ALTER side has no kind
        spelling, so a declaration is not an alternative route to the same
        statement: it is a different, unavailable statement.
        """
        branch = TablePrimaryKeyConstraint(dialect, ["a"])
        action = DropTableConstraintAction(
            dialect, constraint=TableConstraint(dialect, branch=branch, name="pk")
        )

        with pytest.raises(UnsupportedFeatureError) as exc:
            action.to_sql()

        assert exc.value.feature_name == "DROP CONSTRAINT by kind"

    def test_an_action_with_no_address_at_all_is_refused(self, dialect):
        """Neither form: a ValueError, because the action names nothing to drop."""
        with pytest.raises(ValueError, match="requires constraint_name or constraint"):
            DropTableConstraintAction(dialect).to_sql()


class TestDropConstraintByNameIsUnchanged:
    """The accepted route keeps its exact spelling, including ``IF EXISTS``."""

    def test_name_only_renders(self, dialect):
        action = DropTableConstraintAction(dialect, "fk")

        sql, params = _alter_table(dialect, action).to_sql()

        assert sql == "ALTER TABLE `t` DROP CONSTRAINT `fk`"
        assert params == ()

    def test_name_only_with_if_exists_renders(self, dialect):
        action = DropTableConstraintAction(dialect, "fk", if_exists=True)

        sql, params = _alter_table(dialect, action).to_sql()

        assert sql == "ALTER TABLE `t` DROP CONSTRAINT IF EXISTS `fk`"
        assert params == ()

    def test_the_name_wins_when_both_addresses_are_present(self, dialect):
        """Core's rule on a name-only dialect: the name is what it can render.

        The declaration is ignored rather than refused, because the action is
        still addressable -- and the rendered statement is byte-identical to the
        name-only one above.
        """
        action = DropTableConstraintAction(
            dialect, "fk", constraint=_foreign_key(dialect)
        )

        sql, params = _alter_table(dialect, action).to_sql()

        assert sql == "ALTER TABLE `t` DROP CONSTRAINT `fk`"
        assert params == ()
