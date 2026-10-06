# tests/rhosocial/activerecord_bigquery_test/feature/backend/test_expression_roundtrip_all.py
"""
Every expression class BigQuery can be handed survives serialisation, and
every one that cannot render says which of the four reasons applies.

Scope
=====

Two packages, not one. ``rhosocial.activerecord.backend.expression`` holds the
core classes a BigQuery statement is built from, and
``rhosocial.activerecord.backend.impl.bigquery.expression`` holds the four this
backend defines. BigQuery's SQL surface is the narrowest in the family --
one namespace level it qualifies by default, no sequences, no triggers, no
routines, no SQL/XML, no property graphs -- so the core classes are the
interesting ones here: most of them are either unreachable or an
``UnsupportedFeatureError``, and *which* is worth pinning. The five backends
that already have a matrix collect only their own package, which is why they
never learned that their dialect renders 143 of them and refuses 49 outright.

Why ``to_sql()`` is classified rather than caught
=================================================

The shared testsuite helper this matrix replaces wraps the first render in
``try/except Exception: return`` (``testsuite/utils/expression.py``, in
``sql_consistent``). That makes every render failure a green tick: the three
SQL comparisons after it never run, so a formatter reading a field that no
longer exists is indistinguishable from a formatter for a feature this dialect
does not support. Core measured what that costs on its own matrix -- 74 errors
reported as passes -- and replaced the blanket catch with per-type assertions.
This matrix is written to that standard.

Four outcomes, each asserted:

* **renders** -- all three encodings must restore byte-identical SQL *and*
  byte-identical bind parameters.
* a member of :data:`LEGITIMATE_NON_RENDERS` -- a class that cannot render
  because this dialect implements no formatter for it. Each entry pins the
  exception type *and* the message fragment, so a class that starts failing for
  a different reason fails here instead of staying quietly green.
* a member of :data:`LEGITIMATE_NOT_IMPLEMENTED` -- a class that names an
  expression category rather than a renderable thing and declares no
  ``format_method``, or a statement this dialect declines to render. Asserted as
  exactly ``NotImplementedError``, with the message pinned too.
* ``UnsupportedFeatureError`` from a class in neither table -- this dialect does
  not model the feature. Asserted as exactly that type, so a subclass raised for
  an unrelated reason is still visible rather than passing.
* **anything else** -- a failure naming the class and the exception.

The two tables are read before the ``UnsupportedFeatureError`` branch, because
core now reports a *missing formatter* through that same type; see
:func:`classify_sql_roundtrip`.

Discovery is not the registry
=============================

Classes are found by walking the two packages with
``collect_expression_classes``, never by reading
``ExpressionRegistry._registry``. The registry is process-global: it grows as
any sibling test module imports another backend, so a matrix built from it
holds whatever the import order happened to produce -- core measured three
different counts for the same tree that way. Walking the packages is
deterministic and is re-done inside the integrity tests, so a class that
appears after collection fails CI.

No skips
========

``make_instance(...) is None`` is not a skip here. Every class in the two
packages builds: the generic introspective constructor gets the ones whose
guesses are wrong replaced by a registered constructor below, and
:data:`UNCONSTRUCTIBLE` is pinned empty, with a test asserting it stays empty.
A class that cannot be built fails the matrix and names itself.
"""

import inspect

import pytest

from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError
from rhosocial.activerecord.backend.expression import graph as graph_mod
from rhosocial.activerecord.backend.expression.advanced_functions import (
    CaseExpression,
    WindowClause,
    WindowDefinition,
    WindowSpecification,
)
from rhosocial.activerecord.backend.expression.bases import BaseExpression
from rhosocial.activerecord.backend.expression.core import Column, Literal
from rhosocial.activerecord.backend.expression.datetime import (
    TemporalOptionsExpression,
)
from rhosocial.activerecord.backend.expression.operators import RawSQLExpression
from rhosocial.activerecord.backend.expression.objects import (
    Database,
    Domain,
    EdgeTable as EdgeTableObject,
    Function,
    Index,
    MaterializedView,
    NodeTable,
    PropertyGraph,
    Schema,
    Sequence,
    Table,
    Trigger,
    View,
)
from rhosocial.activerecord.backend.expression.predicates import ComparisonPredicate
from rhosocial.activerecord.backend.expression.query_parts import JoinClause
from rhosocial.activerecord.backend.expression.serialization import (
    ExpressionRegistry,
    deserialize,
    deserialize_json,
    deserialize_xml,
    serialize,
    serialize_json,
    serialize_xml,
)
from rhosocial.activerecord.backend.expression.sources import NamedRelationRef
from rhosocial.activerecord.backend.expression.statements import (
    ddl_alter,
    ddl_comment,
    ddl_database,
    ddl_domain,
    ddl_function,
    ddl_index,
    ddl_schema,
    ddl_sequence,
    ddl_table,
    ddl_trigger,
    ddl_truncate,
    ddl_view,
    dml,
)
from rhosocial.activerecord.backend.expression.statements.ddl_database import (
    AlterDatabaseAction,
)
from rhosocial.activerecord.backend.expression.statements.ddl_domain import (
    DomainCheckConstraint,
    RenameDomainAction,
)
from rhosocial.activerecord.backend.expression.statements.ddl_table import (
    ColumnConstraint,
    ColumnConstraintType,
    ForeignKeyConstraint,
    IndexDefinition,
    ReferencesClause,
    TableConstraint,
    TableConstraintType,
)
from rhosocial.activerecord.backend.expression.statements.ddl_trigger import (
    TriggerEvent,
    TriggerTiming,
)
from rhosocial.activerecord.backend.expression.statements.dml import (
    MergeAction,
    MergeActionType,
)
from rhosocial.activerecord.backend.expression.statements.dql import QueryExpression
from rhosocial.activerecord.backend.expression.types import (
    ArrayType,
    IntegerType,
    VarCharType,
)
from rhosocial.activerecord.backend.expression.types.enum_ import EnumType
from rhosocial.activerecord.backend.expression.xml import (
    XMLAttribute,
    XMLAttributesExpression,
    XMLConcatExpression,
    XMLForestExpression,
    XMLForestItem,
    XMLTableColumn,
    XMLTableExpression,
)
from rhosocial.activerecord.backend.impl.bigquery.expression import (
    BigQueryAlterMaterializedViewSetOptionsExpression,
)
from rhosocial.activerecord.testsuite.utils.expression import (
    collect_expression_classes,
    make_instance,
    register_all,
    register_special_constructor,
)

