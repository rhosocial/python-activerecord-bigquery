# tests/rhosocial/activerecord_bigquery_test/feature/backend/ddl/test_bigquery_index_capabilities.py
"""BigQuery index capability probes and by-name refusals.

BigQuery has no plain ``CREATE INDEX`` / ``DROP INDEX`` statement.  Its index
DDL is the separate ``CREATE SEARCH INDEX`` / ``DROP SEARCH INDEX`` /
``ALTER SEARCH INDEX`` family (plus the preview AI INDEX family), which core's
index expressions do not model.  These tests pin every index probe the dialect
exposes, and assert that the plain-index formatters refuse by name instead of
emitting SQL the service would reject.

Evidence (fetched 2026-11-25):
https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language#create_search_index_statement
https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language#drop_search_index
"""

import inspect

import pytest

from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError
from rhosocial.activerecord.backend.dialect.protocols import (
    OperationalStatsIntrospectionSupport,
    StructureIntrospectionSupport,
)
from rhosocial.activerecord.backend.expression import (
    AlterTableStatement,
    CreateTableStatement,
)
from rhosocial.activerecord.backend.expression.objects import Index, Table
from rhosocial.activerecord.backend.expression.statements import (
    ColumnDefinition,
    IndexDefinition,
)
from rhosocial.activerecord.backend.expression.statements.ddl_alter import (
    AddIndexAction,
    DropIndexAction,
)
from rhosocial.activerecord.backend.expression.statements.ddl_index import (
    CreateIndexStatement,
    DropIndexStatement,
)
from rhosocial.activerecord.backend.expression.types import IntegerType
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect
from rhosocial.activerecord.backend.impl.bigquery.mixins import BigQueryIndexMixin


#: name, expected answer, and the reason the answer is what it is.
INDEX_PROBES = (
    # -- flipped by this change: core's defaults claimed plain index DDL ----
    (
        "supports_create_index",
        False,
        "no CREATE INDEX production exists in the DDL reference",
    ),
    (
        "supports_unique_index",
        False,
        "no CREATE INDEX production, so no UNIQUE qualifier position",
    ),
    (
        "supports_drop_index",
        False,
        "no DROP INDEX production exists in the DDL reference",
    ),
    (
        "supports_drop_index_on_table",
        False,
        "ON <table> belongs to DROP SEARCH INDEX / DROP AI INDEX, not plain DROP INDEX",
    ),
    # -- already False, pinned locally so a core default cannot move them ----
    ("supports_index_if_not_exists", False, "IF NOT EXISTS is SEARCH/AI INDEX only"),
    ("supports_index_if_exists", False, "IF EXISTS is SEARCH/AI INDEX only"),
    ("supports_index_type", False, "no USING clause in any index production"),
    ("supports_partial_index", False, "no WHERE clause in any index production"),
    ("supports_functional_index", False, "no expression position in the index grammar"),
    ("supports_index_include", False, "no INCLUDE clause in any index production"),
    ("supports_index_tablespace", False, "BigQuery has no tablespaces"),
    ("supports_concurrent_index", False, "no CONCURRENTLY keyword in GoogleSQL"),
    ("supports_fulltext_index", False, "SEARCH INDEX is not a FULLTEXT index clause"),
    ("supports_inline_index", False, "CREATE TABLE has no inline index branch"),
    # -- adjacent answers, already declared by other mixins -----------------
    (
        "supports_alter_table_index_actions",
        False,
        "no ALTER TABLE ADD/DROP INDEX production",
    ),
    ("supports_index_introspection", False, "BigQuery has no index catalogue view"),
    ("supports_index_stats", False, "no index usage statistics family"),
    ("supports_unused_indexes_detection", False, "no unused-index statistics family"),
)

#: The three entries at the end of ``INDEX_PROBES`` are core introspection
#: members rather than index DDL probes, grouped here by the family that owns
#: each after core split the single ``IntrospectionSupport``. The index
#: *declaration* question belongs to structure; the two counter questions
#: belong to operational statistics. All three are on the declined side, and
#: the classification is asserted so they cannot drift into the wrong family.
INTROSPECTION_INDEX_PROBES = {
    "supports_index_introspection": StructureIntrospectionSupport,
    "supports_index_stats": OperationalStatsIntrospectionSupport,
    "supports_unused_indexes_detection": OperationalStatsIntrospectionSupport,
}


@pytest.fixture
def dialect():
    return BigQueryDialect()


@pytest.mark.parametrize(
    "switch_name,expected,reason",
    INDEX_PROBES,
    ids=[name for name, _, _ in INDEX_PROBES],
)
def test_every_index_probe_is_honest(switch_name, expected, reason, dialect):
    """Each probe answers what the grammar supports, not a core default."""
    assert getattr(dialect, switch_name)() is expected, reason


