# tests/rhosocial/activerecord_bigquery_test/feature/backend/ddl/test_type_domain_negative.py
"""Negative TYPE and DOMAIN DDL contracts for BigQuery."""

from __future__ import annotations

from typing import Tuple

import pytest

from rhosocial.activerecord.backend.dialect import (
    DomainMixin,
    DomainSupport,
    UserDefinedTypeMixin,
    UserDefinedTypeSupport,
)
from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError
from rhosocial.activerecord.backend.expression import BaseExpression, Literal
from rhosocial.activerecord.backend.expression.statements import (
    AlterDomainExpression,
    AlterTypeExpression,
    CreateDomainExpression,
    CreateSchemaExpression,
    CreateTypeExpression,
    DomainCheckConstraint,
    DomainNullability,
    DomainValueExpression,
    DropDomainDefaultAction,
    DropDomainExpression,
    DropTypeExpression,
    TypeAlterAction,
    TypeDefinition,
)
from rhosocial.activerecord.backend.expression.types import (
    ArrayType,
    DataType,
    IntegerType,
    JsonType,
)
from rhosocial.activerecord.backend.impl.bigquery import (
    BigQueryArray,
    BigQueryJSON,
    BigQueryStruct,
)
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect
from rhosocial.activerecord.backend.impl.bigquery.mixins import (
    BigQueryArrayMixin,
    BigQueryJSONMixin,
    BigQuerySchemaMixin,
    BigQueryStructMixin,
    BigQueryTypeSupportMixin,
)
from rhosocial.activerecord.backend.impl.bigquery.protocols import (
    BigQueryArraySupport,
    BigQueryJSONSupport,
    BigQueryStructSupport,
)


class _NegativeTypeDefinition(TypeDefinition):
    @property
    def definition_kind(self) -> str:
        return "negative"


class _NegativeTypeAlterAction(TypeAlterAction):
    @property
    def action_kind(self) -> str:
        return "negative"


TYPE_DOMAIN_SUPPORT_FLAGS = (
    "supports_type_objects",
    "supports_create_type",
    "supports_alter_type",
    "supports_drop_type",
    "supports_create_type_if_not_exists",
    "supports_create_type_or_replace",
    "supports_alter_type_if_exists",
    "supports_drop_type_if_exists",
    "supports_multiple_type_alter_actions",
    "supports_domains",
    "supports_create_domain",
    "supports_alter_domain",
    "supports_drop_domain",
    "supports_domain_default",
    "supports_domain_checks",
    "supports_named_domain_checks",
    "supports_multiple_domain_checks",
    "supports_domain_collation",
    "supports_multiple_domain_alter_actions",
    "supports_drop_domain_if_exists",
    "supports_drop_domain_cascade",
    "supports_drop_domain_restrict",
    "supports_unnamed_domain_check_drop",
)

TYPE_FORMATTERS = (
    "format_create_type_statement",
    "format_alter_type_statement",
    "format_drop_type_statement",
    "format_type_definition",
    "format_type_alter_action",
)

DOMAIN_FORMATTERS = (
    "format_create_domain_statement",
    "format_alter_domain_statement",
    "format_drop_domain_statement",
    "format_domain_value_expression",
    "format_domain_check_constraint",
    "format_domain_alter_action",
)


@pytest.fixture
def dialect() -> BigQueryDialect:
    return BigQueryDialect()


def _type_nodes(dialect: BigQueryDialect) -> Tuple[BaseExpression, ...]:
    definition = _NegativeTypeDefinition(dialect)
    action = _NegativeTypeAlterAction(dialect)
    return (
        CreateTypeExpression(
            dialect,
            "status",
            definition,
            if_not_exists=True,
        ),
        AlterTypeExpression(
            dialect,
            "status",
            [action],
            if_exists=True,
        ),
        DropTypeExpression(dialect, "status", if_exists=True),
        definition,
        action,
    )


def _domain_nodes(dialect: BigQueryDialect) -> Tuple[BaseExpression, ...]:
    condition = DomainValueExpression(dialect) > Literal(
        dialect,
        0,
        inline_literals=True,
    )
    check = DomainCheckConstraint(dialect, condition, name="nonnegative")
    action = DropDomainDefaultAction(dialect)
    return (
        CreateDomainExpression(
            dialect,
            "nonnegative",
            IntegerType(dialect),
            checks=[check],
            collation="und:ci",
        ),
        AlterDomainExpression(dialect, "nonnegative", [action]),
        DropDomainExpression(dialect, "nonnegative"),
        DomainValueExpression(dialect),
        check,
        action,
    )