#: The two packages this backend renders. Core first: the four classes this
#: backend defines are BigQuery subclasses of core's, and the core spelling of
#: each is what a caller reaches for first.
CORE_EXPR_PKG = "rhosocial.activerecord.backend.expression"
BIGQUERY_EXPR_PKG = "rhosocial.activerecord.backend.impl.bigquery.expression"


def _collect_package(package_path):
    """Every concrete expression class one package defines, by walking it.

    Deduplicated by identity: several modules re-export the same class under a
    second name, and testing it twice asserts nothing extra.
    """
    collected = collect_expression_classes(package_path)
    first_name = {}
    for fqn, cls in sorted(collected.items()):
        first_name.setdefault(id(cls), fqn)
    return {
        first_name[id(cls)]: cls
        for cls in collected.values()
        if not inspect.isabstract(cls)
        for fqn in [first_name[id(cls)]]
    }


def _collect_matrix_classes():
    both = {}
    for package in (CORE_EXPR_PKG, BIGQUERY_EXPR_PKG):
        both.update(_collect_package(package))
    return dict(sorted(both.items()))


REGISTERED = _collect_matrix_classes()


# ---------------------------------------------------------------------------
# Special constructors: a real value where the introspective guess is a lie
# ---------------------------------------------------------------------------
#
# ``make_instance`` reads each required parameter's annotation and guesses:
# ``"x"`` for a string, ``[]`` for a list, ``IntegerType()`` for a type. That is
# right for a name and wrong for every parameter that wants a catalogue object --
# a Table, an Index, a PropertyGraph -- because a bare ``"x"`` is not one, and
# the formatter now refuses it by name. It is also wrong for the containers
# that must not be empty (CASE, WINDOW, a constraint's columns, a REFERENCES
# clause's referenced columns), for the enums it fills with a string the class
# then refuses, and for the predicates that must render without bind
# parameters. Every registration below replaces a guess that would otherwise
# have produced an instance this dialect cannot render.
#
# Suffixes are spelled relative to the class's module because ``make_instance``
# matches with ``str.endswith`` and several modules export identically named
# classes.


def _table(dialect, name="t"):
    """A table with a bare name and no namespace."""
    return Table(dialect, name)


def _column_predicate(dialect):
    """A predicate comparing two columns, so it renders with no bind parameters."""
    return ComparisonPredicate(dialect, "=", Column(dialect, "a"), Column(dialect, "b"))


def _one_column_query(dialect):
    """A single-column ``SELECT`` over a table."""
    return QueryExpression(dialect, select=[Column(dialect, "id")], from_=_table(dialect))


def _integer_column(dialect, name="col"):
    """A column definition carrying a *dialect-bound* type.

    The binding is load-bearing, not cosmetic: ``to_sql()`` dispatches on the
    type through its own dialect, so an unbound ``IntegerType()`` raises the
    moment anything renders it.
    """
    return ddl_table.ColumnDefinition(dialect, name, IntegerType(dialect))


