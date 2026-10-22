"""Protocol conformance tests for BigQuery backend."""

from rhosocial.activerecord.backend.dialect import (
    UserDefinedTypeMixin,
    DomainMixin,
)
from rhosocial.activerecord.backend.dialect.protocols import (
    CreateTypeSupport,
    AlterTypeSupport,
    DropTypeSupport,
    CreateDomainSupport,
    AlterDomainSupport,
    DropDomainSupport,
)
from rhosocial.activerecord.backend.impl.bigquery.protocols import (
    BigQueryStructSupport,
    BigQueryArraySupport,
    BigQueryJSONSupport,
    BigQueryGeographySupport,
)
from rhosocial.activerecord.backend.impl.bigquery import protocols as bigquery_protocols


def test_bigquery_protocol_exports_match_protocol_definitions() -> None:
    assert BigQueryStructSupport is bigquery_protocols.BigQueryStructSupport
    assert BigQueryArraySupport is bigquery_protocols.BigQueryArraySupport
    assert BigQueryJSONSupport is bigquery_protocols.BigQueryJSONSupport
    assert BigQueryGeographySupport is bigquery_protocols.BigQueryGeographySupport


PROTOCOL_MODULES = ("schema", "column", "materialized_view", "data_type")


def test_protocols_is_a_package_with_one_module_per_capability() -> None:
    """``protocols`` became a package, so a protocol is findable by name.

    It was a single module that grew. The refactor added two namespace
    protocols and the dialect rule for columns, and a reader looking for the
    latter should not have to grep past the type protocols to find it.
    """
    import importlib

    from rhosocial.activerecord.backend.impl.bigquery import protocols as pkg

    assert hasattr(pkg, "__path__")
    for module in PROTOCOL_MODULES:
        importlib.import_module(
            f"rhosocial.activerecord.backend.impl.bigquery.protocols.{module}"
        )


def test_naming_and_schema_ddl_are_separate_questions() -> None:
    """Naming both slots is one protocol; ``CREATE SCHEMA`` is a second.

    ``NamespaceSupport`` is core's, and it is the only one that answers "which
    levels may a name carry": catalog qualification and schema qualification are
    the same question asked of two slots, so one protocol covers both. BigQuery
    declares both levels, and it is the switches on
    ``BigQueryNamespaceMixin`` that do the declaring.

    ``BigQuerySchemaSupport`` is a different question -- does the engine have
    schemas at all, can it ``CREATE SCHEMA`` / ``DROP SCHEMA`` -- and an engine
    may answer it differently from the naming one. So there are exactly two
    protocols here and neither duplicates the other.

    There used to be a third, ``BigQueryCatalogSupport``, restating
    ``NamespaceSupport``'s three switches and ``validate_catalog_name`` verbatim.
    Under ``runtime_checkable`` structural matching that made
    ``isinstance(dialect, BigQueryCatalogSupport)`` true of *any* dialect with
    those methods: SQLite and Oracle included. The assertion below could not
    fail for a reason specific to BigQuery, which is what made it worth
    deleting.
    """
    from rhosocial.activerecord.backend.dialect.protocols import (
        NamespaceSupport,
    )
    from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect
    from rhosocial.activerecord.backend.impl.bigquery.mixins import (
        BigQueryNamespaceMixin,
    )
    from rhosocial.activerecord.backend.impl.bigquery.protocols import (
        BigQuerySchemaSupport,
    )

    dialect = BigQueryDialect()
    assert isinstance(dialect, NamespaceSupport)
    assert isinstance(dialect, BigQuerySchemaSupport)
    # The naming answers come from the one mixin that owns them, not from a
    # second protocol restating the first.
    assert BigQueryNamespaceMixin in type(dialect).__mro__
    for switch in (
        "supports_catalog",
        "supports_catalog_qualification",
        "supports_schema_qualification",
        "validate_catalog_name",
    ):
        owner = next(
            base.__name__
            for base in type(dialect).__mro__
            if switch in vars(base)
        )
        assert owner == "BigQueryNamespaceMixin", (
            f"{switch} is declared by {owner}; BigQuery's naming answers belong "
            f"to BigQueryNamespaceMixin, which is the backend's one naming-side "
            f"mixin"
        )


