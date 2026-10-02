# tests/rhosocial/activerecord_bigquery_test/feature/backend/dialect/test_expression_fields_match_formatters.py
"""A formatter may not read a field its statement does not carry.

A statement formatter that reads ``expr.schema_name`` needs the expression to
have that attribute. When the formatter was changed to qualify names and the
expression was not given the field, the result is not wrong SQL -- it is an
``AttributeError`` on a statement that can never be built, which is how
SQLServerColumnstoreIndexExpression reached CI.

These were source scans rather than runtime tests. A scan does not work here:
whether the field exists depends on inheritance reaching core, which lives in
another repository, and on **core_kwargs forwarding. Reading the source of this
repository can see neither, so a scan reported defects that were not there --
two were chased down and both were false alarms -- while a field genuinely
removed still passed. Building the statement answers the question the defect
actually asks: does this statement build, and does the schema reach the SQL?
"""
import importlib
import inspect

import pytest

#: Statement fields a formatter may read that some expression classes carry
#: under a different name. Reading these by their own name is the defect.
#: TruncateExpression and the PostgreSQL vacuum/statistics expressions name the
#: field `schema`; the DDL statements name it `schema_name`. No formatter on
#: this backend reads the alias, so nothing here exercises it.
KNOWN_ALIASES = {
    "schema": {"TruncateExpression"},
}


class TestQualifiedStatementsRender:
    """A statement whose formatter qualifies names must build with a schema.

    Checked by building each statement and rendering it, not by scanning
    source. Each case names the statement and how to build it, so adding
    coverage for a newly qualified object type is one entry rather than a new
    mechanism.

    BigQuery writes a dataset as ```app```.`name`, which is the ``schema_name``
    spelled the way BigQuery spells it, and it quotes with backticks.
    """

    @pytest.fixture
    def dialect(self):
        from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect

        return BigQueryDialect()

    def test_create_materialized_view(self, dialect):
        """A class defined in this repository, qualified by a formatter here.

        BigQueryCreateMaterializedViewExpression extends core's
        CreateMaterializedViewExpression and assigns schema_name itself, so a
        scan of this repository could in principle resolve it -- but only until
        core changed, which is the fragile assumption this test drops.
        """
        from rhosocial.activerecord.backend.expression import Column, QueryExpression
        from rhosocial.activerecord.backend.impl.bigquery.expression.materialized_view import (
            BigQueryCreateMaterializedViewExpression,
        )

        query = QueryExpression(dialect, [Column(dialect, "id")], from_="orders")
        expr = BigQueryCreateMaterializedViewExpression(
            dialect, view_name="mv_orders", query=query
        )
        assert expr.to_sql()[0] == (
            "CREATE MATERIALIZED VIEW `mv_orders` AS SELECT `id` FROM `orders`"
        ), expr.to_sql()[0]
        qualified = BigQueryCreateMaterializedViewExpression(
            dialect, view_name="mv_orders", query=query, schema_name="app"
        )
        assert qualified.to_sql()[0] == (
            "CREATE MATERIALIZED VIEW `app`.`mv_orders` AS "
            "SELECT `id` FROM `orders`"
        ), qualified.to_sql()[0]

    def test_drop_materialized_view(self, dialect):
        from rhosocial.activerecord.backend.impl.bigquery.expression.materialized_view import (
            BigQueryDropMaterializedViewExpression,
        )

        expr = BigQueryDropMaterializedViewExpression(dialect, view_name="mv_orders")
        assert expr.to_sql()[0] == "DROP MATERIALIZED VIEW `mv_orders`", expr.to_sql()[0]
        qualified = BigQueryDropMaterializedViewExpression(
            dialect, view_name="mv_orders", schema_name="app"
        )
        assert qualified.to_sql()[0] == (
            "DROP MATERIALIZED VIEW `app`.`mv_orders`"
        ), qualified.to_sql()[0]

    def test_alter_materialized_view_set_options(self, dialect):
        """The formatter is annotated ``expr: Any`` and type-checks nowhere.

        That is precisely the shape a source scan could not attribute to a
        class, so it is one of the two that reached CI this way.
        """
        from rhosocial.activerecord.backend.impl.bigquery.expression.materialized_view import (
            BigQueryAlterMaterializedViewSetOptionsExpression,
        )

        def build(schema_name=None):
            return BigQueryAlterMaterializedViewSetOptionsExpression(
                dialect,
                view_name="mv_orders",
                options={"enable_refresh": True},
                schema_name=schema_name,
            )

        assert build().to_sql()[0] == (
            "ALTER MATERIALIZED VIEW `mv_orders` SET OPTIONS(enable_refresh = true)"
        )
        assert build(schema_name="app").to_sql()[0] == (
            "ALTER MATERIALIZED VIEW `app`.`mv_orders` "
            "SET OPTIONS(enable_refresh = true)"
        )

    def test_create_schema_carries_the_dataset_it_creates(self, dialect):
        """Here the field is the subject, not a qualifier -- and it is required.

        There is no unqualified form to build, so this asserts the narrower
        thing that still matters: the formatter reads the field, the statement
        cannot be built without it, and the name reaches the SQL.
        """
        from rhosocial.activerecord.backend.expression import CreateSchemaExpression

        expr = CreateSchemaExpression(dialect, "app")
        assert expr.to_sql()[0] == "CREATE SCHEMA `app`", expr.to_sql()[0]

    def test_column_is_never_schema_qualified_but_warns(self, dialect):
        """``format_column`` reads the field and then deliberately ignores it.

        BigQuery never schema-qualifies a column, so the qualifier cannot be
        rendered. The dialect warns instead of raising, which is a decision
        worth holding in place: if the field ever goes missing, this fails with
        AttributeError rather than passing.
        """
        from rhosocial.activerecord.backend.expression import Column

        with pytest.warns(UserWarning, match="dropping schema_name='app'"):
            sql, _ = Column(dialect, "id", schema_name="app").to_sql()
        assert sql == "`id`", sql

        # With a table the qualifier still does not reach the SQL, and no
        # warning is raised: a column reference is table-qualified only.
        qualified, _ = Column(
            dialect, "id", table="orders", schema_name="app"
        ).to_sql()
        assert qualified == "`orders`.`id`", qualified