def register_specials():
    """Replace every introspective guess that would cost a real assertion."""
    # -- the FROM side ------------------------------------------------------
    register_special_constructor(
        "sources.relation.NamedRelationRef",
        lambda d: NamedRelationRef(d, _table(d)),
    )
    register_special_constructor(
        "query_parts.JoinClause",
        lambda d: JoinClause(
            d,
            left_table=NamedRelationRef(d, _table(d)),
            right_table=NamedRelationRef(d, Table(d, "other")),
            condition=_column_predicate(d),
        ),
    )

    # -- tables -------------------------------------------------------------
    register_special_constructor(
        "statements.ddl_table.CreateTableExpression",
        lambda d: ddl_table.CreateTableExpression(d, _table(d), [_integer_column(d)]),
    )
    register_special_constructor(
        "statements.ddl_table.DropTableExpression",
        lambda d: ddl_table.DropTableExpression(d, _table(d)),
    )
    register_special_constructor(
        "statements.ddl_table.CreateTableLikeExpression",
        lambda d: ddl_table.CreateTableLikeExpression(d, _table(d), Table(d, "other")),
    )
    register_special_constructor(
        "statements.ddl_table.CreateTableCloneExpression",
        lambda d: ddl_table.CreateTableCloneExpression(d, _table(d), Table(d, "other")),
    )
    register_special_constructor(
        "statements.ddl_table.CreateTableAsExpression",
        lambda d: ddl_table.CreateTableAsExpression(d, _table(d), _one_column_query(d)),
    )
    register_special_constructor(
        "statements.ddl_table.CreateTableFromTemplateExpression",
        lambda d: ddl_table.CreateTableFromTemplateExpression(
            d, _table(d), _one_column_query(d)
        ),
    )
    register_special_constructor(
        "statements.ddl_truncate.TruncateExpression",
        lambda d: ddl_truncate.TruncateExpression(d, _table(d)),
    )
    # Overrides the shared testsuite factory, which binds no dialect to its type.
    register_special_constructor(
        "statements.ddl_table.ColumnDefinition", _integer_column
    )

    # -- constraints, which need member columns and real enum values ---------
    # The generic guess passes the constraint *type* as the string "x", which
    # every one of these refuses; and it passes no columns at all, which is a
    # FOREIGN KEY and a REFERENCES clause without an end.
    register_special_constructor(
        "statements.ddl_table.ColumnConstraint",
        lambda d: ColumnConstraint(d, ColumnConstraintType.NOT_NULL, name="c"),
    )
    register_special_constructor(
        "statements.ddl_table.TableConstraint",
        lambda d: TableConstraint(
            d, TableConstraintType.PRIMARY_KEY, name="c", columns=["a"]
        ),
    )
    register_special_constructor(
        "statements.ddl_table.ForeignKeyConstraint",
        lambda d: ForeignKeyConstraint(
            d,
            columns=["a"],
            foreign_key_table=Table(d, "other"),
            foreign_key_columns=["b"],
            name="fk",
        ),
    )
    register_special_constructor(
        "statements.ddl_table.ReferencesClause",
        lambda d: ReferencesClause(d, Table(d, "other"), ["b"]),
    )

    # -- indexes, and the ALTER TABLE actions over them ---------------------
    register_special_constructor(
        "statements.ddl_index.CreateIndexExpression",
        lambda d: ddl_index.CreateIndexExpression(
            d, index=Index(d, "i"), table=_table(d), columns=["a"]
        ),
    )
    register_special_constructor(
        "statements.ddl_index.DropIndexExpression",
        lambda d: ddl_index.DropIndexExpression(d, index=Index(d, "i")),
    )
    register_special_constructor(
        "statements.ddl_index.CreateFulltextIndexExpression",
        lambda d: ddl_index.CreateFulltextIndexExpression(
            d, index=Index(d, "i"), table=_table(d), columns=["a"]
        ),
    )
    register_special_constructor(
        "statements.ddl_index.DropFulltextIndexExpression",
        lambda d: ddl_index.DropFulltextIndexExpression(
            d, index=Index(d, "i"), table=_table(d)
        ),
    )
    register_special_constructor(
        "statements.ddl_alter.DropIndex", lambda d: ddl_alter.DropIndex(d, Index(d, "i"))
    )
    register_special_constructor(
        "statements.ddl_alter.AddIndex",
        lambda d: ddl_alter.AddIndex(d, IndexDefinition(d, "i", ["a"])),
    )
    register_special_constructor(
        "statements.ddl_alter.AddColumn",
        lambda d: ddl_alter.AddColumn(d, _integer_column(d)),
    )
    register_special_constructor(
        "statements.ddl_alter.AddTableConstraint",
        lambda d: ddl_alter.AddTableConstraint(
            d,
            TableConstraint(
                d, TableConstraintType.PRIMARY_KEY, name="c", columns=["a"]
            ),
        ),
    )
    # Both constraint modifiers hide their required arguments behind defaulted
    # positionals, so the introspective constructor skips them and the action
    # arrives incomplete.
    register_special_constructor(
        "statements.ddl_alter.AlterConstraint",
        lambda d: ddl_alter.AlterConstraint(
            d, name="c", constraint_type=TableConstraintType.CHECK
        ),
    )
    register_special_constructor(
        "statements.ddl_alter.ValidateConstraint",
        lambda d: ddl_alter.ValidateConstraint(d, name="c"),
    )

    # -- schemas, sequences, databases, domains, types ---------------------
    register_special_constructor(
        "statements.ddl_schema.CreateSchemaExpression",
        lambda d: ddl_schema.CreateSchemaExpression(d, Schema(d, "s")),
    )
    register_special_constructor(
        "statements.ddl_schema.DropSchemaExpression",
        lambda d: ddl_schema.DropSchemaExpression(d, Schema(d, "s")),
    )
    register_special_constructor(
        "statements.ddl_sequence.CreateSequenceExpression",
        lambda d: ddl_sequence.CreateSequenceExpression(d, Sequence(d, "s")),
    )
    register_special_constructor(
        "statements.ddl_sequence.AlterSequenceExpression",
        lambda d: ddl_sequence.AlterSequenceExpression(d, Sequence(d, "s"), restart=1),
    )
    register_special_constructor(
        "statements.ddl_sequence.DropSequenceExpression",
        lambda d: ddl_sequence.DropSequenceExpression(d, Sequence(d, "s")),
    )
    register_special_constructor(
        "statements.ddl_database.CreateDatabaseExpression",
        lambda d: ddl_database.CreateDatabaseExpression(d, Database(d, "db")),
    )
    register_special_constructor(
        "statements.ddl_database.DropDatabaseExpression",
        lambda d: ddl_database.DropDatabaseExpression(d, Database(d, "db")),
    )
    register_special_constructor(
        "statements.ddl_database.AlterDatabaseExpression",
        lambda d: ddl_database.AlterDatabaseExpression(
            d,
            Database(d, "db"),
            action=AlterDatabaseAction.RENAME_TO,
            target="renamed_db",
        ),
    )
    register_special_constructor(
        "statements.ddl_domain.CreateDomainExpression",
        lambda d: ddl_domain.CreateDomainExpression(d, Domain(d, "dom"), IntegerType(d)),
    )
    register_special_constructor(
        "statements.ddl_domain.DropDomainExpression",
        lambda d: ddl_domain.DropDomainExpression(d, Domain(d, "dom")),
    )
    register_special_constructor(
        "statements.ddl_domain.AlterDomainExpression",
        lambda d: ddl_domain.AlterDomainExpression(
            d, Domain(d, "dom"), [RenameDomainAction(d, "other")]
        ),
    )
    # A DOMAIN CHECK is DDL: it must render without bind parameters, so its
    # condition compares two columns rather than a column and a literal.
    register_special_constructor(
        "statements.ddl_domain.DomainCheckConstraint",
        lambda d: DomainCheckConstraint(d, _column_predicate(d), name="chk"),
    )
    register_special_constructor(
        "statements.ddl_domain.AddDomainCheckAction",
        lambda d: ddl_domain.AddDomainCheckAction(
            d, DomainCheckConstraint(d, _column_predicate(d), name="chk")
        ),
    )

    # -- routines, triggers, comments --------------------------------------
    register_special_constructor(
        "statements.ddl_function.CreateFunctionExpression",
        lambda d: ddl_function.CreateFunctionExpression(
            d, Function(d, "fn"), returns="integer", body="SELECT 1"
        ),
    )
    register_special_constructor(
        "statements.ddl_function.DropFunctionExpression",
        lambda d: ddl_function.DropFunctionExpression(d, Function(d, "fn")),
    )
    register_special_constructor(
        "statements.ddl_trigger.CreateTriggerExpression",
        lambda d: ddl_trigger.CreateTriggerExpression(
            d,
            trigger=Trigger(d, "trg"),
            table=_table(d),
            timing=TriggerTiming.BEFORE,
            events=[TriggerEvent.INSERT],
            function=Function(d, "fn"),
        ),
    )
    register_special_constructor(
        "statements.ddl_trigger.DropTriggerExpression",
        lambda d: ddl_trigger.DropTriggerExpression(d, trigger=Trigger(d, "trg")),
    )
    register_special_constructor(
        "statements.ddl_comment.CommentOnExpression",
        lambda d: ddl_comment.CommentOnExpression(d, "table", _table(d), comment="c"),
    )

    # -- views --------------------------------------------------------------
    register_special_constructor(
        "statements.ddl_view.DropViewExpression",
        lambda d: ddl_view.DropViewExpression(d, View(d, "v")),
    )
    register_special_constructor(
        "statements.ddl_view.CreateMaterializedViewExpression",
        lambda d: ddl_view.CreateMaterializedViewExpression(
            d, MaterializedView(d, "mv"), _one_column_query(d)
        ),
    )
    register_special_constructor(
        "statements.ddl_view.DropMaterializedViewExpression",
        lambda d: ddl_view.DropMaterializedViewExpression(d, MaterializedView(d, "mv")),
    )
    register_special_constructor(
        "statements.ddl_view.RefreshMaterializedViewExpression",
        lambda d: ddl_view.RefreshMaterializedViewExpression(
            d, MaterializedView(d, "mv")
        ),
    )

    # -- DML ----------------------------------------------------------------
    register_special_constructor(
        "statements.dml.InsertExpression",
        lambda d: dml.InsertExpression(
            d, into=_table(d), source=dml.ValuesSource(d, [[Literal(d, 1)]])
        ),
    )
    register_special_constructor(
        "statements.dml.DeleteExpression",
        lambda d: dml.DeleteExpression(d, _table(d)),
    )
    # The guess gives MERGE a bare string for its row source and no matched
    # action, and the action itself a sequence with no alias.
    register_special_constructor(
        "statements.dml.MergeExpression",
        lambda d: dml.MergeExpression(
            d,
            target_table=_table(d),
            source=NamedRelationRef(d, Table(d, "src")),
            on_condition=_column_predicate(d),
            when_matched=[
                MergeAction(
                    d,
                    MergeActionType.UPDATE,
                    {"a": Literal(d, 1)},
                    _column_predicate(d),
                    "matched",
                )
            ],
        ),
    )
    register_special_constructor(
        "statements.dml.MergeAction",
        lambda d: MergeAction(
            d,
            MergeActionType.UPDATE,
            {"a": Literal(d, 1)},
            _column_predicate(d),
            "matched",
        ),
    )

    # -- expressions that must not be empty ---------------------------------
    register_special_constructor(
        "advanced_functions.CaseExpression",
        lambda d: CaseExpression(
            d,
            cases=[(_column_predicate(d), Literal(d, 1))],
            else_result=Literal(d, 0),
        ),
    )
    register_special_constructor(
        "advanced_functions.WindowSpecification",
        lambda d: WindowSpecification(d, partition_by=["a"]),
    )
    register_special_constructor(
        "advanced_functions.WindowDefinition",
        lambda d: WindowDefinition(
            d, "w", WindowSpecification(d, partition_by=["a"])
        ),
    )
    register_special_constructor(
        "advanced_functions.WindowClause",
        lambda d: WindowClause(
            d, [WindowDefinition(d, "w", WindowSpecification(d, partition_by=["a"]))]
        ),
    )
    # An empty options dict is refused by the formatter, so a time-travel clause
    # needs an actual option to be worth building.
    register_special_constructor(
        "datetime.TemporalOptionsExpression",
        lambda d: TemporalOptionsExpression(d, {"as_of": "2020-01-01"}),
    )

    # -- types that need a member type or a member value --------------------
    register_special_constructor(
        "types.array.ArrayType", lambda d: ArrayType(d, VarCharType(d, 10))
    )
    # ``values`` is keyword-only behind a defaulted positional, so the guess
    # skips it and the type declares no members.
    register_special_constructor(
        "types.enum_.EnumType", lambda d: EnumType(d, values=["a", "b"])
    )

    # -- property graphs ----------------------------------------------------
    def node_table(d):
        return NodeTable(d, "people")

    def edge_table(d):
        return EdgeTableObject(d, "knows")

    def path_pattern(d):
        return graph_mod.PathPattern(d, graph_mod.GraphVertex(d, "n", node_table(d)))

    register_special_constructor(
        "graph.GraphVertex", lambda d: graph_mod.GraphVertex(d, "n", node_table(d))
    )
    register_special_constructor(
        "graph.GraphEdge", lambda d: graph_mod.GraphEdge(d, "e", edge_table(d))
    )
    register_special_constructor(
        "graph.VertexTable",
        lambda d: graph_mod.VertexTable(d, node_table(d), key_columns=["id"]),
    )
    register_special_constructor(
        "graph.EdgeTable",
        lambda d: graph_mod.EdgeTable(d, edge_table(d), ["src"], ["dst"]),
    )
    register_special_constructor(
        "graph.QuantifiedPath",
        lambda d: graph_mod.QuantifiedPath(
            d, graph_mod.GraphEdge(d, "e", edge_table(d)), min_repeats=1, max_repeats=3
        ),
    )
    register_special_constructor(
        "graph.MatchClause", lambda d: graph_mod.MatchClause(d, path_pattern(d))
    )
    register_special_constructor(
        "graph.ColumnsClause",
        lambda d: graph_mod.ColumnsClause(d, graph_mod.GraphColumn("n", "id")),
    )
    register_special_constructor(
        "graph.PathPattern", path_pattern
    )
    register_special_constructor(
        "graph.GraphTableExpression",
        lambda d: graph_mod.GraphTableExpression(
            d,
            graph=PropertyGraph(d, "g"),
            match=graph_mod.MatchClause(d, path_pattern(d)),
            columns=graph_mod.ColumnsClause(d, graph_mod.GraphColumn("n", "id")),
        ),
    )
    register_special_constructor(
        "graph.CreatePropertyGraphExpression",
        lambda d: graph_mod.CreatePropertyGraphExpression(
            d, graph=PropertyGraph(d, "g"), vertex_tables=[graph_mod.VertexTable(d, node_table(d))]
        ),
    )
    # The formatter accepts "add"/"drop" against "vertex tables"/"edge tables"/
    # "tables"; anything else is refused.
    register_special_constructor(
        "graph.AlterPropertyGraphExpression",
        lambda d: graph_mod.AlterPropertyGraphExpression(
            d,
            graph=PropertyGraph(d, "g"),
            action="add",
            target="vertex tables",
            vertex_tables=[graph_mod.VertexTable(d, node_table(d))],
        ),
    )
    register_special_constructor(
        "graph.DropPropertyGraphExpression",
        lambda d: graph_mod.DropPropertyGraphExpression(d, graph=PropertyGraph(d, "g")),
    )

    # -- SQL/XML ------------------------------------------------------------
    register_special_constructor(
        "xml.XMLAttributesExpression",
        lambda d: XMLAttributesExpression(d, [XMLAttribute(Literal(d, "v"), "a")]),
    )
    register_special_constructor(
        "xml.XMLForestExpression",
        lambda d: XMLForestExpression(d, [XMLForestItem(Literal(d, "v"), "a")]),
    )
    register_special_constructor(
        "xml.XMLConcatExpression",
        lambda d: XMLConcatExpression(d, [Literal(d, "a"), Literal(d, "b")]),
    )
    # An XMLTABLE needs a row source document and a COLUMNS list; with neither
    # it is not a statement at all. The document is an expression, and the
    # columns are typed projections rather than a plain name.
    register_special_constructor(
        "xml.XMLTableExpression",
        lambda d: XMLTableExpression(
            d, RawSQLExpression(d, "SELECT 1 AS a"), [XMLTableColumn("a", "int")]
        ),
    )

    # -- this backend's own four expressions --------------------------------
    # OPTIONS must be a non-empty mapping, which the introspective guess
    # supplies as ``{}``.
    register_special_constructor(
        "materialized_view.BigQueryAlterMaterializedViewSetOptionsExpression",
        lambda d: BigQueryAlterMaterializedViewSetOptionsExpression(
            d, MaterializedView(d, "mv"), {"enable_refresh": True}
        ),
    )


