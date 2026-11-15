# tests/rhosocial/activerecord_bigquery_test/feature/backend/dialect/test_bigquery_dataset_qualification.py
"""Dataset qualification and the two constraints BigQuery cannot spell.

The shared testsuite builds ``Table(dialect, "users")`` with no dataset.  A
BigQuery client resolves a bare name only when a default dataset is bound to
the job -- and the goccy emulator does not keep that binding per request.
The backend therefore hands its configured dataset to the dialect, which
renders unqualified relations as ``dataset.table``.  These tests pin that
render, plus the two table clauses of the shared ``order_items`` fixture:
``DEFAULT`` is rendered (GoogleSQL has it) and ``UNIQUE`` is dropped (it has
no production at all).
"""
from rhosocial.activerecord.backend.expression.objects import (
    Schema,
    Table,
)
from rhosocial.activerecord.backend.expression.statements import (
    ColumnConstraint,
    ColumnDefaultConstraint,
    ColumnDefinition,
    CreateTableStatement,
    TableConstraint,
    TableUniqueConstraint,
)
from rhosocial.activerecord.backend.expression.types import IntegerType
from rhosocial.activerecord.backend.impl.bigquery.backend import BigQueryBackend
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect
from rhosocial.activerecord.testsuite.feature.query.fixtures.definitions import (
    OrderItemsDefinition,
    UsersDefinition,
)


DATASET = "test_query_basic"


def _dialect() -> BigQueryDialect:
    return BigQueryDialect(version=(3, 0, 0), default_dataset=DATASET)


class TestRelationQualification:
    """An unqualified relation takes the dialect's default dataset."""

    def test_table_renders_dataset_qualified(self):
        sql, _ = Table(_dialect(), "users").to_sql()
        assert sql == "`test_query_basic`.`users`", sql

    def test_explicit_schema_wins_over_default(self):
        sql, _ = Table(_dialect(), "users", schema_name="other_dataset").to_sql()
        assert sql == "`other_dataset`.`users`", sql

    def test_no_default_dataset_keeps_bare_name(self):
        sql, _ = Table(BigQueryDialect(version=(3, 0, 0)), "users").to_sql()
        assert sql == "`users`", sql

    def test_schema_object_is_not_prefixed_with_the_dataset(self):
        sql, _ = Schema(_dialect(), DATASET).to_sql()
        assert sql == "`test_query_basic`", sql

    def test_backend_hands_its_dataset_to_the_dialect(self):
        backend = BigQueryBackend(project="test", dataset=DATASET)
        assert backend.dialect.default_dataset == DATASET

    def test_project_level_backend_has_no_default_dataset(self):
        backend = BigQueryBackend(project="test")
        assert backend.dialect.default_dataset is None


class TestSharedQueryFixtureDdl:
    """The exact DDL the shared ``query/basic`` fixture renders on BigQuery.

    The definitions are the L1 classes of the shared query topic; only a
    dialect is handed to them, so this test stays a pure render check.
    """

    USERS_DDL = (
        "CREATE TABLE `test_query_basic`.`users` ("
        "`id` INT64 PRIMARY KEY, `username` STRING(255), "
        "`email` STRING(255), `age` INT64, `balance` FLOAT64, "
        "`is_active` BOOL, `created_at` TIMESTAMP, "
        "`updated_at` TIMESTAMP)"
    )

    ORDER_ITEMS_DDL = (
        "CREATE TABLE `test_query_basic`.`order_items` ("
        "`id` INT64 PRIMARY KEY, `order_id` INT64, `product_id` INT64, "
        "`product_name` STRING(255) DEFAULT '-' NOT NULL, `quantity` INT64, "
        "`unit_price` NUMERIC(12, 4), `subtotal` NUMERIC(12, 4), "
        "`created_at` TIMESTAMP, `updated_at` TIMESTAMP)"
    )

    def test_users_table(self):
        sql, params = UsersDefinition(_dialect()).create_table.to_sql()
        assert sql == self.USERS_DDL, sql
        assert params == ()

    def test_order_items_keeps_default_and_drops_unique(self):
        sql, params = OrderItemsDefinition(_dialect()).create_table.to_sql()
        assert sql == self.ORDER_ITEMS_DDL, sql
        assert params == ()
        assert "DEFAULT '-'" in sql
        assert "UNIQUE" not in sql
        # The AUTO_INCREMENT marker is inert: the key column is plain INT64
        # and ids are generated client-side by the backend's insert path.
        assert "AUTO_INCREMENT" not in sql


class TestUnenforceableUniqueConstraint:
    """Table UNIQUE renders nothing; the core renderer skips an empty clause."""

    def test_unique_table_constraint_renders_empty(self):
        dialect = _dialect()
        constraint = TableConstraint(
            dialect, branch=TableUniqueConstraint(dialect, ["a", "b"])
        )
        sql, params = dialect.format_table_constraint(constraint)
        assert sql == ""
        assert params == ()

    def test_create_table_omits_the_unique_clause_entirely(self):
        dialect = _dialect()
        statement = CreateTableStatement(
            dialect,
            table=Table(dialect, "unique_probe"),
            columns=[
                ColumnDefinition(dialect, "a", IntegerType(dialect)),
                ColumnDefinition(
                    dialect,
                    "b",
                    IntegerType(dialect),
                    constraints=[
                        ColumnConstraint(
                            dialect, branch=ColumnDefaultConstraint(dialect, 0)
                        ),
                    ],
                ),
            ],
            table_constraints=[
                TableConstraint(
                    dialect, branch=TableUniqueConstraint(dialect, ["a", "b"])
                )
            ],
        )
        sql, _ = statement.to_sql()
        assert "UNIQUE" not in sql
        assert "DEFAULT 0" in sql
        assert "`test_query_basic`.`unique_probe`" in sql