class TestExpressionSignatures:
    """The expressions this backend's formatters qualify must take the field."""

    @pytest.mark.parametrize(
        "import_path,class_name",
        [
            (
                "rhosocial.activerecord.backend.impl.bigquery.expression.materialized_view",
                "BigQueryCreateMaterializedViewExpression",
            ),
            (
                "rhosocial.activerecord.backend.impl.bigquery.expression.materialized_view",
                "BigQueryDropMaterializedViewExpression",
            ),
            (
                "rhosocial.activerecord.backend.impl.bigquery.expression.materialized_view",
                "BigQueryAlterMaterializedViewSetOptionsExpression",
            ),
            (
                "rhosocial.activerecord.backend.expression.statements.ddl_schema",
                "CreateSchemaExpression",
            ),
            (
                "rhosocial.activerecord.backend.expression.core",
                "Column",
            ),
        ],
    )
    def test_qualified_expression_accepts_schema_name(self, import_path, class_name):
        module = importlib.import_module(import_path)
        cls = getattr(module, class_name)
        params = inspect.signature(cls.__init__).parameters
        assert "schema_name" in params, (
            f"{class_name} is read by its formatter, so it needs the field; "
            f"got {list(params)}"
        )

    def test_qualifier_defaults_to_unqualified(self):
        """Where the field qualifies a name, None has to mean unqualified.

        CreateSchemaExpression is exempt on purpose: there the field *is* the
        object, and requiring it is the correct shape.
        """
        from rhosocial.activerecord.backend.expression import Column
        from rhosocial.activerecord.backend.impl.bigquery.expression.materialized_view import (
            BigQueryAlterMaterializedViewSetOptionsExpression,
            BigQueryCreateMaterializedViewExpression,
            BigQueryDropMaterializedViewExpression,
        )

        for cls in (
            BigQueryCreateMaterializedViewExpression,
            BigQueryDropMaterializedViewExpression,
            BigQueryAlterMaterializedViewSetOptionsExpression,
            Column,
        ):
            params = inspect.signature(cls.__init__).parameters
            assert params["schema_name"].default is None, (
                f"{cls.__name__}.schema_name must default to None -- None is "
                f"what means unqualified"
            )