register_specials()


# ---------------------------------------------------------------------------
# Lists pinned so neither can grow or shrink silently
# ---------------------------------------------------------------------------

#: Classes the constructors above still cannot build. Pinned empty.
#:
#: This is not a ceiling -- there is no "at most N" here to absorb a new gap.
#: It is an equality: every class in the two packages builds, and the test that
#: checks it re-derives the set from ``make_instance`` and compares. A class
#: that stops building fails with its own name and the reason the constructor
#: gave; the fix is a registered constructor, never a skip.
UNCONSTRUCTIBLE = ()

#: The dispatch failure -- ``format_method`` named a method this dialect does not
#: define, so ``to_sql()`` never called anything. Core reported that as
#: ``AttributeError`` saying "has no formatting method 'format_x'"; it now reports
#: ``UnsupportedFeatureError`` saying "does not support the 'format_x' statement",
#: matching every other capability gap in the tree. Each fragment below is this
#: constant followed by the method name, because the message names the method and
#: that is what makes each entry a distinct pin: a class that started dispatching
#: somewhere else fails here.
#:
#: The type no longer separates "BigQuery never implemented this" from "BigQuery
#: knows the statement and refuses it", because both are
#: ``UnsupportedFeatureError``. The fragments do, by naming a missing method.
_NO_FORMATTER = "does not support the"