@pytest.mark.parametrize(
    "switch_name,family",
    list(INTROSPECTION_INDEX_PROBES.items()),
    ids=list(INTROSPECTION_INDEX_PROBES),
)
def test_the_introspection_entries_are_classified_per_family(switch_name, family, dialect):
    """The introspection probes name the family that owns them.

    Reclassified after core split ``IntrospectionSupport`` into four families:
    the index-declaration switch is structure, the two counter switches are
    operational statistics. The dialect declines all three, so each stays on
    the negative side of its family rather than being read as an index probe.
    """
    assert switch_name in family.__dict__, switch_name
    expected = next(answer for name, answer, _reason in INDEX_PROBES if name == switch_name)
    assert expected is False
    assert getattr(dialect, switch_name)() is expected


@pytest.mark.parametrize(
    "switch_name,expected,reason",
    INDEX_PROBES[:14],
    ids=[name for name, _, _ in INDEX_PROBES[:14]],
)
def test_each_ddl_index_probe_is_declared_in_this_package(
    switch_name, expected, reason, dialect
):
    """The DDL answers are owned here, not inherited from core."""
    declaring = next(
        cls for cls in type(dialect).__mro__ if switch_name in cls.__dict__
    )
    assert declaring.__module__.startswith(
        "rhosocial.activerecord.backend.impl.bigquery"
    ), f"{switch_name} is declared by {declaring.__module__}"
    assert getattr(dialect, switch_name)() is expected, reason


def test_create_index_refuses_by_name(dialect):
    expression = CreateIndexStatement(
        dialect, Index(dialect, "i"), Table(dialect, "t"), ["a"]
    )
    with pytest.raises(UnsupportedFeatureError) as caught:
        expression.to_sql()
    assert caught.value.feature_name == "CREATE INDEX"
    assert "CREATE SEARCH INDEX" in str(caught.value)


def test_unique_create_index_refuses_by_name(dialect):
    expression = CreateIndexStatement(
        dialect, Index(dialect, "i"), Table(dialect, "t"), ["a"], unique=True
    )
    with pytest.raises(UnsupportedFeatureError) as caught:
        expression.to_sql()
    assert caught.value.feature_name == "CREATE INDEX"
    assert "CREATE SEARCH INDEX" in str(caught.value)


def test_drop_index_refuses_by_name(dialect):
    expression = DropIndexStatement(
        dialect, Index(dialect, "i"), Table(dialect, "t"), if_exists=True
    )
    with pytest.raises(UnsupportedFeatureError) as caught:
        expression.to_sql()
    assert caught.value.feature_name == "DROP INDEX"
    assert "DROP SEARCH INDEX" in str(caught.value)


def test_alter_table_add_index_refuses_by_name(dialect):
    expression = AlterTableStatement(
        dialect,
        table=Table(dialect, "t"),
        action=AddIndexAction(dialect, IndexDefinition(dialect, "i", ["a"])),
    )
    with pytest.raises(UnsupportedFeatureError) as caught:
        expression.to_sql()
    assert caught.value.feature_name == "ALTER TABLE ADD INDEX"
    assert "ADD INDEX" in str(caught.value)


def test_alter_table_drop_index_refuses_by_name(dialect):
    expression = AlterTableStatement(
        dialect,
        table=Table(dialect, "t"),
        action=DropIndexAction(dialect, Index(dialect, "i")),
    )
    with pytest.raises(UnsupportedFeatureError) as caught:
        expression.to_sql()
    assert caught.value.feature_name == "ALTER TABLE DROP INDEX"
    assert "DROP INDEX" in str(caught.value)


def test_inline_create_table_index_is_refused(dialect):
    column = ColumnDefinition(dialect, "id", IntegerType(dialect))
    expression = CreateTableStatement(
        dialect,
        Table(dialect, "t"),
        [column],
        indexes=[IndexDefinition(dialect, "i", ["id"])],
    )
    with pytest.raises(UnsupportedFeatureError) as caught:
        expression.to_sql()
    assert "inline index" in str(caught.value)


def test_search_index_family_is_recorded_as_unmodelled(dialect):
    """No SEARCH INDEX / AI INDEX formatter is invented on this dialect."""
    for method in (
        "format_create_search_index_statement",
        "format_drop_search_index_statement",
        "format_alter_search_index_statement",
        "format_create_ai_index_statement",
        "format_drop_ai_index_statement",
    ):
        assert not hasattr(dialect, method), f"{method} must not exist"
    doc = inspect.getdoc(inspect.getmodule(BigQueryIndexMixin)) or ""
    for phrase in ("CREATE SEARCH INDEX", "DROP SEARCH INDEX", "CREATE AI INDEX"):
        assert phrase in doc, f"the module docstring must record {phrase!r}"
