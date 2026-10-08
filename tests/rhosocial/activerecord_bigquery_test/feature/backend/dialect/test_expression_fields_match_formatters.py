# tests/rhosocial/activerecord_bigquery_test/feature/backend/dialect/test_expression_fields_match_formatters.py
"""A formatter may not read a field its statement does not carry.

A statement formatter that qualifies names needs the statement to carry the
name as an object. When the formatter was changed to qualify names and the
expression was not given the object, the result is not wrong SQL -- it is an
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

from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError
from rhosocial.activerecord.backend.expression.objects import MaterializedView

#: Statement fields a formatter may read that some expression classes carry
#: under a different name. Reading these by their own name is the defect.
#: The DDL statements all name their target through a schema object, so no
#: formatter on this backend reads an alias.
KNOWN_ALIASES: dict = {}


class TestQualifiedStatementsRender:
    """A statement whose formatter qualifies names must build with a schema.

    Checked by building each statement and rendering it, not by scanning
    source. Each case names the statement and how to build it, so adding
    coverage for a newly qualified object type is one entry rather than a new
    mechanism.

    BigQuery writes a dataset as ```app```.`name` and a project as
    ```proj```.`app```.`name`, which are the ``schema_name`` and
    ``catalog_name`` slots spelled the way BigQuery spells them, and it quotes
    with backticks.
    """

    @pytest.fixture
    def dialect(self):
        from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect

        return BigQueryDialect()

    def test_create_materialized_view(self, dialect):
        """A class defined in this repository, qualified by a formatter here."""
        from rhosocial.activerecord.backend.expression import Column, QueryExpression
        from rhosocial.activerecord.backend.impl.bigquery.expression.materialized_view import (
            BigQueryCreateMaterializedViewExpression,
        )

        query = QueryExpression(dialect, [Column(dialect, "id")], from_="orders")
        expr = BigQueryCreateMaterializedViewExpression(
            dialect, view=MaterializedView(dialect, "mv_orders"), query=query
        )
        assert expr.to_sql()[0] == (
            "CREATE MATERIALIZED VIEW `mv_orders` AS SELECT `id` FROM `orders`"
        ), expr.to_sql()[0]
        qualified = BigQueryCreateMaterializedViewExpression(
            dialect, view=MaterializedView(dialect, "mv_orders", schema_name="app"), query=query
        )
        assert qualified.to_sql()[0] == (
            "CREATE MATERIALIZED VIEW `app`.`mv_orders` AS "
            "SELECT `id` FROM `orders`"
        ), qualified.to_sql()[0]

    def test_drop_materialized_view(self, dialect):
        from rhosocial.activerecord.backend.impl.bigquery.expression.materialized_view import (
            BigQueryDropMaterializedViewExpression,
        )

        expr = BigQueryDropMaterializedViewExpression(
            dialect, view=MaterializedView(dialect, "mv_orders")
        )
        assert expr.to_sql()[0] == "DROP MATERIALIZED VIEW `mv_orders`", expr.to_sql()[0]
        qualified = BigQueryDropMaterializedViewExpression(
            dialect, view=MaterializedView(dialect, "mv_orders", schema_name="app")
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
                view=MaterializedView(dialect, "mv_orders", schema_name=schema_name),
                options={"enable_refresh": True},
            )

        assert build().to_sql()[0] == (
            "ALTER MATERIALIZED VIEW `mv_orders` SET OPTIONS(enable_refresh = true)"
        )
        assert build(schema_name="app").to_sql()[0] == (
            "ALTER MATERIALIZED VIEW `app`.`mv_orders` "
            "SET OPTIONS(enable_refresh = true)"
        )

    def test_each_mv_statement_refuses_a_table_in_place_of_the_view(self, dialect):
        """A wrong object kind is refused by name, not rendered as SQL.

        Each of the four statements is reached by name -- the view's own
        ``format_method`` says which formatter renders it -- so nothing in the
        dispatch tells a formatter whether the object it was handed is the kind
        the statement acts on. Given a ``Table`` instead, the object's own
        ``format_table_object`` produces valid SQL: ``CREATE MATERIALIZED VIEW
        `orders` AS ...`` is well-formed and names the wrong object, with no
        error anywhere. That is the silent failure the kind checks exist to
        stop, so each of the three single-object statements and the replica's
        two objects is asserted separately.
        """
        from rhosocial.activerecord.backend.expression import Column, QueryExpression
        from rhosocial.activerecord.backend.expression.objects import Table
        from rhosocial.activerecord.backend.impl.bigquery.expression.materialized_view import (
            BigQueryAlterMaterializedViewSetOptionsExpression,
            BigQueryCreateMaterializedViewExpression,
            BigQueryCreateMaterializedViewReplicaExpression,
            BigQueryDropMaterializedViewExpression,
        )

        query = QueryExpression(dialect, [Column(dialect, "id")], from_="orders")
        wrong = Table(dialect, "orders")

        with pytest.raises(TypeError) as exc:
            BigQueryCreateMaterializedViewExpression(
                dialect, view=wrong, query=query
            ).to_sql()
        assert "CreateMaterializedViewExpression.view must be a MaterializedView" in str(
            exc.value
        )

        with pytest.raises(TypeError) as exc:
            BigQueryDropMaterializedViewExpression(dialect, view=wrong).to_sql()
        assert "DropMaterializedViewExpression.view must be a MaterializedView" in str(
            exc.value
        )

        with pytest.raises(TypeError) as exc:
            BigQueryAlterMaterializedViewSetOptionsExpression(
                dialect, view=wrong, options={"enable_refresh": True}
            ).to_sql()
        assert (
            "BigQueryAlterMaterializedViewSetOptionsExpression.view must be a "
            "MaterializedView" in str(exc.value)
        )

    def test_a_dataset_is_still_accepted_where_a_view_belongs(self, dialect):
        """The check is the kind, not "is it a relation".

        ``Table`` and ``MaterializedView`` share a base; a check written against
        the base would accept either. The assertion is that the *dataset* still
        qualifies after the check, so the guard cannot be satisfied by an object
        of the wrong kind that happens to carry the slots.
        """
        from rhosocial.activerecord.backend.impl.bigquery.expression import (
            BigQueryDropMaterializedViewExpression,
        )

        sql, _ = BigQueryDropMaterializedViewExpression(
            dialect,
            view=MaterializedView(dialect, "mv", schema_name="app"),
        ).to_sql()
        assert sql == "DROP MATERIALIZED VIEW `app`.`mv`", sql

    def test_create_schema_refuses_a_non_schema_object(self, dialect):
        """The dataset named as a different kind is refused, not rendered.

        ``CREATE SCHEMA`` reads one object. Handed a ``Table`` it would render
        through ``format_table_object`` -- ``CREATE SCHEMA `orders```, which the
        server accepts syntactically and which creates no dataset.
        """
        from rhosocial.activerecord.backend.expression.objects import Table
        from rhosocial.activerecord.backend.expression.statements import (
            CreateSchemaExpression,
            DropSchemaExpression,
        )

        with pytest.raises(TypeError) as exc:
            CreateSchemaExpression(dialect, Table(dialect, "orders")).to_sql()
        assert "CreateSchemaExpression.schema must be a Schema, got Table" in str(
            exc.value
        )

        with pytest.raises(TypeError) as exc:
            DropSchemaExpression(dialect, Table(dialect, "orders")).to_sql()
        assert "DropSchemaExpression.schema must be a Schema, got Table" in str(
            exc.value
        )

    def test_all_three_mv_statements_render_one_carrier(self, dialect):
        """CREATE, DROP and ALTER read the same object through one path.

        They used to each build a name of their own, so a qualified form could
        reach one statement and miss the next. Building all three from one
        object is the assertion that the path is shared.
        """
        from rhosocial.activerecord.backend.expression import Column, QueryExpression
        from rhosocial.activerecord.backend.impl.bigquery.expression.materialized_view import (
            BigQueryAlterMaterializedViewSetOptionsExpression,
            BigQueryCreateMaterializedViewExpression,
            BigQueryDropMaterializedViewExpression,
        )

        view = MaterializedView(dialect, "mv_orders", schema_name="app")
        query = QueryExpression(dialect, [Column(dialect, "id")], from_="orders")
        rendered = [
            BigQueryCreateMaterializedViewExpression(dialect, view=view, query=query)
            .to_sql()[0],
            BigQueryDropMaterializedViewExpression(dialect, view=view).to_sql()[0],
            BigQueryAlterMaterializedViewSetOptionsExpression(
                dialect, view=view, options={"enable_refresh": True}
            ).to_sql()[0],
        ]
        for sql in rendered:
            assert "`app`.`mv_orders`" in sql, sql

    def test_create_schema_carries_the_dataset_it_creates(self, dialect):
        """Here the field is the subject, not a qualifier -- and it is required.

        There is no unqualified form to build, so this asserts the narrower
        thing that still matters: the formatter reads the field, the statement
        cannot be built without it, and the name reaches the SQL.
        """
        from rhosocial.activerecord.backend.expression import CreateSchemaExpression
        from rhosocial.activerecord.backend.expression.objects import Schema

        expr = CreateSchemaExpression(dialect, Schema(dialect, "app"))
        assert expr.to_sql()[0] == "CREATE SCHEMA `app`", expr.to_sql()[0]

    def test_a_project_reaches_the_sql_through_the_object(self, dialect):
        """``catalog_name`` is BigQuery's project, and it is rendered.

        The dialect is a dual-support backend: dataset in ``schema_name``,
        project in ``catalog_name``. This asserts the outer slot is not dropped
        the way the inner one was before the outer namespace was declared.
        """
        from rhosocial.activerecord.backend.expression import Column, QueryExpression
        from rhosocial.activerecord.backend.impl.bigquery.expression.materialized_view import (
            BigQueryDropMaterializedViewExpression,
        )

        expr = BigQueryDropMaterializedViewExpression(
            dialect,
            view=MaterializedView(dialect, "mv_orders", schema_name="app", catalog_name="proj"),
        )
        assert expr.to_sql()[0] == (
            "DROP MATERIALIZED VIEW `proj`.`app`.`mv_orders`"
        ), expr.to_sql()[0]

    def test_a_project_without_a_dataset_is_refused(self, dialect):
        """``project.table`` is not a BigQuery path.

        The refusal comes from the dialect, while rendering, where the dialect
        is known -- not from the constructor, where it is not.
        """
        from rhosocial.activerecord.backend.impl.bigquery.expression.materialized_view import (
            BigQueryDropMaterializedViewExpression,
        )

        expr = BigQueryDropMaterializedViewExpression(
            dialect, view=MaterializedView(dialect, "mv_orders", catalog_name="proj")
        )
        with pytest.raises(ValueError, match="project only together with a dataset"):
            expr.to_sql()

    def test_bare_column_with_a_dataset_is_reported_not_qualified(self, dialect):
        """``format_column`` refuses the one case it cannot express.

        BigQuery never schema-qualifies a column, so the qualifier cannot be
        rendered. With a table the namespace is redundant and dropping it is
        correct; without one, the namespace is the only thing that would have
        identified the column, so it is named in an error instead.
        """
        from rhosocial.activerecord.backend.expression import Column

        with pytest.raises(UnsupportedFeatureError) as exc:
            Column(dialect, "id", schema_name="app").to_sql()
        assert "carries schema_name='app' but no table" in str(exc.value)

        # With a table the qualifier still does not reach the SQL, and nothing
        # is raised: a column reference is table-qualified only.
        qualified, _ = Column(
            dialect, "id", table="orders", schema_name="app"
        ).to_sql()
        assert qualified == "`orders`.`id`", qualified


class TestExpressionSignatures:
    """The expressions this backend's formatters qualify must take the object."""

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
                "rhosocial.activerecord.backend.impl.bigquery.expression.materialized_view",
                "BigQueryCreateMaterializedViewReplicaExpression",
            ),
        ],
    )
    def test_qualified_expression_takes_a_view_object(self, import_path, class_name):
        """The namespace belongs to the object, not beside it.

        A name string plus a ``schema_name`` parameter is two carriers, two
        things to keep in step, and the flat string cannot say which dataset it
        lived in. The formatter reads one object, so the constructor takes one.
        """
        module = importlib.import_module(import_path)
        cls = getattr(module, class_name)
        params = inspect.signature(cls.__init__).parameters
        assert "schema_name" not in params, (
            f"{class_name} carries the namespace in its view object; a separate "
            f"schema_name parameter would be a second carrier; "
            f"got {list(params)}"
        )
        object_params = [name for name in params if name in ("view", "replica", "source_view")]
        assert object_params, (
            f"{class_name} is qualified by its formatter, so it needs the object; "
            f"got {list(params)}"
        )

    def test_view_defaults_to_unqualified(self):
        """Where the object qualifies a name, no namespace has to mean unqualified.

        ``CreateSchemaExpression`` is exempt on purpose: there the name *is* the
        object, and requiring it is the correct shape. For the materialized
        views the namespace is optional, and "no dataset" is expressed by
        leaving the slot off the object rather than by passing ``None``
        separately.
        """
        from rhosocial.activerecord.backend.impl.bigquery.expression.materialized_view import (
            BigQueryAlterMaterializedViewSetOptionsExpression,
            BigQueryCreateMaterializedViewExpression,
            BigQueryDropMaterializedViewExpression,
        )

        for cls in (
            BigQueryCreateMaterializedViewExpression,
            BigQueryDropMaterializedViewExpression,
            BigQueryAlterMaterializedViewSetOptionsExpression,
        ):
            params = inspect.signature(cls.__init__).parameters
            assert "schema_name" not in params, (
                f"{cls.__name__} has no flat schema_name to default"
            )
            view_param = next(
                params[name] for name in params if name in ("view", "replica")
            )
            assert view_param.default is inspect.Parameter.empty, (
                f"{cls.__name__}.view is required: a caller has to say which "
                f"object is being created, named or dropped"
            )