#: Classes that construct but cannot render, because this backend implements no
#: formatter for them. Each entry pins the exception type *and* the message
#: fragment, so a class that starts failing for a different reason fails here
#: instead of staying quietly green.
#:
#: All of these are capability gaps rather than defects in the sense that
#: BigQuery has no such feature: it has no sequences, triggers, stored
#: routines, databases, time travel, COMMENT ON, PIVOT, ILIKE, property graphs
#: or SQL/XML. What the table below records is that the dialect says so by
#: *omission* -- ``to_sql()`` cannot find ``format_...`` -- rather than through
#: the capability probe the rest of the tree uses. The gap is still declared by
#: omission; what changed is only the spelling. Core reports a missing formatter
#: through ``UnsupportedFeatureError`` now, so these entries no longer sit in a
#: category of their own by type -- which is the outcome this table wanted, since
#: one dialect reporting a gap two ways is what made it worth naming. They are
#: kept name by name because a dialect that grew real ``supports_*`` probes would
#: move them out of here, and each of those moves is a change someone has to make
#: on purpose.
LEGITIMATE_NON_RENDERS = {
    # ---- SQL/XML: BigQuery has no SQL/XML functions at all -----------------
    "rhosocial.activerecord.backend.expression.xml.XMLAggExpression": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_xmlagg_expression'",
    ),
    "rhosocial.activerecord.backend.expression.xml.XMLAttributesExpression": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_xmlattributes_expression'",
    ),
    "rhosocial.activerecord.backend.expression.xml.XMLCommentExpression": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_xmlcomment_expression'",
    ),
    "rhosocial.activerecord.backend.expression.xml.XMLConcatExpression": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_xmlconcat_expression'",
    ),
    "rhosocial.activerecord.backend.expression.xml.XMLElementExpression": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_xmlelement_expression'",
    ),
    "rhosocial.activerecord.backend.expression.xml.XMLExistsExpression": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_xmlexists_expression'",
    ),
    "rhosocial.activerecord.backend.expression.xml.XMLForestExpression": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_xmlforest_expression'",
    ),
    "rhosocial.activerecord.backend.expression.xml.XMLPIExpression": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_xmlpi_expression'",
    ),
    "rhosocial.activerecord.backend.expression.xml.XMLParseExpression": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_xmlparse_expression'",
    ),
    "rhosocial.activerecord.backend.expression.xml.XMLQueryExpression": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_xmlquery_expression'",
    ),
    "rhosocial.activerecord.backend.expression.xml.XMLRootExpression": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_xmlroot_expression'",
    ),
    "rhosocial.activerecord.backend.expression.xml.XMLSerializeExpression": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_xmlserialize_expression'",
    ),
    "rhosocial.activerecord.backend.expression.xml.XMLTableExpression": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_xmltable_expression'",
    ),
    # ---- SQL/PGQ property graphs: no CREATE PROPERTY GRAPH ------------------
    "rhosocial.activerecord.backend.expression.graph.CreatePropertyGraphExpression": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_create_property_graph_statement'",
    ),
    "rhosocial.activerecord.backend.expression.graph.AlterPropertyGraphExpression": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_alter_property_graph_statement'",
    ),
    "rhosocial.activerecord.backend.expression.graph.DropPropertyGraphExpression": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_drop_property_graph_statement'",
    ),
    "rhosocial.activerecord.backend.expression.graph.GraphTableExpression": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_graph_table_expression'",
    ),
    "rhosocial.activerecord.backend.expression.graph.GraphVertex": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_graph_vertex'",
    ),
    "rhosocial.activerecord.backend.expression.graph.GraphEdge": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_graph_edge'",
    ),
    "rhosocial.activerecord.backend.expression.graph.QuantifiedPath": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_quantified_path'",
    ),
    "rhosocial.activerecord.backend.expression.graph.PathPattern": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_path_pattern'",
    ),
    "rhosocial.activerecord.backend.expression.graph.MatchClause": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_match_clause'",
    ),
    "rhosocial.activerecord.backend.expression.graph.ColumnsClause": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_graph_columns_clause'",
    ),
    "rhosocial.activerecord.backend.expression.graph.VertexTable": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_vertex_table'",
    ),
    "rhosocial.activerecord.backend.expression.graph.EdgeTable": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_edge_table'",
    ),
    "rhosocial.activerecord.backend.expression.graph.TablePropertiesClause": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_table_properties_clause'",
    ),
    # ---- routines, triggers, sequences, databases: none exist --------------
    "rhosocial.activerecord.backend.expression.statements.ddl_function.CreateFunctionExpression": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_create_function_statement'",
    ),
    "rhosocial.activerecord.backend.expression.statements.ddl_function.DropFunctionExpression": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_drop_function_statement'",
    ),
    "rhosocial.activerecord.backend.expression.statements.ddl_trigger.CreateTriggerExpression": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_create_trigger_statement'",
    ),
    "rhosocial.activerecord.backend.expression.statements.ddl_trigger.DropTriggerExpression": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_drop_trigger_statement'",
    ),
    "rhosocial.activerecord.backend.expression.statements.ddl_sequence.CreateSequenceExpression": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_create_sequence_statement'",
    ),
    "rhosocial.activerecord.backend.expression.statements.ddl_sequence.AlterSequenceExpression": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_alter_sequence_statement'",
    ),
    "rhosocial.activerecord.backend.expression.statements.ddl_sequence.DropSequenceExpression": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_drop_sequence_statement'",
    ),
    "rhosocial.activerecord.backend.expression.statements.ddl_database.CreateDatabaseExpression": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_create_database_statement'",
    ),
    "rhosocial.activerecord.backend.expression.statements.ddl_database.AlterDatabaseExpression": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_alter_database_statement'",
    ),
    "rhosocial.activerecord.backend.expression.statements.ddl_database.DropDatabaseExpression": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_drop_database_statement'",
    ),
    # ---- COMMENT ON, PARTITION clause, PIVOT, ILIKE -------------------------
    "rhosocial.activerecord.backend.expression.statements.ddl_comment.CommentOnExpression": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_comment_statement'",
    ),
    "rhosocial.activerecord.backend.expression.statements.ddl_partition.PartitionClause": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_partition_clause'",
    ),
    "rhosocial.activerecord.backend.expression.pivot.PivotExpression": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_pivot_expression'",
    ),
    "rhosocial.activerecord.backend.expression.pivot.UnpivotExpression": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_unpivot_expression'",
    ),
    "rhosocial.activerecord.backend.expression.predicates.ILIKEExpression": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_ilike_expression'",
    ),
    # ---- time travel: a BigQuery FROM names no temporal version ------------
    "rhosocial.activerecord.backend.expression.datetime.TemporalOptionsExpression": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_temporal_options'",
    ),
    # ---- roots whose incompleteness is structural --------------------------
    # The root of the row-source tree. No concrete source renders through
    # `format_table_source`; each overrides `format_method`. Rendering the base
    # would mean inventing SQL for an object that carries nothing but an alias.
    "rhosocial.activerecord.backend.expression.sources.base.TableSource": (
        UnsupportedFeatureError, f"{_NO_FORMATTER} 'format_table_source'",
    ),
    # The root of the type tree. Every concrete type declares its own generic
    # `name`, which is what `format_data_type` dispatches on; the root declares
    # none, so there is nothing to dispatch. TypeError, not
    # UnsupportedFeatureError, because the class is incomplete rather than the
    # dialect being unable.
    "rhosocial.activerecord.backend.expression.types._base.DataType": (
        TypeError, "does not declare a valid generic type name",
    ),
    # ---- generic types this dialect has no formatter for -------------------
    # Each is a type name the dialect declines. BigQuery spells ARRAY, VARBINARY
    # and friends differently or not at all, so `format_data_type_<name>` is
    # absent and the dispatcher reports the gap. Declared capability rather than
    # omission would be the other answer; see the note above.
    "rhosocial.activerecord.backend.expression.types.array.ArrayType": (
        TypeError, "does not support the generic type 'array'",
    ),
    "rhosocial.activerecord.backend.expression.types.binary.BinaryType": (
        TypeError, "does not support the generic type 'binary'",
    ),
    "rhosocial.activerecord.backend.expression.types.binary.VarBinaryType": (
        TypeError, "does not support the generic type 'varbinary'",
    ),
    "rhosocial.activerecord.backend.expression.types.custom.CustomType": (
        TypeError, "does not support the generic type 'custom'",
    ),
    "rhosocial.activerecord.backend.expression.types.datetime_.IntervalType": (
        TypeError, "does not support the generic type 'interval'",
    ),
    "rhosocial.activerecord.backend.expression.types.enum_.EnumType": (
        TypeError, "does not support the generic type 'enum'",
    ),
    "rhosocial.activerecord.backend.expression.types.integer.IntType": (
        TypeError, "does not support the generic type 'int'",
    ),
    "rhosocial.activerecord.backend.expression.types.uuid_.UUIDType": (
        TypeError, "does not support the generic type 'uuid'",
    ),
}

