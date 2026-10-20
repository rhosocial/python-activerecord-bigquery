# tests/rhosocial/activerecord_bigquery_test/feature/backend/dialect/test_bigquery_kind_identity.py
"""Kind, class name and formatting entry are three spellings of one identity.

§3 derives the kind from the class name and names the formatting entry
``format_`` + kind. Nothing in the framework compares the three, so nothing
detects a node whose entry is called something else -- and the reader of an
artifact has to know which entry a kind dispatches to, which is exactly the
answer that goes missing.

These cases pin all three sources for every node this backend defines, and the
arrangement that lets a backend entry win: an override placed after the class
it overrides never wins the lookup (§11.1), so each one must resolve ahead of
the core entry of the same name.

Everything here is construction and reflection on the class tree: no
connection, no dialect capability probe, so the file satisfies §12.
"""

import importlib
import pkgutil

import pytest

from rhosocial.activerecord.backend.expression.core import BaseExpression
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect

BIGQUERY_EXPR_PKG = "rhosocial.activerecord.backend.impl.bigquery.expression"


def _bigquery_nodes():
    """Every concrete expression class this backend's package defines."""
    pkg = importlib.import_module(BIGQUERY_EXPR_PKG)
    found = {}
    for module_info in pkgutil.walk_packages(
        pkg.__path__, pkg.__name__ + ".", onerror=lambda _error: None
    ):
        module = importlib.import_module(module_info.name)
        for name, obj in vars(module).items():
            if (
                isinstance(obj, type)
                and obj.__module__ == module_info.name
                and issubclass(obj, BaseExpression)
                and obj is not BaseExpression
                and not getattr(obj, "__abstractmethods__", None)
            ):
                found[f"{module_info.name}.{name}"] = obj
    return found


NODES = _bigquery_nodes()


def _declared_entry(cls):
    """The entry name *cls* declares, read off the class rather than an instance."""
    declared = cls.__dict__.get("format_method")
    if not isinstance(declared, property):
        return None
    return declared.fget(cls.__new__(cls))


class TestThreeSourcesAgree:
    def test_the_package_defines_the_four_materialized_view_statements(self):
        """A guard on the sweep below: an empty package would pass it silently."""
        assert set(NODES) == {
            f"{BIGQUERY_EXPR_PKG}.materialized_view.BigQueryAlterMaterializedViewSetOptionsStatement",
            f"{BIGQUERY_EXPR_PKG}.materialized_view.BigQueryCreateMaterializedViewReplicaStatement",
            f"{BIGQUERY_EXPR_PKG}.materialized_view.BigQueryCreateMaterializedViewStatement",
            f"{BIGQUERY_EXPR_PKG}.materialized_view.BigQueryDropMaterializedViewStatement",
        }

    @pytest.mark.parametrize("fqn", sorted(NODES))
    def test_the_entry_is_format_plus_the_kind(self, fqn):
        """§3: kind and entry are one identity, so the entry names the kind."""
        cls = NODES[fqn]
        entry = _declared_entry(cls)
        assert entry is not None, f"{fqn} declares no format_method"
        assert entry == "format_" + cls.kind(), (
            f"{fqn}: class name gives kind {cls.kind()!r}, but the class "
            f"declares {entry!r}"
        )

    @pytest.mark.parametrize("fqn", sorted(NODES))
    def test_the_kind_starts_with_the_backend_name(self, fqn):
        """§3: the backend name is at the head of a kind it owns."""
        kind = NODES[fqn].kind()
        assert kind.startswith("bigquery_"), kind

    @pytest.mark.parametrize("fqn", sorted(NODES))
    def test_the_class_name_ends_with_its_nature(self, fqn):
        """§3: these four are statements, and their names say so."""
        cls = NODES[fqn]
        assert cls.__name__.endswith("Statement"), cls.__name__
        assert cls.kind().endswith("_statement"), cls.kind()


class TestTheEntryResolvesAheadOfCore:
    """§11.1: an override placed after the class it overrides never wins."""

    @pytest.mark.parametrize(
        "entry",
        [
            "format_bigquery_create_materialized_view_statement",
            "format_bigquery_drop_materialized_view_statement",
            "format_bigquery_alter_materialized_view_set_options_statement",
            "format_bigquery_create_materialized_view_replica_statement",
        ],
    )
    def test_the_bigquery_mixin_owns_the_entry(self, entry):
        assert (
            getattr(BigQueryDialect, entry).__qualname__.startswith(
                "BigQueryMaterializedViewMixin."
            )
        )

    @pytest.mark.parametrize(
        "entry",
        [
            "format_create_materialized_view_statement",
            "format_drop_materialized_view_statement",
        ],
    )
    def test_the_core_statements_still_reach_the_bigquery_mixin(self, entry):
        """Core's own entry names are BigQuery's answers too, not core's."""
        assert (
            getattr(BigQueryDialect, entry).__qualname__.startswith(
                "BigQueryMaterializedViewMixin."
            )
        )
