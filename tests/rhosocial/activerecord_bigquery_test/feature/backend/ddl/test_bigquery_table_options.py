# tests/rhosocial/activerecord_bigquery_test/feature/backend/ddl/test_bigquery_table_options.py
"""BigQuery ``ALTER TABLE SET OPTIONS``: probes, exact SQL and by-name refusals.

Evidence level: 文档（待云验证）. The production and its closed
``table_set_options_list`` come from Google's official DDL reference
(fetched 2026-11-25):

https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language#alter_table_set_options_statement

That reference has **no** ``UNSET OPTIONS`` production: clearing an option is
``SET OPTIONS(option_name = NULL)``. No UNSET node, formatter or probe exists,
and a test below refuses to let one reappear from a task brief or a
third-party summary. Every assertion here is construction and reflection: no
BigQuery instance is contacted.
"""
import importlib
import inspect
import pkgutil
import re

import pytest

from rhosocial.activerecord.backend.expression.bases.bases import BaseExpression
from rhosocial.activerecord.backend.expression.objects import Table
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect
from rhosocial.activerecord.backend.impl.bigquery.expression import (
    BigQueryAlterTableSetOptionsStatement,
)
from rhosocial.activerecord.backend.impl.bigquery.mixins import BigQueryTableOptionsMixin
from rhosocial.activerecord.backend.impl.bigquery.protocols import BigQueryTableOptionsSupport

#: name, expected answer, evidence. Registered in the capability test table
#: below so a core default cannot answer for this dialect.
TABLE_OPTION_PROBES = (
    (
        "supports_alter_table_options",
        True,
        "official DDL reference documents ALTER TABLE ... SET OPTIONS and a closed "
        "table_set_options_list",
    ),
)


@pytest.fixture
def dialect():
    return BigQueryDialect()


@pytest.mark.parametrize(
    "switch_name,expected,evidence",
    TABLE_OPTION_PROBES,
    ids=[name for name, _, _ in TABLE_OPTION_PROBES],
)
def test_every_table_option_probe_is_honest(switch_name, expected, evidence, dialect):
    """Each answer is declared by this backend and carries its evidence."""
    declaring = next(
        cls for cls in type(dialect).__mro__ if switch_name in cls.__dict__
    )
    assert declaring is BigQueryTableOptionsMixin, declaring
    assert getattr(dialect, switch_name)() is expected, evidence


def test_the_protocol_is_advertised(dialect):
    """The capability surface is a declared protocol, not an accident."""
    assert isinstance(dialect, BigQueryTableOptionsSupport)


def test_the_evidence_is_written_on_the_probe():
    """The documented answer names the reference it rests on."""
    doc = inspect.getdoc(BigQueryTableOptionsMixin.supports_alter_table_options) or ""
    assert "#alter_table_set_options_statement" in doc


def test_no_unset_options_node_probe_formatter_or_kind_exists(dialect):
    """The official reference has no UNSET OPTIONS; this backend must not invent one."""
    package = importlib.import_module(
        "rhosocial.activerecord.backend.impl.bigquery.expression"
    )
    expression_names = []
    for module_info in pkgutil.walk_packages(
        package.__path__, package.__name__ + ".", onerror=lambda _error: None
    ):
        module = importlib.import_module(module_info.name)
        for name, obj in vars(module).items():
            if (
                isinstance(obj, type)
                and obj.__module__ == module_info.name
                and issubclass(obj, BaseExpression)
            ):
                expression_names.append(name)
                assert "unsetoptions" not in name.lower(), name
                assert "unset_options" not in obj.kind().lower(), obj.kind()

    member_names = list(vars(BigQueryTableOptionsMixin)) + list(
        vars(BigQueryTableOptionsSupport)
    )
    for name in member_names:
        assert "unset_options" not in name.lower(), name
    for name in dir(dialect):
        assert "unset_options" not in name.lower(), name


def test_clearing_an_option_uses_set_options_with_null(dialect):
    """The only documented clearing spelling: SET OPTIONS(option_name = NULL)."""
    expr = BigQueryAlterTableSetOptionsStatement(
        dialect, Table(dialect, "orders"), (("description", None),)
    )
    assert expr.to_sql() == (
        "ALTER TABLE `orders` SET OPTIONS(description = NULL)",
        (),
    )


def test_the_modules_warn_against_adding_unset_options():
    """The prohibition is written where a future contributor will read it."""
    for module in (
        importlib.import_module(
            "rhosocial.activerecord.backend.impl.bigquery.expression.statements.table_options"
        ),
        importlib.import_module(
            "rhosocial.activerecord.backend.impl.bigquery.mixins.table_options"
        ),
    ):
        doc = inspect.getdoc(module) or ""
        flattened = " ".join(doc.split())
        assert "``ALTER TABLE ... UNSET OPTIONS`` production" in flattened
        assert "task briefs or third-party summaries" in flattened


def test_set_options_description(dialect):
    expr = BigQueryAlterTableSetOptionsStatement(
        dialect, Table(dialect, "orders"), (("description", "orders table"),)
    )
    assert expr.to_sql() == (
        "ALTER TABLE `orders` SET OPTIONS(description = 'orders table')",
        (),
    )