#: The message a class with no ``format_method`` reports instead of SQL.
_NO_DISPATCH = "does not declare its dialect formatting method name"


#: Classes that construct and refuse to render by raising
#: ``NotImplementedError``. There are two reasons and they are not the same, so
#: each entry pins which message it expects.
#:
#: The first group declares no ``format_method`` at all -- a base that names an
#: expression category rather than a renderable thing, whose concrete
#: subclasses each declare their own. ``to_sql()`` reports that there is nothing
#: to dispatch to, which is true rather than a gap.
#:
#: The second is a statement the dialect implements no rendering for: the
#: formatter exists in core and raises to say so. BigQuery has no ``SET
#: TRANSACTION``. That is a capability this backend declines, which is why it
#: raises ``NotImplementedError`` rather than reporting the feature through
#: ``UnsupportedFeatureError`` -- see the note on
#: :data:`LEGITIMATE_NON_RENDERS` for why this is worth pinning by name rather
#: than widening what counts as acceptable.
LEGITIMATE_NOT_IMPLEMENTED = {
    # ---- bases that name an expression category, not a renderable thing ----
    "rhosocial.activerecord.backend.expression.bases.SQLPredicate": _NO_DISPATCH,
    "rhosocial.activerecord.backend.expression.bases.SQLValueExpression": _NO_DISPATCH,
    "rhosocial.activerecord.backend.expression.datetime._TemporalValueExpression": (
        _NO_DISPATCH
    ),
    "rhosocial.activerecord.backend.expression.introspection.IntrospectionExpression": (
        _NO_DISPATCH
    ),
    # The roots of the object tree. Each concrete object overrides
    # `format_method` with its own `format_*_object`; the base names only what
    # every catalogue object has in common.
    "rhosocial.activerecord.backend.expression.objects.base.SchemaObject": _NO_DISPATCH,
    "rhosocial.activerecord.backend.expression.objects.relation.RelationObject": (
        _NO_DISPATCH
    ),
    "rhosocial.activerecord.backend.expression.objects.routine.RoutineObject": (
        _NO_DISPATCH
    ),
    "rhosocial.activerecord.backend.expression.objects.type_.TypeObject": _NO_DISPATCH,
    # An ALTER TABLE action, an INSERT row source, and the two transaction
    # roots: each concrete member names its own formatter.
    "rhosocial.activerecord.backend.expression.statements.ddl_alter.AlterTableAction": (
        _NO_DISPATCH
    ),
    "rhosocial.activerecord.backend.expression.statements.dml.InsertDataSource": (
        _NO_DISPATCH
    ),
    "rhosocial.activerecord.backend.expression.transaction.TransactionExpression": (
        _NO_DISPATCH
    ),
    # ---- a statement this dialect declines to render ------------------------
    "rhosocial.activerecord.backend.expression.transaction.SetTransactionExpression": (
        "does not support SET TRANSACTION statement"
    ),
}


