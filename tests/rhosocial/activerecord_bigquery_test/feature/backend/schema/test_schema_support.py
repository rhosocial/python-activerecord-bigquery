# tests/rhosocial/activerecord_bigquery_test/feature/backend/schema/test_schema_support.py
"""Tests for the namespace capabilities declared on the BigQuery dialect.

BigQuery has two independent namespaces above a table, and this backend is a
dual-support one: the inner slot is the **dataset** and the outer slot is the
**project**. Both are declared, separately, because an engine can have one
without the other -- Oracle has a schema and no catalog at all.
"""
import pytest

from rhosocial.activerecord.backend.dialect.protocols import (
    NamespaceSupport,
)
from rhosocial.activerecord.backend.expression.objects import MaterializedView, Table
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect
from rhosocial.activerecord.backend.impl.bigquery.mixins import BigQueryNamespaceMixin
from rhosocial.activerecord.backend.impl.bigquery.protocols import BigQuerySchemaSupport


class TestSchemaCapability:
    """Umbrella flag and granular schema DDL capability bits."""

    def _dialect(self) -> BigQueryDialect:
        return BigQueryDialect()

    def test_supports_schema_is_true(self):
        assert self._dialect().supports_schema() is True

    def test_implements_namespace_support_protocol(self):
        """The naming side is one protocol, and it covers both levels.

        Catalog qualification and schema qualification are the same question
        asked of two slots, so core answers them with a single
        ``NamespaceSupport`` rather than one protocol per level.
        """
        assert isinstance(self._dialect(), NamespaceSupport)

    def test_implements_bigquery_schema_support_protocol(self):
        assert isinstance(self._dialect(), BigQuerySchemaSupport)

    def test_granular_ddl_flags_currently_true(self):
        """BigQuery supports CREATE/DROP SCHEMA (dataset DDL)."""
        d = self._dialect()
        assert d.supports_create_schema() is True
        assert d.supports_drop_schema() is True


class TestCatalogCapability:
    """BigQuery's outer namespace is a project, and it is rendered."""

    def _dialect(self) -> BigQueryDialect:
        return BigQueryDialect()

    def test_supports_catalog_is_true(self):
        assert self._dialect().supports_catalog() is True

    def test_catalog_qualification_is_true(self):
        """Unlike PostgreSQL's database, a BigQuery project is not implicit."""
        assert self._dialect().supports_catalog_qualification() is True

    def test_schema_qualification_is_true(self):
        """``dataset.table`` is a name BigQuery resolves, so it is rendered."""
        assert self._dialect().supports_schema_qualification() is True

    def test_naming_side_is_owned_by_one_bigquery_mixin(self):
        """The outer level is declared by the backend's one naming-side mixin.

        ``BigQueryCatalogSupport`` used to declare this same switch, and
        duplicated core's ``NamespaceSupport`` member for member while doing it.
        The answer now lives on ``BigQueryNamespaceMixin``, which is where both
        naming levels live -- see
        ``tests/.../protocol/test_protocol_conformance.py`` for why the
        duplicate protocol went.
        """
        assert BigQueryNamespaceMixin in type(self._dialect()).__mro__

    def test_project_reaches_the_sql(self):
        sql, _ = Table(
            self._dialect(), "orders", schema_name="app", catalog_name="myproject"
        ).to_sql()
        assert sql == "`myproject`.`app`.`orders`"

    def test_project_without_dataset_is_refused_while_rendering(self):
        """``project.table`` is not a BigQuery path, so this cannot render."""
        dialect = self._dialect()
        with pytest.raises(ValueError, match="project only together with a dataset"):
            Table(dialect, "orders", catalog_name="myproject").to_sql()


class TestBothNamespacesAreIndependent:
    """Neither protocol implies the other; both are declared here."""

    def test_a_dataset_alone_renders(self):
        sql, _ = Table(
            BigQueryDialect(), "orders", schema_name="app"
        ).to_sql()
        assert sql == "`app`.`orders`"

    def test_a_name_alone_renders(self):
        sql, _ = Table(BigQueryDialect(), "orders").to_sql()
        assert sql == "`orders`"

    def test_every_materialized_view_statement_uses_the_slots(self):
        """The one object model this backend has, qualified by both slots.

        A dataset reaches the SQL, and a project reaches the SQL: neither slot is
        silently dropped on the way through.
        """
        from rhosocial.activerecord.backend.impl.bigquery.expression import (
            BigQueryDropMaterializedViewExpression,
        )

        dialect = BigQueryDialect()
        assert BigQueryDropMaterializedViewExpression(
            dialect, MaterializedView(dialect, "mv", schema_name="app")
        ).to_sql()[0] == "DROP MATERIALIZED VIEW `app`.`mv`"
        assert BigQueryDropMaterializedViewExpression(
            dialect,
            MaterializedView(dialect, "mv", schema_name="app", catalog_name="myproject"),
        ).to_sql()[0] == "DROP MATERIALIZED VIEW `myproject`.`app`.`mv`"


class TestObjectNamingIsTheOnlyPath:
    """Every schema object becomes SQL here, and nowhere else."""

    def test_table_object_formatter_is_present(self):
        dialect = BigQueryDialect()
        assert hasattr(dialect, "format_table_object")
        assert hasattr(dialect, "format_materialized_view_object")
        assert hasattr(dialect, "format_schema_object")

    def test_named_relation_reference_renders_through_the_same_path(self):
        """A ``FROM`` reference and a DDL target share one renderer.

        ``NamedRelationRef`` carries the alias and asks the relation for its
        name; the relation renders itself through ``format_table_object``, the
        same call the materialized view statements reach through their own
        ``format_materialized_view_object``. There is no second implementation
        of "how a BigQuery name is spelled".
        """
        from rhosocial.activerecord.backend.expression.sources import NamedRelationRef

        dialect = BigQueryDialect()
        ref = NamedRelationRef(
            dialect, Table(dialect, "orders", schema_name="app"), alias="o"
        )
        assert dialect.format_named_relation(ref)[0] == "`app`.`orders` AS `o`"

    def test_a_name_carrying_a_slot_the_dialect_cannot_render_is_refused(self):
        """The renderer refuses rather than drops.

        BigQuery declares both namespaces, so the slot is rendered. The point of
        the assertion is the mechanism: an object with an empty name never gets
        that far, and one with both slots takes exactly the path that renders
        both -- there is no code path that receives a populated slot and returns
        a bare name.
        """
        dialect = BigQueryDialect()
        with pytest.raises(ValueError, match="non-empty string"):
            Table(dialect, "  ", schema_name="app", catalog_name="myproject")
        with pytest.raises(ValueError, match="schema_name"):
            Table(dialect, "orders", schema_name="", catalog_name="myproject")
