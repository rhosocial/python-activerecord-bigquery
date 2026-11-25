# tests/rhosocial/activerecord_bigquery_test/feature/backend/ddl/test_bigquery_table_options.py
"""BigQuery ``ALTER TABLE`` option DDL: probes, exact SQL and by-name refusals.

Evidence level: 文档（待云验证） for the ``SET OPTIONS`` half. The production and
its closed ``table_set_options_list`` come from Google's official DDL reference
(fetched 2026-11-25):

https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language#alter_table_set_options_statement

The ``UNSET OPTIONS`` spelling is the one supplied with the migration task. The
reference above has no ``UNSET OPTIONS`` production and documents clearing as
``SET OPTIONS(option_name = NULL)``, so its probe row records that evidence
gap instead of claiming a verified server contract. Every assertion here is
construction and reflection: no BigQuery instance is contacted.
"""
import inspect
import re

import pytest

from rhosocial.activerecord.backend.expression.objects import Table
from rhosocial.activerecord.backend.expression.serialization import core_registry
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect
from rhosocial.activerecord.backend.impl.bigquery.expression import (
    BigQueryAlterTableSetOptionsStatement,
    BigQueryAlterTableUnsetOptionsStatement,
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
    (
        "supports_alter_table_unset_options",
        True,
        "task-supplied server syntax; NOT in the official DDL reference fetched "
        "2026-11-25, which clears an option with SET OPTIONS(name = NULL)",
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


def test_the_evidence_levels_are_written_on_the_probes():
    """The unverified UNSET answer may not quietly pass as a documented one."""
    set_doc = inspect.getdoc(BigQueryTableOptionsMixin.supports_alter_table_options) or ""
    unset_doc = inspect.getdoc(BigQueryTableOptionsMixin.supports_alter_table_unset_options) or ""
    assert "#alter_table_set_options_statement" in set_doc
    assert "unverified" in unset_doc
    assert "SET OPTIONS(option_name = NULL)" in unset_doc


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


def test_unset_options_exact_sql(dialect):
    expr = BigQueryAlterTableUnsetOptionsStatement(
        dialect, Table(dialect, "orders"), ("description", "labels")
    )
    assert expr.to_sql() == (
        "ALTER TABLE `orders` UNSET OPTIONS(description, labels)",
        (),
    )


def test_unset_options_owner_qualified_and_if_exists(dialect):
    expr = BigQueryAlterTableUnsetOptionsStatement(
        dialect,
        Table(dialect, "orders", schema_name="analytics", catalog_name="my-project"),
        ("expiration_timestamp",),
        if_exists=True,
    )
    assert expr.to_sql() == (
        "ALTER TABLE IF EXISTS `my-project`.`analytics`.`orders` "
        "UNSET OPTIONS(expiration_timestamp)",
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


@pytest.mark.parametrize(
    "names,message",
    [
        ((), "at least one option name"),
        (("enable_refresh",), "enable_refresh"),
        (("description", "description"), "repeats"),
        ("description", "sequence of documented option names"),
    ],
    ids=["empty", "unknown-name", "duplicate", "bare-string"],
)
def test_unset_options_refuses_unsupported_names(dialect, names, message):
    expr = BigQueryAlterTableUnsetOptionsStatement(dialect, Table(dialect, "orders"), names)
    with pytest.raises(ValueError, match=re.escape(message)):
        expr.to_sql()


def test_a_wrong_object_kind_is_refused_by_name(dialect):
    """A View renders valid SQL too, so the node must refuse it by kind."""
    from rhosocial.activerecord.backend.expression.objects import View

    for expr in (
        BigQueryAlterTableSetOptionsStatement(
            dialect, View(dialect, "v"), (("description", "x"),)
        ),
        BigQueryAlterTableUnsetOptionsStatement(dialect, View(dialect, "v"), ("description",)),
    ):
        with pytest.raises(TypeError, match=".table must be a Table, got View"):
            expr.to_sql()


def test_the_kinds_are_bigquery_proprietary(dialect):
    """These nodes are this backend's, never re-exported through core's registry."""
    core = core_registry()
    for expr in (
        BigQueryAlterTableSetOptionsStatement(
            dialect, Table(dialect, "t"), (("description", "x"),)
        ),
        BigQueryAlterTableUnsetOptionsStatement(dialect, Table(dialect, "t"), ("description",)),
    ):
        assert expr.kind().startswith("bigquery_")
        assert expr.kind() not in core.node_kinds()
        assert dialect.artifact_registry().resolve_node(expr.kind()) is type(expr)
