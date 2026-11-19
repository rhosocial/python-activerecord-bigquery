# tests/rhosocial/activerecord_bigquery_test/feature/query/relation/legacy/conftest.py
"""L2 environment for the merged ``query/relations`` bridge tests.

This is the sqlite bridge's local environment for ``test_with_integration.py``
(the real-database ``with_()`` integration tests carried over from the old
``query/relations`` directory).  It is deliberately self-contained: the DDL
definitions are inlined so this directory does not import any model module from
the (concurrently restructured) query topic.

Each table definition receives only a dialect and produces ``to_sql()`` DDL;
the ``schema`` fixture drops and recreates all tables before every test so
sequence/identity state is reset.
"""

from pathlib import Path

import pytest

from rhosocial.activerecord.backend.expression import ColumnConstraint as Constraint
from rhosocial.activerecord.backend.expression import ColumnDefinition as Column
from rhosocial.activerecord.backend.expression import CreateTableStatement as CreateTable
from rhosocial.activerecord.backend.expression import DropTableStatement as DropTable
from rhosocial.activerecord.backend.expression import TableConstraint
from rhosocial.activerecord.backend.expression.objects import Table
from rhosocial.activerecord.backend.expression.statements import (
    ColumnDefaultConstraint as Default,
)
from rhosocial.activerecord.backend.expression.statements import (
    ColumnNotNullConstraint as NotNull,
)
from rhosocial.activerecord.backend.expression.statements import (
    ColumnPrimaryKeyConstraint as PrimaryKey,
)
from rhosocial.activerecord.backend.expression.statements import TableUniqueConstraint as TableUnique
from rhosocial.activerecord.backend.expression.statements import auto_increment_parts
from rhosocial.activerecord.backend.expression.types import BooleanType as Bool
from rhosocial.activerecord.backend.expression.types import DecimalType as Numeric
from rhosocial.activerecord.backend.expression.types import FloatType as Float
from rhosocial.activerecord.backend.expression.types import IntegerType as Int
from rhosocial.activerecord.backend.expression.types import TextType, TimestampType
from rhosocial.activerecord.backend.expression.types import VarCharType as VarChar
from rhosocial.activerecord.backend.options import ExecutionOptions
from rhosocial.activerecord.backend.schema import StatementType
from rhosocial.activerecord.testsuite.pytest_plugin import Declaration

DECLARATION = Declaration(
    uses_database=True,
    parallel=True,
    purpose="Directory-owned database for query/relation/legacy bridge tests.",
    passes_means="the directory's tests run on one worker per scenario",
    fails_means="two workers share the same database file",
)

DDL = ExecutionOptions(stmt_type=StatementType.DDL)

PLACEHOLDER_TEXT = "-"


def _require_data_type(dialect, concept):
    probe = getattr(dialect, "supports_data_types", None)
    if not callable(probe):
        return
    supported = probe() or {}
    if concept not in supported:
        import pytest as _pytest

        _pytest.skip(f"dialect does not support data type {concept!r}")


def _short_text(dialect):
    _require_data_type(dialect, "varchar")
    return VarChar(dialect, 255)


def _long_text(dialect):
    return TextType(dialect)


def _timestamp(dialect):
    probe = getattr(dialect, "supports_microsecond_timestamp", None)
    keeps = bool(probe()) if callable(probe) else bool(probe)
    return TimestampType(dialect, precision=6 if keeps else None)


def _supports_drop_if_exists(dialect):
    probe = getattr(dialect, "supports_if_exists_table", None)
    return True if probe is None else bool(probe())


class Definition:
    """Minimal DDL-only table definition (no model imports)."""

    table_name = ""

    def __init__(self, dialect, table_name=None):
        self.dialect = dialect
        self.name = table_name or type(self).table_name
        self.create_table = CreateTable(
            dialect,
            table=Table(dialect, self.name),
            columns=self.columns(),
            table_constraints=self.table_constraints(),
        )
        self.drop_table = DropTable(
            dialect,
            table=Table(dialect, self.name),
            if_exists=_supports_drop_if_exists(dialect),
        )

    def columns(self):
        raise NotImplementedError

    def table_constraints(self):
        return []

    def column(self, name, sql_type, constraints=None):
        return Column(self.dialect, name, sql_type, constraints=constraints or [])

    def auto_pk(self, name="id"):
        data_type, attributes = auto_increment_parts(self.dialect, Int(self.dialect))
        return Column(
            self.dialect,
            name,
            data_type,
            constraints=[Constraint(self.dialect, branch=PrimaryKey(self.dialect))],
            attributes=attributes,
        )

    def text(self, name):
        return self.column(name, _short_text(self.dialect))

    def longtext(self, name):
        return self.column(name, _long_text(self.dialect))

    def timestamp(self, name):
        return self.column(name, _timestamp(self.dialect))

    def required_text(self, name):
        return self.column(
            name,
            VarChar(self.dialect, 255),
            [
                Constraint(self.dialect, branch=Default(self.dialect, PLACEHOLDER_TEXT)),
                Constraint(self.dialect, branch=NotNull(self.dialect)),
            ],
        )