# ---------------------------------------------------------------------------
# The local assertion: classify the outcome instead of swallowing it
# ---------------------------------------------------------------------------

def classify_sql_roundtrip(fqn, instance, dialect):
    """Assert an expression's SQL survives the round-trip, or say precisely why not.

    The two pinned tables are consulted *before* the catch-all
    ``UnsupportedFeatureError`` branch, not after. Core reports a missing
    formatter as ``UnsupportedFeatureError``, the same type a dialect uses when it
    knows a statement and refuses it, so with an ``except`` clause for that type
    in front a pinned dispatch-failure entry would never be looked up: its type
    and message would go unasserted on this path and the "no-formatter" bucket
    would quietly go to zero. Checking the pins first keeps every entry
    load-bearing and keeps the branch name meaning what it says.

    Returns the name of the branch taken, so a caller can report the
    distribution. Raises ``AssertionError`` on a round-trip mismatch, on an
    unclassified exception, or when a class's outcome changed.
    """
    try:
        expected_sql, expected_params = instance.to_sql()
    except Exception as exc:
        if fqn in LEGITIMATE_NOT_IMPLEMENTED:
            assert isinstance(exc, NotImplementedError), (
                f"{fqn}: LEGITIMATE_NOT_IMPLEMENTED pins this class as a "
                f"NotImplementedError, but it raised {type(exc).__name__}: {exc}"
            )
            fragment = LEGITIMATE_NOT_IMPLEMENTED[fqn]
            assert fragment in str(exc), (
                f"{fqn}: expected the NotImplementedError to mention {fragment!r}, "
                f"got: {exc}"
            )
            return "not-implemented"
        if fqn in LEGITIMATE_NON_RENDERS:
            expected_type, fragment = LEGITIMATE_NON_RENDERS[fqn]
            assert type(exc) is expected_type, (
                f"{fqn}: LEGITIMATE_NON_RENDERS pins this class as raising "
                f"{expected_type.__name__}, but it raised {type(exc).__name__}: {exc}"
            )
            assert fragment in str(exc), (
                f"{fqn}: expected {expected_type.__name__} to say {fragment!r}, "
                f"but it said: {exc}"
            )
            return "no-formatter"
        if type(exc) is UnsupportedFeatureError:
            return "unsupported"
        raise AssertionError(
            f"{fqn}: to_sql() raised {type(exc).__name__}, which is neither a "
            f"render nor a classified non-render, and this is a defect.\n"
            f"  UnsupportedFeatureError means the dialect declares it cannot "
            f"do this and is always allowed.\n"
            f"  NotImplementedError means the class names an expression "
            f"category rather than a renderable thing.\n"
            f"  A class this dialect has no formatter for belongs in "
            f"LEGITIMATE_NON_RENDERS with its message fragment.\n"
            f"  Exception: {exc}"
        ) from exc

    for channel, decoded in (
        ("dict", deserialize(serialize(instance), dialect)),
        ("json", deserialize_json(serialize_json(instance), dialect)),
        ("xml", deserialize_xml(serialize_xml(instance), dialect)),
    ):
        decoded_sql, decoded_params = decoded.to_sql()
        assert decoded_sql == expected_sql, (
            f"{fqn}: {channel} round-trip changed the SQL.\n"
            f"  original: {expected_sql!r}\n"
            f"  {channel}: {decoded_sql!r}"
        )
        assert decoded_params == expected_params, (
            f"{fqn}: {channel} round-trip changed the bind parameters.\n"
            f"  original: {expected_params!r}\n"
            f"  {channel}: {decoded_params!r}"
        )
    return "rendered"


@pytest.fixture
def dialect():
    from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect

    return BigQueryDialect()


@pytest.fixture(params=sorted(REGISTERED), ids=sorted(REGISTERED))
def expr_case(request, dialect):
    fqn = request.param
    cls = REGISTERED[fqn]
    ExpressionRegistry._auto_register_builtins()
    # The four classes this backend defines are not core's built-ins, so the
    # registry cannot find them by name when it decodes a nested one.
    register_all({fqn: cls})
    instance, source = make_instance(cls, dialect)
    assert instance is not None, (
        f"{fqn} cannot be built by the constructors this module registers "
        f"({source}). Register a special constructor for it -- the matrix has "
        f"no skips, and a class that cannot be constructed cannot be asserted "
        f"on."
    )
    return fqn, instance


class TestExpressionRoundtripAll:
    """Every expression class this backend can be handed survives all three."""

    def test_to_sql_roundtrip_classified(self, expr_case, dialect):
        """A render must survive the round-trip; a non-render must be classified."""
        fqn, instance = expr_case
        classify_sql_roundtrip(fqn, instance, dialect)