def test_type_and_domain_protocols_and_mixins_are_composed(
    dialect: BigQueryDialect,
) -> None:
    assert isinstance(dialect, UserDefinedTypeSupport)
    assert isinstance(dialect, DomainSupport)
    assert isinstance(dialect, UserDefinedTypeMixin)
    assert isinstance(dialect, DomainMixin)

    mro = BigQueryDialect.__mro__
    for mixin, protocol in (
        (UserDefinedTypeMixin, UserDefinedTypeSupport),
        (DomainMixin, DomainSupport),
    ):
        assert mixin in mro
        assert protocol in mro
        assert mro.index(mixin) < mro.index(protocol)

    for protocol in (
        BigQueryStructSupport,
        BigQueryArraySupport,
        BigQueryJSONSupport,
    ):
        assert protocol in mro
        assert not issubclass(protocol, UserDefinedTypeSupport)
        assert not issubclass(protocol, DomainSupport)

    for mixin in (
        BigQueryTypeSupportMixin,
        BigQueryStructMixin,
        BigQueryArrayMixin,
        BigQueryJSONMixin,
        BigQuerySchemaMixin,
    ):
        assert not issubclass(mixin, UserDefinedTypeMixin)
        assert not issubclass(mixin, DomainMixin)


def test_core_type_and_domain_formatters_own_the_mro() -> None:
    for method_name in TYPE_FORMATTERS:
        assert getattr(BigQueryDialect, method_name) is getattr(
            UserDefinedTypeMixin,
            method_name,
        )
    for method_name in DOMAIN_FORMATTERS:
        assert getattr(BigQueryDialect, method_name) is getattr(
            DomainMixin,
            method_name,
        )


def test_schema_level_type_and_domain_support_is_false(
    dialect: BigQueryDialect,
) -> None:
    for method_name in TYPE_DOMAIN_SUPPORT_FLAGS:
        assert getattr(dialect, method_name)() is False, method_name

    assert dialect.supported_type_definitions() == ()
    assert dialect.supports_type_definition(_NegativeTypeDefinition) is False
    assert dialect.supports_type_alter_action(_NegativeTypeAlterAction) is False
    for nullability in DomainNullability:
        assert dialect.supports_domain_nullability(nullability) is False
    assert dialect.supports_alter_domain_action(DropDomainDefaultAction) is False


def test_type_formatters_and_expressions_fail_fast(
    dialect: BigQueryDialect,
) -> None:
    nodes = _type_nodes(dialect)
    for formatter_name, node in zip(TYPE_FORMATTERS, nodes, strict=True):
        with pytest.raises(UnsupportedFeatureError):
            getattr(dialect, formatter_name)(node)
        with pytest.raises(UnsupportedFeatureError):
            node.to_sql()


def test_domain_formatters_and_expressions_fail_fast(
    dialect: BigQueryDialect,
) -> None:
    nodes = _domain_nodes(dialect)
    for formatter_name, node in zip(DOMAIN_FORMATTERS, nodes, strict=True):
        with pytest.raises(UnsupportedFeatureError):
            getattr(dialect, formatter_name)(node)
        with pytest.raises(UnsupportedFeatureError):
            node.to_sql()


def test_column_types_and_dataset_schema_remain_separate(
    dialect: BigQueryDialect,
) -> None:
    data_types = (
        JsonType(dialect),
        ArrayType(dialect, IntegerType(dialect)),
    )
    for data_type in data_types:
        assert isinstance(data_type, DataType)
        assert not isinstance(data_type, TypeDefinition)

    value_objects = (
        BigQueryStruct({"id": 1}),
        BigQueryArray([1]),
        BigQueryJSON({"id": 1}),
    )
    for value_object in value_objects:
        assert not isinstance(value_object, DataType)
        assert not isinstance(value_object, TypeDefinition)

    assert dialect.supports_data_type_json() is True
    assert dialect.supports_struct() is True
    assert dialect.supports_array() is True
    assert dialect.supports_json() is True
    assert JsonType(dialect).to_sql() == ("JSON", ())

    schema = CreateSchemaExpression(dialect, "analytics")
    assert dialect.supports_create_schema() is True
    assert dialect.supports_domains() is False
    assert schema.to_sql() == ("CREATE SCHEMA `analytics`", ())