def test_the_column_rule_is_a_declared_capability() -> None:
    """BigQuery's one dialect-specific namespace rule is declared, not assumed."""
    from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect
    from rhosocial.activerecord.backend.impl.bigquery.protocols import (
        BigQueryColumnQualificationSupport,
    )

    dialect = BigQueryDialect()
    assert isinstance(dialect, BigQueryColumnQualificationSupport)
    assert dialect.supports_column_namespace_qualification() is False


class TestBigQueryStructSupport:
    def test_supports_struct(self):
        from rhosocial.activerecord.backend.impl.bigquery.mixins import BigQueryStructMixin
        mixin = BigQueryStructMixin()
        assert mixin.supports_struct() is True


class TestBigQueryArraySupport:
    def test_supports_array(self):
        from rhosocial.activerecord.backend.impl.bigquery.mixins import BigQueryArrayMixin
        mixin = BigQueryArrayMixin()
        assert mixin.supports_array() is True


class TestBigQueryJSONSupport:
    def test_supports_json(self):
        from rhosocial.activerecord.backend.impl.bigquery.mixins import BigQueryJSONMixin
        mixin = BigQueryJSONMixin()
        assert mixin.supports_json() is True


class TestBigQueryGeographySupport:
    def test_supports_geography(self):
        from rhosocial.activerecord.backend.impl.bigquery.mixins import BigQueryGeographyMixin
        mixin = BigQueryGeographyMixin()
        assert mixin.supports_geography() is True


class TestBigQueryDialectProtocols:
    def test_dialect_has_protocol_methods(self):
        from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect
        dialect = BigQueryDialect()
        assert dialect.supports_struct() is True
        assert dialect.supports_array() is True
        assert dialect.supports_json() is True
        assert dialect.supports_geography() is True

    def test_dialect_has_type_and_domain_protocols(self):
        from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect
        dialect = BigQueryDialect()
        for protocol in (
            CreateTypeSupport,
            AlterTypeSupport,
            DropTypeSupport,
            CreateDomainSupport,
            AlterDomainSupport,
            DropDomainSupport,
        ):
            assert isinstance(dialect, protocol), protocol.__name__
        assert isinstance(dialect, UserDefinedTypeMixin)
        assert isinstance(dialect, DomainMixin)


class TestTheBackendOwnAnswersAreTheEffectiveOnes:
    """A backend mixin's method must resolve to a backend class.

    The other checks in this file are about the *declaration*: the mixin
    declares the method, and the protocol declares it too. This one is
    about the *resolution*. A core class that wins the MRO makes the
    backend's implementation dead code, and the answer a caller gets is
    core's rather than the backend's -- so the backend never says what it
    means about itself, and nothing else in the suite notices: the
    declaration is there either way.

    A protocol class is a declaration rather than an implementation (its
    body is ``...``), so a core class may legitimately precede it; only
    the mixins are held to this.
    """

    def test_no_backend_method_is_shadowed_by_a_core_class(self):
        from rhosocial.activerecord.backend.impl.bigquery.dialect import (
            BigQueryDialect,
        )

        mro = type(BigQueryDialect()).__mro__
        own = "rhosocial.activerecord.backend.impl.bigquery"
        shadowed = []
        for klass in mro:
            if not klass.__module__.startswith(own):
                continue
            if not klass.__name__.endswith("Mixin"):
                continue
            for name in vars(klass):
                if not name.startswith(("format_", "supports_", "get_")):
                    continue
                if not callable(vars(klass)[name]):
                    continue
                winner = next((k for k in mro if name in k.__dict__), None)
                if winner is None or winner.__module__.startswith(own):
                    continue
                shadowed.append(f"{klass.__name__}.{name} -> {winner.__name__}")
        assert not shadowed, (
            "a core class wins these backend methods, so the backend's "
            f"implementation is dead code: {shadowed}"
        )