def test_set_options_labels_and_expiration(dialect):
    expr = BigQueryAlterTableSetOptionsStatement(
        dialect,
        Table(dialect, "orders"),
        (
            ("labels", (("org_unit", "development"), ("env", "prod"))),
            ("expiration_timestamp", "2025-01-01 00:00:00 UTC"),
        ),
    )
    assert expr.to_sql() == (
        "ALTER TABLE `orders` SET OPTIONS("
        "labels = [('org_unit', 'development'), ('env', 'prod')], "
        "expiration_timestamp = TIMESTAMP '2025-01-01 00:00:00 UTC')",
        (),
    )


def test_set_options_owner_qualified_table_and_if_exists(dialect):
    """Project in catalog_name, dataset in schema_name, both backtick-quoted."""
    expr = BigQueryAlterTableSetOptionsStatement(
        dialect,
        Table(dialect, "orders", schema_name="analytics", catalog_name="my-project"),
        (("require_partition_filter", True), ("partition_expiration_days", 7)),
        if_exists=True,
    )
    assert expr.to_sql() == (
        "ALTER TABLE IF EXISTS `my-project`.`analytics`.`orders` "
        "SET OPTIONS(require_partition_filter = true, partition_expiration_days = 7)",
        (),
    )


def test_set_options_escapes_string_values_without_bind_parameters(dialect):
    expr = BigQueryAlterTableSetOptionsStatement(
        dialect,
        Table(dialect, "orders"),
        (("description", "it's a \\ path"),),
    )
    sql, params = expr.to_sql()
    assert sql == "ALTER TABLE `orders` SET OPTIONS(description = 'it\\'s a \\\\ path')"
    assert params == ()


def test_set_options_null_clears_an_option(dialect):
    """The reference documents NULL as the clearing value."""
    expr = BigQueryAlterTableSetOptionsStatement(
        dialect, Table(dialect, "orders"), (("expiration_timestamp", None),)
    )
    assert expr.to_sql() == (
        "ALTER TABLE `orders` SET OPTIONS(expiration_timestamp = NULL)",
        (),
    )


def test_set_options_interval_and_enum_values(dialect):
    expr = BigQueryAlterTableSetOptionsStatement(
        dialect,
        Table(dialect, "orders"),
        (
            ("max_staleness", ("4:0:0", "HOUR TO SECOND")),
            ("default_rounding_mode", "ROUND_HALF_EVEN"),
        ),
    )
    assert expr.to_sql() == (
        "ALTER TABLE `orders` SET OPTIONS(max_staleness = INTERVAL '4:0:0' "
        "HOUR TO SECOND, default_rounding_mode = 'ROUND_HALF_EVEN')",
        (),
    )


@pytest.mark.parametrize(
    "options,message",
    [
        ((), "at least one table option"),
        ({"description": "x"}, "sequence of (name, value) pairs"),
        ((("enable_refresh", True),), "enable_refresh"),
        ((("description", {"nested": "shape"}),), "needs a string value"),
        ((("description", ("a", "b")),), "needs a string value"),
        ((("require_partition_filter", "true"),), "needs a bool value"),
        ((("partition_expiration_days", "7"),), "needs an int or float value"),
        ((("partition_expiration_days", True),), "needs an int or float value"),
        ((("expiration_timestamp", 123),), "needs a non-empty timestamp string"),
        ((("labels", [{"a": "b"}]),), "(key, value) pair of strings"),
        ((("labels", "a=b"),), "sequence of (key, value) string pairs"),
        ((("max_staleness", (7, "HOUR")),), "pair of strings"),
        ((("max_staleness", ("4", "FOO TO BAR")),), "interval qualifier"),
        ((("default_rounding_mode", "HALF_UP"),), "ROUND_HALF_EVEN"),
        ((("description", "x"), ("description", "y")), "repeats"),
        (("description",), "(name, value) pair"),
    ],
    ids=[
        "empty",
        "dict-options",
        "mv-option-name",
        "nested-dict-value",
        "tuple-string-value",
        "string-bool",
        "string-number",
        "bool-number",
        "numeric-timestamp",
        "dict-label-pair",
        "flat-label",
        "numeric-interval-pair",
        "bad-interval-part",
        "bad-rounding-mode",
        "duplicate-name",
        "not-a-pair",
    ],
)
def test_set_options_refuses_unsupported_shapes_and_values(dialect, options, message):
    """Refusals name the option or the shape; nothing is silently stringified."""
    expr = BigQueryAlterTableSetOptionsStatement(dialect, Table(dialect, "orders"), options)
    with pytest.raises(ValueError, match=re.escape(message)):
        expr.to_sql()


def test_a_wrong_object_kind_is_refused_by_name(dialect):
    """A View renders valid SQL too, so the node must refuse it by kind."""
    from rhosocial.activerecord.backend.expression.objects import View

    expr = BigQueryAlterTableSetOptionsStatement(
        dialect, View(dialect, "v"), (("description", "x"),)
    )
    with pytest.raises(TypeError, match=".table must be a Table, got View"):
        expr.to_sql()