class UsersDefinition(Definition):
    table_name = "users"

    def columns(self):
        return [
            self.auto_pk(),
            self.text("username"),
            self.text("email"),
            self.column("age", Int(self.dialect)),
            self.column("balance", Float(self.dialect)),
            self.column("is_active", Bool(self.dialect)),
            self.timestamp("created_at"),
            self.timestamp("updated_at"),
        ]


class PostsDefinition(Definition):
    table_name = "posts"

    def columns(self):
        return [
            self.auto_pk(),
            self.column("user_id", Int(self.dialect)),
            self.text("title"),
            self.longtext("content"),
            self.text("status"),
            self.timestamp("created_at"),
            self.timestamp("updated_at"),
        ]


class CommentsDefinition(Definition):
    table_name = "comments"

    def columns(self):
        return [
            self.auto_pk(),
            self.column("user_id", Int(self.dialect)),
            self.column("post_id", Int(self.dialect)),
            self.longtext("content"),
            self.column("is_hidden", Bool(self.dialect)),
            self.timestamp("created_at"),
            self.timestamp("updated_at"),
        ]


class OrdersDefinition(Definition):
    table_name = "orders"

    def columns(self):
        return [
            self.auto_pk(),
            self.column("user_id", Int(self.dialect)),
            self.text("order_number"),
            self.column("total_amount", Numeric(self.dialect, 12, 4)),
            self.text("status"),
            self.timestamp("created_at"),
            self.timestamp("updated_at"),
        ]


class OrderItemsDefinition(Definition):
    table_name = "order_items"

    def columns(self):
        return [
            self.auto_pk(),
            self.column("order_id", Int(self.dialect)),
            self.column("product_id", Int(self.dialect)),
            self.required_text("product_name"),
            self.column("quantity", Int(self.dialect)),
            self.column("unit_price", Numeric(self.dialect, 12, 4)),
            self.column("subtotal", Numeric(self.dialect, 12, 4)),
            self.timestamp("created_at"),
            self.timestamp("updated_at"),
        ]

    def table_constraints(self):
        return [
            TableConstraint(
                self.dialect,
                branch=TableUnique(
                    self.dialect,
                    ["order_id", "product_id", "product_name"],
                ),
            )
        ]


DEFINITIONS = (
    UsersDefinition,
    PostsDefinition,
    CommentsDefinition,
    OrdersDefinition,
    OrderItemsDefinition,
)


def _database_name() -> str:
    """Database name from this conftest's namespace (below ``feature``)."""
    parts = Path(__file__).parent.parts
    start = parts.index("feature") + 1
    return "test_" + "_".join(parts[start:])


@pytest.fixture(scope="session")
def database_config(backend_scenario):
    """The scenario, its connection configuration, and the directory database name."""
    name = _database_name()
    return backend_scenario, backend_scenario.make_config(name), name


@pytest.fixture(scope="session")
def database(database_config):
    """The directory's database, prepared once and left for later files."""
    scenario, config, name = database_config
    scenario.reset_database(name)
    backend = scenario.backend_class(connection_config=config)
    backend.connect()
    backend.introspect_and_adapt()
    yield backend
    backend.disconnect()


@pytest.fixture(scope="function", autouse=True)
def schema(database):
    """Drop and recreate the tables this directory uses, before every test."""
    fixtures = [definition(database.dialect) for definition in DEFINITIONS]
    for fixture in fixtures:
        database.execute(*fixture.create_table.to_sql(), options=DDL)
    yield
    for fixture in reversed(fixtures):
        database.execute(*fixture.drop_table.to_sql(), options=DDL)