class TestMatrixIntegrity:
    """Guards on the matrix and its lists, so neither can quietly change."""

    def test_nothing_is_skipped(self, dialect):
        """Every covered class builds. There is no skip, and no ceiling either.

        The set is re-derived from ``make_instance`` and compared with
        :data:`UNCONSTRUCTIBLE` both ways, so a class that stops building fails
        with its own name and a named class that starts building fails too.
        """
        ExpressionRegistry._auto_register_builtins()
        actual = tuple(
            sorted(
                fqn
                for fqn in REGISTERED
                if make_instance(REGISTERED[fqn], dialect)[0] is None
            )
        )
        assert actual == tuple(sorted(UNCONSTRUCTIBLE)), (
            "the set of expression classes the constructors cannot build "
            "changed.\n"
            f"  now unbuildable but not named: "
            f"{sorted(set(actual) - set(UNCONSTRUCTIBLE))}\n"
            f"  named but now built: "
            f"{sorted(set(UNCONSTRUCTIBLE) - set(actual))}\n"
            "Register a special constructor rather than naming a class here."
        )

    def test_pinned_entries_are_real_collected_classes(self):
        """Every pinned name was actually collected.

        A typo in either table would exempt nothing while still reading as a
        deliberate decision.
        """
        for table, entries in (
            ("LEGITIMATE_NON_RENDERS", LEGITIMATE_NON_RENDERS),
            ("LEGITIMATE_NOT_IMPLEMENTED", LEGITIMATE_NOT_IMPLEMENTED),
        ):
            unknown = set(entries) - set(REGISTERED)
            assert not unknown, (
                f"{table} names classes that were not collected: {sorted(unknown)}"
            )

    def test_pinned_non_renders_still_raise_what_they_claim(self, dialect):
        """Each pinned entry still fails the way the table says, for that reason.

        Without this an entry could sit in the table for a class that now renders
        perfectly well, and the matrix would be asserting nothing about it.
        """
        ExpressionRegistry._auto_register_builtins()
        for fqn, (expected_type, fragment) in LEGITIMATE_NON_RENDERS.items():
            instance, source = make_instance(REGISTERED[fqn], dialect)
            assert instance is not None, (
                f"{fqn} is pinned as a non-render but could not be constructed "
                f"({source})"
            )
            with pytest.raises(expected_type) as exc_info:
                instance.to_sql()
            assert fragment in str(exc_info.value), (
                f"{fqn}: expected the message to mention {fragment!r}, got: "
                f"{exc_info.value}"
            )

    def test_pinned_not_implementeds_still_raise_what_they_claim(self, dialect):
        """Each pinned entry still raises, and says the reason the table names."""
        ExpressionRegistry._auto_register_builtins()
        for fqn, fragment in LEGITIMATE_NOT_IMPLEMENTED.items():
            instance, source = make_instance(REGISTERED[fqn], dialect)
            assert instance is not None, (
                f"{fqn} is pinned as not-implemented but could not be constructed "
                f"({source})"
            )
            with pytest.raises(NotImplementedError) as exc_info:
                instance.to_sql()
            assert fragment in str(exc_info.value), (
                f"{fqn}: expected the message to mention {fragment!r}, got: "
                f"{exc_info.value}"
            )

    def test_matrix_covers_both_packages_completely(self):
        """The matrix covers every concrete class in both packages.

        Re-walked here rather than trusting the module-level collection, so a
        class that appeared after import is caught. The package walk is used
        rather than the registry because the registry also holds whatever
        backends other test modules happened to import.
        """
        ExpressionRegistry._auto_register_builtins()
        expected = set(_collect_matrix_classes())
        assert expected == set(REGISTERED), (
            "the set of classes the two packages define changed after "
            f"collection.\n  now defined but not covered: "
            f"{sorted(expected - set(REGISTERED))}\n"
            f"  covered but no longer defined: "
            f"{sorted(set(REGISTERED) - expected)}"
        )
        stray = [
            fqn
            for fqn in REGISTERED
            if not fqn.startswith(f"{CORE_EXPR_PKG}.")
            and not fqn.startswith(f"{BIGQUERY_EXPR_PKG}.")
        ]
        assert not stray, f"classes outside the two packages are in the matrix: {stray}"
        assert len(REGISTERED) > 200, (
            f"only {len(REGISTERED)} classes collected; the package walk may have "
            f"stopped early"
        )

    def test_core_classes_are_covered_not_just_this_backends_own(self):
        """The core package is in scope, which is the point of collecting two.

        A matrix over this backend's four expressions would pass no matter how
        many core classes this dialect refused or broke, and BigQuery's SQL
        surface is narrow enough that most of the core tree is untested without
        this.
        """
        ExpressionRegistry._auto_register_builtins()
        core = set(_collect_package(CORE_EXPR_PKG))
        bigquery = set(_collect_package(BIGQUERY_EXPR_PKG))
        assert core, "the core package walk found nothing"
        assert bigquery, "the bigquery package walk found nothing"
        assert set(REGISTERED) == core | bigquery

    def test_every_covered_class_is_registered_for_deserialization(self):
        """A class in the matrix can be found again when deserializing.

        Deserialization looks the class up by name, so a class the matrix
        renders but the registry cannot resolve would round-trip into the wrong
        thing or nothing at all.
        """
        ExpressionRegistry._auto_register_builtins()
        register_all(REGISTERED)
        unresolved = sorted(set(REGISTERED) - set(ExpressionRegistry._registry))
        assert not unresolved, (
            f"the matrix covers classes the registry cannot resolve: {unresolved}"
        )

    def test_coverage_report(self, dialect):
        """Surface the classification, so what the matrix covers stays visible.

        Every number below is counted by rendering each class once in this
        process and recording which branch it took -- not read off a constant,
        and not a ceiling the next class can hide inside.
        """
        ExpressionRegistry._auto_register_builtins()
        register_all(REGISTERED)
        counts = {}
        for fqn, cls in REGISTERED.items():
            instance, source = make_instance(cls, dialect)
            assert instance is not None, f"{fqn} could not be constructed ({source})"
            branch = classify_sql_roundtrip(fqn, instance, dialect)
            counts[branch] = counts.get(branch, 0) + 1
        assert sum(counts.values()) == len(REGISTERED)
        print(
            f"\nexpression matrix for BigQuery: {len(REGISTERED)} classes "
            f"(core + this backend)"
        )
        for branch in sorted(counts):
            print(f"  {branch}: {counts[branch]}")
        assert counts["rendered"], "no class renders; the matrix is not testing anything"
        assert len(counts) >= 4, (
            f"only {len(counts)} distinct outcomes; a narrow SQL surface usually "
            f"produces several, so something may have started swallowing errors"
        )