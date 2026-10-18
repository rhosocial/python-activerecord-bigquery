# tests/rhosocial/activerecord_bigquery_test/feature/backend/expression_roundtrip_harness.py
"""
Expression serialization round-trip / contract test helpers (BigQuery-local copy).

Vendored from the shared testsuite at
``python-activerecord-testsuite@4ef2551`` (formerly
``src/rhosocial/activerecord/testsuite/utils/expression.py``) when that suite's
``fix/column-constraint-gates`` branch dropped the module in ``e05edb0`` with
the direction "round-trip coverage moves to the owning repository": the suite
keeps the ActiveRecord-layer contracts and must not grow an opinion about
which expressions exist, so each backend now owns the harness its own matrix
runs on. Fix drift here deliberately; do not re-import it from the suite.

This module is the test-only home (NOT shipped as part of the core library's
runtime API) for constructing expression instances and asserting they survive
all three serializations.

After registering a class into the ExpressionRegistry, expression instances
must satisfy:

- ``get_params()`` reflects every ``__init__`` parameter
- A round-trip through the three encoding channels returns a structurally
  equivalent instance (``get_params()`` equal)
- When the chosen backend's dialect supports ``to_sql()``, the SQL keyword
  rendering is identical
"""

import collections.abc
import dataclasses
import inspect
import re
import typing
import warnings
from typing import Any, Callable, Dict, Type

from rhosocial.activerecord.backend.expression.bases import BaseExpression

# Annotation fragments that mean "this parameter names a relation object".
# Word boundaries matter: ``TableConstraint`` and ``AddTableConstraint`` are
# constraint actions, not relations, and a substring test would hand them a
# Table. ``SchemaObject`` is the base every catalogue object shares, so an
# annotation naming it wants an object too.
_MENTIONS_RELATION = re.compile(
    r"\b(Table|View|MaterializedView|Index|Sequence|Type|Domain|Function|Trigger"
    r"|Schema|Database|RelationObject|SchemaObject|NodeTable|EdgeTable)\b"
)

# An INSERT's data source. It is an expression now, so it needs a real one --
# the generic placeholder cannot invent the rows a VALUES list is made of.
_MENTIONS_INSERT_SOURCE = re.compile(r"\bInsertDataSource\b")


def _empty_container_for(annotation: Any, dialect: Any):
    """Return an empty container for a parameterised alias, else None.

    A parameterised alias like ``List[str]`` or ``Dict[str, BaseExpression]``
    says what the *elements* are, never the container itself, so there is no
    catalogue object to hand back -- only an empty container. Deciding this
    before the relation-name test is what keeps ``typing.List[str]`` from being
    read as a ``Table``: ``typing.get_origin`` on it gives ``list``, but the
    relation test only ever saw the alias' own name, and ``List[str]`` matches
    ``Sequence``/``Table``-family fragments well enough to be mistaken for one.

    Returns ``None`` when ``annotation`` is not a parameterised container, which
    is the caller's signal to keep reading.
    """
    origin = typing.get_origin(annotation)
    if origin is None:
        return None
    if origin in (list, tuple, set, frozenset):
        return []
    if origin is dict:
        return {}
    # ``Sequence[str]`` and friends resolve to the collections.abc ABC rather
    # than to ``list``, so match on the abstract base instead of the concrete
    # one the annotation happens to name.
    if isinstance(origin, type) and issubclass(origin, (collections.abc.Sequence, collections.abc.Set)):
        return []
    if isinstance(origin, type) and issubclass(origin, collections.abc.Mapping):
        return {}
    return None


def _mentions_expression_class(annotation: Any, raw: Any) -> bool:
    """Whether the annotation names an expression node, whatever it is called.

    This used to be a substring test for ``"Expression"``, which is a coupling
    to the class *names*: renaming ``QueryExpression`` to ``QueryStatement``
    (规范 4.9: a statement is a statement) silently stopped matching, the
    parameter fell through to the ``"x"`` fallback, and the failure surfaced
    later as ``'str' object has no attribute 'to_sql'`` from inside a
    formatter. The structural question -- does this annotation name a
    ``BaseExpression`` subclass? -- does not care what the class is called.
    """
    from rhosocial.activerecord.backend.expression.bases import BaseExpression

    candidates = [raw]
    if typing.get_origin(annotation) is not None:
        candidates.extend(typing.get_args(annotation))
    for candidate in candidates:
        if isinstance(candidate, type) and issubclass(candidate, BaseExpression):
            return True
    return False


def _is_predicate_class(annotation: Any, raw: Any) -> bool:
    """Whether the annotation names a predicate node, whatever it is called.

    Same structural question as :func:`_mentions_expression_class` answers for
    expressions, asked of the predicate family: a rename inside the family must
    not change what this heuristic builds either.
    """
    from rhosocial.activerecord.backend.expression.bases import SQLPredicate

    for candidate in (raw, annotation):
        if isinstance(candidate, type) and issubclass(candidate, SQLPredicate):
            return True
    return False


def _placeholder_for(param: inspect.Parameter, dialect: Any = None):
    """Return a heuristic construction value for a required parameter."""
    annotation = param.annotation
    if annotation is not inspect.Parameter.empty:
        origin = typing.get_origin(annotation)
        raw = annotation if origin is None else origin
        if isinstance(annotation, str):
            text = annotation
        else:
            text = getattr(raw, "__name__", "")
        container = _empty_container_for(annotation, dialect)
        if container is not None:
            return container
        if raw in (list, tuple, set):
            return []
        if raw is dict:
            return {}
        if _MENTIONS_RELATION.search(text):
            return _relation(dialect, text)
        if _MENTIONS_INSERT_SOURCE.search(text):
            return _values_source(dialect)
        if raw is str or "str" in text:
            return "x"
        # A typed value expression wraps the call it renders, so the parameter
        # wants a FunctionCall and not a bare name. This must be tested before
        # the str branch above: "FunctionCall" contains no "str", but the
        # fallback below returns "x" for it, which the wrapper then calls
        # to_sql() on.
        if "FunctionCall" in text:
            return _function_call(dialect)
        if "DataType" in text or "Type" in text.split(".")[-1:]:
            from rhosocial.activerecord.backend.expression.types import IntegerType

            return IntegerType(dialect)
        if raw is int:
            return 1
        if raw is float:
            return 1.0
        if raw is bool:
            return True
        # A predicate slot wants a predicate, not a value. SQLPredicate is a
        # BaseExpression subclass like the values are, so the structural
        # expression branch below hands it a Literal -- and the constructors
        # that type a parameter as a predicate refuse a Literal on their
        # isinstance check (core's DomainCheckConstraint.condition is the one
        # in the matrix today). Asked structurally when the annotation
        # resolves; the name test beside it covers forward references.
        if (not isinstance(annotation, str) and _is_predicate_class(annotation, raw)) or (
            "Predicate" in text
        ):
            return _comparison(dialect)
        # Asked structurally when the annotation resolves: what a class is
        # called says nothing about what it is, and a rename must not change
        # what this heuristic builds. The substring tests beside it remain for
        # forward references, which introspection cannot resolve -- and they
        # must list every name the library might grow, which is exactly why
        # the structural test is the one that leads.
        if (
            "Expression" in text
            or "Subquery" in text
            or "Statement" in text
            or (not isinstance(annotation, str) and _mentions_expression_class(annotation, raw))
        ):
            return _literal(dialect)

    name = param.name
    if name in ("value",):
        return 1
    if name in ("values", "columns", "args", "params", "predicates", "expressions"):
        return []
    if name in ("left", "right") or "predicate" in name or "condition" in name:
        return _comparison(dialect)
    if "expression" in name or name in ("expr", "operand", "subquery", "query"):
        return _literal(dialect)
    return "x"


def _literal(dialect):
    from rhosocial.activerecord.backend.expression.core import Literal

    return Literal(dialect, 1)


def _function_call(dialect):
    """A niladic function call, for a parameter that wraps one.

    The typed value expressions (``BooleanValue`` and its siblings)
    hold a ``call`` and render it through ``to_sql()``. Handing them a string
    builds an instance that cannot render, and the failure surfaces as
    ``'str' object has no attribute 'to_sql'`` from inside the wrapper rather
    than as a construction problem.
    """
    from rhosocial.activerecord.backend.expression.core import FunctionCall

    return FunctionCall(dialect, "FUNC", niladic=True)


def _comparison(dialect):
    from rhosocial.activerecord.backend.expression.core import Column
    from rhosocial.activerecord.backend.expression.predicates import ComparisonPredicate

    return ComparisonPredicate(dialect, "=", Column(dialect, "a"), _literal(dialect))


def _try_construct(cls, dialect):
    """Construct an instance of cls with heuristic arguments; None on failure."""
    sig = inspect.signature(cls.__init__)
    # DataType-family declares dialect as an optional trailing keyword.
    has_dialect = "dialect" in sig.parameters
    first_param = next((p for p in sig.parameters if p != "self"), None)
    dialect_as_kw = first_param != "dialect"
    args = []
    kwargs = {}
    skipped_defaulted_positional = False
    for pname, param in sig.parameters.items():
        if pname in ("self", "dialect"):
            continue
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            continue
        if param.kind == inspect.Parameter.VAR_POSITIONAL:
            if not skipped_defaulted_positional:
                args.append(_literal(dialect))
            continue
        if param.default is not inspect.Parameter.empty:
            if param.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD:
                skipped_defaulted_positional = True
            continue
        placeholder = _placeholder_for(param, dialect)
        # placeholder None → default case; real value provided otherwise
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            kwargs[pname] = placeholder
        else:
            args.append(placeholder)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            if not has_dialect:
                return cls(*args, **kwargs)
            if dialect_as_kw:
                return cls(*args, dialect=dialect, **kwargs)
            return cls(dialect, *args, **kwargs)
    except Exception:
        return None


def special_constructors():
    """Explicit constructors for classes whose ``__init__`` rejects heuristic
    placeholder values. Keyed by a suffix that matches the class's full
    module.ClassName. Registered by name only — this is a static registry and
    backends may register their own entries for backend-specific expressions.

    **A key that matches no class is dead code, and nothing says so.**
    :func:`make_instance` dispatches on ``full_name.endswith(key)``, so
    renaming a class turns its entry into a literal that matches nothing: the
    class then falls through to :func:`_try_construct`, the source is reported
    as ``"heuristic"`` instead of ``"special"``, and if the heuristic also
    fails the class is silently reported as unconstructible rather than as
    mis-registered. This is how ``"advanced_functions.JSONExpression"`` came to
    match nothing at all once core split that one class into
    ``JSONDocumentValue`` and ``JSONTextValue``.

    The failure is one-directional, which is what makes it dangerous: renaming
    the key once breaks the match silently, and a *single* key covering both
    new names is not expressible, because ``endswith`` compares a suffix. A
    class that was split needs one entry per resulting class.

    :func:`register_special_constructor` writes to the module-level
    ``_SPECIAL_REGISTRY``, which is what :func:`make_instance` reads. Note that
    this function rebuilds its dict on every call, so a registration made
    elsewhere is **not** visible to a caller that invokes
    ``special_constructors()`` directly — core's expression-contract test does
    exactly that, and therefore sees only the literals below.
    """
    return {
        "statements.ddl_table.ColumnDefinition": _column_definition,
        "statements.ddl_table.ColumnConstraint": _column_constraint,
        "statements.ddl_table.ForeignKeyConstraint": _foreign_key_constraint,
        "statements.ddl_table.TableConstraint": _table_constraint,
        "statements.ddl_table.ColumnForeignKeyConstraint": _column_fk_constraint,
        "statements.ddl_table.TableForeignKeyConstraint": _table_fk_constraint,
        "statements.ddl_table.TablePrimaryKeyConstraint": _table_primary_key,
        "statements.ddl_table.TableUniqueConstraint": _table_unique,
        "statements.dml.ValuesSource": _values_source,
        "statements.ddl_sequence.CreateSequenceStatement": _create_sequence_expr,
        "statements.ddl_sequence.DropSequenceStatement": _drop_sequence_expr,
        "statements.ddl_sequence.AlterSequenceStatement": _alter_sequence_expr,
        "statements.ddl_type.CreateTypeStatement": _create_type_expr,
        "statements.ddl_type.AlterTypeStatement": _alter_type_expr,
        "statements.ddl_type.DropTypeStatement": _drop_type_expr,
        "statements.ddl_domain.CreateDomainStatement": _create_domain_expr,
        "statements.ddl_domain.AlterDomainStatement": _alter_domain_expr,
        "statements.ddl_domain.DropDomainStatement": _drop_domain_expr,
        "statements.ddl_function.CreateFunctionStatement": _create_function_expr,
        "statements.ddl_function.DropFunctionStatement": _drop_function_expr,
        "statements.ddl_schema.CreateSchemaStatement": _create_schema_expr,
        "statements.ddl_schema.DropSchemaStatement": _drop_schema_expr,
        "statements.ddl_database.CreateDatabaseStatement": _create_database_expr,
        "statements.ddl_database.DropDatabaseStatement": _drop_database_expr,
        # core splits what was one JSONExpression into a document and a text
        # class, so one key cannot cover both: endswith matches a suffix.
        "advanced_functions.JSONDocumentValue": _json_document_expr,
        "advanced_functions.JSONTextValue": _json_text_expr,
        "query_parts.JoinClause": _join_expr,
        "statements.ddl_partition.PartitionClause": _partition_clause,
        "statements.dml.OnConflictClause": _on_conflict,
        "statements.dml.UpdateStatement": _update_expr,
        "statements.dml.InsertStatement": _insert_expr,
        "statements.dml.DeleteStatement": _delete_expr,
        "statements.ddl_alter.AlterTableStatement": _alter_table_expr,
        "types.array.ArrayType": _array_type,
        "statements.ddl_view.CreateViewStatement": _create_view_expr,
        "graph.GraphVertex": _graph_vertex,
        "graph.GraphEdge": _graph_edge,
        "graph.VertexTable": _node_table,
        "graph.EdgeTable": _edge_table,
        "graph.GraphTableExpression": _graph_table_expr,
        "graph.CreatePropertyGraphStatement": _create_property_graph_expr,
        "graph.DropPropertyGraphStatement": _drop_property_graph_expr,
        "graph.AlterPropertyGraphStatement": _alter_property_graph_expr,
        "datetime.ExtractExpression": _extract_expr,
        "datetime.DatePartExpression": _datepart_expr,
        "datetime.DateTruncExpression": _datetrunc_expr,
        "datetime.IntervalExpression": _interval_expr,
        "datetime.DateTimeDiffExpression": _datetime_diff_expr,
        "datetime.DateTimeSubtractExpression": _datetime_sub_expr,
        "datetime.DateTimeAddExpression": _datetime_add_expr,
    }


def _column_definition(dialect):
    from rhosocial.activerecord.backend.expression.statements import ColumnDefinition
    from rhosocial.activerecord.backend.expression.types import IntegerType

    return ColumnDefinition(dialect, "col", IntegerType(dialect))


# ---------------------------------------------------------------- constraint nodes
# A constraint is a clause plus the branch that says which kind it is, so the
# two levels need a branch each: the clause cannot be built without saying what
# it constrains, and the branches whose payload is a relation or a column list
# need one the heuristic guess has no way to supply.


def _column_constraint(dialect):
    from rhosocial.activerecord.backend.expression.statements import (
        ColumnConstraint,
        ColumnNotNullConstraint,
    )

    return ColumnConstraint(dialect, branch=ColumnNotNullConstraint(dialect))


def _foreign_key_constraint(dialect):
    """The construction sugar over a table-level FOREIGN KEY branch.

    Same reason as the branch itself: what it points at has to be a real
    ``Table``, which a guessed placeholder cannot be.
    """
    from rhosocial.activerecord.backend.expression.objects import Table
    from rhosocial.activerecord.backend.expression.statements import (
        ForeignKeyConstraint,
    )

    return ForeignKeyConstraint(
        dialect,
        columns=["col"],
        foreign_key_table=Table(dialect, "parent"),
        foreign_key_columns=["id"],
    )


def _table_constraint(dialect):
    from rhosocial.activerecord.backend.expression.statements import (
        TableConstraint,
        TableUniqueConstraint,
    )

    return TableConstraint(dialect, branch=TableUniqueConstraint(dialect, ["col"]))


def _column_fk_constraint(dialect):
    from rhosocial.activerecord.backend.expression.objects import Table
    from rhosocial.activerecord.backend.expression.statements import (
        ColumnForeignKeyConstraint,
    )

    return ColumnForeignKeyConstraint(dialect, (Table(dialect, "parent"), ["id"]))


def _table_fk_constraint(dialect):
    from rhosocial.activerecord.backend.expression.objects import Table
    from rhosocial.activerecord.backend.expression.statements import (
        TableForeignKeyConstraint,
    )

    return TableForeignKeyConstraint(dialect, ["col"], (Table(dialect, "parent"), ["id"]))


def _table_primary_key(dialect):
    from rhosocial.activerecord.backend.expression.statements import (
        TablePrimaryKeyConstraint,
    )

    return TablePrimaryKeyConstraint(dialect, ["col"])


def _table_unique(dialect):
    from rhosocial.activerecord.backend.expression.statements import TableUniqueConstraint

    return TableUniqueConstraint(dialect, ["col"])


def _json_document_expr(dialect):
    """``->``: a JSON *document*, reached by path.

    ``path`` and ``operation`` keep their defaults, so this renders exactly
    what the pre-split single ``JSONExpression`` factory rendered.
    """
    from rhosocial.activerecord.backend.expression.advanced_functions import (
        JSONDocumentValue,
    )
    from rhosocial.activerecord.backend.expression.core import Literal

    return JSONDocumentValue(dialect, Literal(dialect, '{"a": 1}'), path="$.a")


def _json_text_expr(dialect):
    """``->>``: the *text* of a JSON path.

    ``JSONTextValue`` declares no ``__init__`` of its own, so it inherits
    the document class's -- including ``operation="->"``. The default is
    therefore inherited too, and this factory has to say ``->>`` explicitly.
    Leaving it off would hand the contract test a ``JSONTextValue`` whose
    ``operation`` says ``->``, which is the one thing the class exists to
    distinguish.

    The rendered SQL is unaffected either way: the formatters branch on
    ``expr.operation``, not on the class, and dispatch is on ``format_method``,
    which both classes share.
    """
    from rhosocial.activerecord.backend.expression.advanced_functions import (
        JSONTextValue,
    )
    from rhosocial.activerecord.backend.expression.core import Literal

    return JSONTextValue(
        dialect, Literal(dialect, '{"a": 1}'), path="$.a", operation="->>"
    )


def _values_source(dialect):
    """A ``VALUES`` clause with one row of one column.

    ``ValuesSource`` rejects an empty ``values_list``, and the heuristic filler
    returns ``[]`` for any ``list``-origin annotation -- which is why this class
    needs an explicit constructor at all. ``[]`` would also be the wrong thing
    to satisfy it with: a ``VALUES`` clause with no rows is not an INSERT
    source, and the zero-row spelling already has its own class,
    ``DefaultValuesSource``, sitting next to this one.
    """
    from rhosocial.activerecord.backend.expression.core import Literal
    from rhosocial.activerecord.backend.expression.statements.dml import ValuesSource

    return ValuesSource(dialect, [[Literal(dialect, 1)]])


def _array_type(dialect):
    """An array of integers -- one dimension.

    ``ArrayType`` requires an ``element_type`` and raises ``TypeError`` without
    one ("an array with no element type is not a type"). Two things stop the
    heuristic filler from reaching that requirement, and neither is fixable by
    giving the parameter a default:

    * the filler skips defaulted parameters, so it calls ``ArrayType(dialect)``
      with nothing else; and
    * ``dialect`` must come first and ``element_type`` must follow it, so a
      *required* ``element_type`` after a defaulted ``dialect`` is not
      expressible in Python at all.

    Making the parameter required therefore cannot help, and a default of
    ``None`` is already what core declares. So the element type has to be
    supplied here, as a concrete ``DataType``.
    """
    from rhosocial.activerecord.backend.expression.types import (
        ArrayType,
        IntegerType,
    )

    return ArrayType(dialect, element_type=IntegerType(dialect))


def _sequence(dialect):
    """A sequence, by kind."""
    from rhosocial.activerecord.backend.expression.objects import Sequence

    return Sequence(dialect, "s")


def _create_sequence_expr(dialect):
    from rhosocial.activerecord.backend.expression.statements.ddl_sequence import (
        CreateSequenceStatement,
    )

    return CreateSequenceStatement(dialect, _sequence(dialect))


def _drop_sequence_expr(dialect):
    from rhosocial.activerecord.backend.expression.statements.ddl_sequence import (
        DropSequenceStatement,
    )

    return DropSequenceStatement(dialect, _sequence(dialect))


def _alter_sequence_expr(dialect):
    from rhosocial.activerecord.backend.expression.statements.ddl_sequence import (
        AlterSequenceStatement,
    )

    return AlterSequenceStatement(dialect, _sequence(dialect))


def _create_type_expr(dialect):
    from rhosocial.activerecord.backend.impl.dummy.expression import _DummyTypeDefinition
    from rhosocial.activerecord.backend.expression.objects import Type
    from rhosocial.activerecord.backend.expression.statements.ddl_type import (
        CreateTypeStatement,
    )
    from rhosocial.activerecord.backend.expression.types import IntegerType

    return CreateTypeStatement(
        dialect, Type(dialect, "t"), _DummyTypeDefinition(dialect, IntegerType(dialect))
    )


def _alter_type_expr(dialect):
    from rhosocial.activerecord.backend.impl.dummy.expression import _DummyTypeAlterAction
    from rhosocial.activerecord.backend.expression.objects import Type
    from rhosocial.activerecord.backend.expression.statements.ddl_type import (
        AlterTypeStatement,
    )

    return AlterTypeStatement(
        dialect, Type(dialect, "t"), [_DummyTypeAlterAction(dialect, "t2")]
    )


def _drop_type_expr(dialect):
    from rhosocial.activerecord.backend.expression.objects import Type
    from rhosocial.activerecord.backend.expression.statements.ddl_type import (
        DropTypeStatement,
    )

    return DropTypeStatement(dialect, Type(dialect, "t"))


def _create_domain_expr(dialect):
    from rhosocial.activerecord.backend.expression.objects import Domain
    from rhosocial.activerecord.backend.expression.statements.ddl_domain import (
        CreateDomainStatement,
    )
    from rhosocial.activerecord.backend.expression.types import IntegerType

    return CreateDomainStatement(dialect, Domain(dialect, "d"), IntegerType(dialect))


def _alter_domain_expr(dialect):
    from rhosocial.activerecord.backend.expression.core import Literal
    from rhosocial.activerecord.backend.expression.objects import Domain
    from rhosocial.activerecord.backend.expression.statements.ddl_domain import (
        AlterDomainStatement,
        SetDomainDefaultAction,
    )

    return AlterDomainStatement(
        dialect, Domain(dialect, "d"), [SetDomainDefaultAction(dialect, Literal(dialect, 1))]
    )


def _drop_domain_expr(dialect):
    from rhosocial.activerecord.backend.expression.objects import Domain
    from rhosocial.activerecord.backend.expression.statements.ddl_domain import (
        DropDomainStatement,
    )

    return DropDomainStatement(dialect, Domain(dialect, "d"))


def _create_function_expr(dialect):
    from rhosocial.activerecord.backend.expression.objects import Function
    from rhosocial.activerecord.backend.expression.statements.ddl_function import (
        CreateFunctionStatement,
    )

    return CreateFunctionStatement(dialect, Function(dialect, "f"))


def _drop_function_expr(dialect):
    from rhosocial.activerecord.backend.expression.objects import Function
    from rhosocial.activerecord.backend.expression.statements.ddl_function import (
        DropFunctionStatement,
    )

    return DropFunctionStatement(dialect, Function(dialect, "f"))


def _create_schema_expr(dialect):
    from rhosocial.activerecord.backend.expression.objects import Schema
    from rhosocial.activerecord.backend.expression.statements.ddl_schema import (
        CreateSchemaStatement,
    )

    return CreateSchemaStatement(dialect, Schema(dialect, "s"))


def _drop_schema_expr(dialect):
    from rhosocial.activerecord.backend.expression.objects import Schema
    from rhosocial.activerecord.backend.expression.statements.ddl_schema import (
        DropSchemaStatement,
    )

    return DropSchemaStatement(dialect, Schema(dialect, "s"))


def _create_database_expr(dialect):
    from rhosocial.activerecord.backend.expression.objects import Database
    from rhosocial.activerecord.backend.expression.statements.ddl_database import (
        CreateDatabaseStatement,
    )

    return CreateDatabaseStatement(dialect, Database(dialect, "d"))


def _drop_database_expr(dialect):
    from rhosocial.activerecord.backend.expression.objects import Database
    from rhosocial.activerecord.backend.expression.statements.ddl_database import (
        DropDatabaseStatement,
    )

    return DropDatabaseStatement(dialect, Database(dialect, "d"))


def _node_table(dialect):
    """A graph vertex table."""
    from rhosocial.activerecord.backend.expression.graph import VertexTable
    from rhosocial.activerecord.backend.expression.objects import NodeTable

    return VertexTable(dialect, NodeTable(dialect, "n"))


def _edge_table(dialect):
    """A graph edge table declaration."""
    from rhosocial.activerecord.backend.expression.graph import EdgeTable
    from rhosocial.activerecord.backend.expression.objects import (
        EdgeTable as EdgeTableObject,
    )

    return EdgeTable(dialect, EdgeTableObject(dialect, "e"), ["s"], ["d"])


def _graph_vertex(dialect):
    from rhosocial.activerecord.backend.expression.graph import GraphVertex
    from rhosocial.activerecord.backend.expression.objects import NodeTable

    return GraphVertex(dialect, "v", NodeTable(dialect, "n"))


def _graph_edge(dialect):
    from rhosocial.activerecord.backend.expression.graph import (
        GraphEdge,
        GraphEdgeDirection,
    )
    from rhosocial.activerecord.backend.expression.objects import (
        EdgeTable as EdgeTableObject,
    )

    return GraphEdge(dialect, "e", EdgeTableObject(dialect, "e"),
                     GraphEdgeDirection.RIGHT)


def _graph_table_expr(dialect):
    from rhosocial.activerecord.backend.expression.graph import (
        ColumnsClause,
        GraphColumn,
        GraphTableExpression,
        MatchClause,
    )
    from rhosocial.activerecord.backend.expression.objects import PropertyGraph

    return GraphTableExpression(
        dialect,
        PropertyGraph(dialect, "g"),
        MatchClause(
            dialect,
            _graph_vertex(dialect),
            _graph_edge(dialect),
            _graph_vertex(dialect),
        ),
        ColumnsClause(dialect, GraphColumn("v", "name")),
    )


def _create_property_graph_expr(dialect):
    from rhosocial.activerecord.backend.expression.graph import (
        CreatePropertyGraphStatement,
    )
    from rhosocial.activerecord.backend.expression.objects import PropertyGraph

    return CreatePropertyGraphStatement(
        dialect, PropertyGraph(dialect, "g"), [_node_table(dialect)]
    )


def _drop_property_graph_expr(dialect):
    from rhosocial.activerecord.backend.expression.graph import (
        DropPropertyGraphStatement,
    )
    from rhosocial.activerecord.backend.expression.objects import PropertyGraph

    return DropPropertyGraphStatement(dialect, PropertyGraph(dialect, "g"))


def _alter_property_graph_expr(dialect):
    from rhosocial.activerecord.backend.expression.graph import (
        AlterPropertyGraphStatement,
    )
    from rhosocial.activerecord.backend.expression.objects import PropertyGraph

    return AlterPropertyGraphStatement(
        dialect,
        PropertyGraph(dialect, "g"),
        "ADD",
        "VERTEX TABLES",
        vertex_tables=[_node_table(dialect)],
    )


def _table(dialect, name="t"):
    """The catalogue object a statement acts on."""
    from rhosocial.activerecord.backend.expression.objects import Table

    return Table(dialect, name)


def _relation(dialect, annotation):
    """The object an annotation asks for, chosen by the kind it names.

    The kind is not decoration: CREATE VIEW will not accept a Table, and DROP
    MATERIALIZED VIEW will not accept a View. Longest name first, because
    ``MaterializedView`` contains ``View`` and the more specific kind is the one
    an annotation naming it means.
    """
    import rhosocial.activerecord.backend.expression.objects as objects

    for kind in ("MaterializedView", "ForeignTable", "NodeTable", "EdgeTable",
                 "Sequence", "Index", "View", "Table", "Type", "Domain",
                 "Function", "Trigger", "Schema", "Database"):
        if re.search(rf"\b{kind}\b", annotation):
            return getattr(objects, kind)(dialect, "t")
    return _table(dialect)


def _source(dialect, name="t"):
    """A row source over the object a statement acts on.

    A statement that *names* a relation takes the object; a statement that
    *reads rows from* one takes a source over it. The two are not
    interchangeable, so they get their own helper rather than one that guesses
    which position it is filling.
    """
    from rhosocial.activerecord.backend.expression.objects import Table
    from rhosocial.activerecord.backend.expression.sources import NamedRelationRef

    return NamedRelationRef(dialect, Table(dialect, name))


def _join_expr(dialect):
    from rhosocial.activerecord.backend.expression.query_parts import JoinClause
    from rhosocial.activerecord.backend.expression.predicates import ComparisonPredicate
    from rhosocial.activerecord.backend.expression.core import Column

    return JoinClause(
        dialect,
        left_table=_source(dialect, "a"),
        right_table=_source(dialect, "b"),
        condition=ComparisonPredicate(dialect, "=", Column(dialect, "a"), Column(dialect, "b")),
    )


def _partition_clause(dialect):
    from rhosocial.activerecord.backend.expression.core import Column
    from rhosocial.activerecord.backend.expression.statements.ddl_partition import (
        PartitionClause,
        PartitionStrategy,
    )

    return PartitionClause(dialect, method=PartitionStrategy.RANGE, keys=[Column(dialect, "created_at")])


def _on_conflict(dialect):
    from rhosocial.activerecord.backend.expression.statements.dml import OnConflictClause

    return OnConflictClause(dialect, do_nothing=True, conflict_target=["id"])


def _insert_expr(dialect):
    from rhosocial.activerecord.backend.expression.core import Literal
    from rhosocial.activerecord.backend.expression.statements.dml import (
        InsertStatement,
        ValuesSource,
    )

    return InsertStatement(dialect, into=_table(dialect), source=ValuesSource(dialect, [[Literal(dialect, 1)]]))


def _delete_expr(dialect):
    from rhosocial.activerecord.backend.expression.statements.dml import DeleteStatement

    return DeleteStatement(dialect, tables=_table(dialect))


def _update_expr(dialect):
    from rhosocial.activerecord.backend.expression.core import Literal
    from rhosocial.activerecord.backend.expression.statements.dml import UpdateStatement

    return UpdateStatement(dialect, table=_table(dialect), assignments={"a": Literal(dialect, 1)})


def _alter_table_expr(dialect):
    from rhosocial.activerecord.backend.expression.statements.ddl_alter import (
        AddColumn,
        AlterTableStatement,
        DropColumn,
    )

    column = _column_definition(dialect)
    return AlterTableStatement(
        dialect,
        table=_table(dialect, "t"),
        actions=[DropColumn(dialect, "a"), AddColumn(dialect, column=column)],
    )


def _create_view_expr(dialect):
    from rhosocial.activerecord.backend.expression.core import Column
    from rhosocial.activerecord.backend.expression.objects import View
    from rhosocial.activerecord.backend.expression.statements.ddl_view import CreateViewStatement
    from rhosocial.activerecord.backend.expression.statements.dql import QueryStatement

    query = QueryStatement(dialect, select=[Column(dialect, "id")], from_=_source(dialect, "t"))
    return CreateViewStatement(dialect, view=View(dialect, "v"), query=query)


def _extract_expr(dialect):
    from rhosocial.activerecord.backend.expression.core import Column
    from rhosocial.activerecord.backend.expression.datetime import ExtractExpression

    return ExtractExpression(dialect, "YEAR", Column(dialect, "created_at"))


def _datepart_expr(dialect):
    from rhosocial.activerecord.backend.expression.core import Column
    from rhosocial.activerecord.backend.expression.datetime import DatePartExpression

    return DatePartExpression(dialect, "YEAR", Column(dialect, "created_at"))


def _datetrunc_expr(dialect):
    from rhosocial.activerecord.backend.expression.core import Column
    from rhosocial.activerecord.backend.expression.datetime import DateTruncExpression

    return DateTruncExpression(dialect, "year", Column(dialect, "created_at"))


def _interval_expr(dialect):
    from rhosocial.activerecord.backend.expression.datetime import IntervalExpression

    return IntervalExpression(dialect, 7, "day")


def _datetime_diff_expr(dialect):
    from rhosocial.activerecord.backend.expression.core import Column
    from rhosocial.activerecord.backend.expression.datetime import DateTimeDiffExpression

    return DateTimeDiffExpression(dialect, "day", Column(dialect, "a"), Column(dialect, "b"))


def _datetime_sub_expr(dialect):
    from rhosocial.activerecord.backend.expression.core import Column
    from rhosocial.activerecord.backend.expression.datetime import (
        DateTimeSubtractExpression,
        IntervalExpression,
    )

    return DateTimeSubtractExpression(dialect, Column(dialect, "a"), IntervalExpression(dialect, 1, "day"))


def _datetime_add_expr(dialect):
    from rhosocial.activerecord.backend.expression.core import Column
    from rhosocial.activerecord.backend.expression.datetime import (
        DateTimeAddExpression,
        IntervalExpression,
    )

    return DateTimeAddExpression(dialect, Column(dialect, "a"), IntervalExpression(dialect, 1, "day"))


_SPECIAL_REGISTRY: Dict[str, Callable] = special_constructors()


def register_special_constructor(fqn_suffix: str, factory: Callable) -> None:
    """Register an explicit constructor for an expression class.

    ``fqn_suffix`` must match the tail of the class's fully qualified name
    (e.g. ``"json.MySQLJSONObjectExpression"``). ``factory(dialect)`` must
    return an expression instance.
    """
    _SPECIAL_REGISTRY[fqn_suffix] = factory


def make_instance(cls: Type[BaseExpression], dialect: Any):
    """Best-effort construction for an expression class.

    Returns (instance, source) where source is "special", "heuristic", or
    (None, "failed").
    """
    full_name = f"{cls.__module__}.{cls.__name__}"
    special = next((fn for s, fn in _SPECIAL_REGISTRY.items() if full_name.endswith(s)), None)
    if special is not None:
        try:
            return special(dialect), "special"
        except Exception:
            return None, "special-failed"
    instance = _try_construct(cls, dialect)
    if instance is None:
        return None, "failed"
    return instance, "heuristic"


def collect_expression_classes(package_path: str) -> Dict[str, Type[BaseExpression]]:
    """Walk a package subtree and collect every defined BaseExpression subclass."""
    import importlib
    import pkgutil

    pkg = importlib.import_module(package_path)
    classes: Dict[str, Type[BaseExpression]] = {}
    for _, modname, _ in pkgutil.walk_packages(pkg.__path__, pkg.__name__ + "."):
        try:
            mod = importlib.import_module(modname)
        except Exception:
            continue
        for name in dir(mod):
            obj = getattr(mod, name, None)
            if (
                isinstance(obj, type)
                and obj.__module__ == modname
                and issubclass(obj, BaseExpression)
                and obj is not BaseExpression
                and not inspect.isabstract(obj)
            ):
                classes[f"{modname}.{name}"] = obj
    return classes


def register_all(classes: Dict[str, Type[BaseExpression]]) -> None:
    """Hand the collected classes to the deserialization kind whitelist.

    Core split the class index out of the serialization module into a
    registry: deserialization resolves a node to its class through the
    framework's default registry, not through the ``(dialect, kind)`` render
    registry -- the two are separate mechanisms and only the former names
    expression classes. Core and the built-in backends populate that registry
    on first use; registering one of those classes again is a no-op, and the
    backend classes collected by the matrix are what this call adds.
    """
    from rhosocial.activerecord.backend.expression.serialization import default_registry

    registry = default_registry()
    for cls in classes.values():
        registry.register_node(cls)


def register_enums_and_dataclasses(package_path: str) -> None:
    """Register a package's enums and dataclasses into the same whitelist.

    An artifact encodes an enum member as ``[short class name, member]`` and
    the reader resolves that name through the registry's enum table -- no
    ``importlib`` by name (untrusted input, §4.11.4), so a backend enum that
    was never registered refuses to read back. Core populates its own enums
    and dataclasses; a backend package's are exactly as privileged as a
    third-party plugin's, which is to say they are registered, not discovered.
    Same ownership filters as core's own populator: the class must be defined
    in the module being walked.
    """
    import dataclasses
    import enum as _enum
    import importlib
    import pkgutil

    from rhosocial.activerecord.backend.expression.registry import RegistryError
    from rhosocial.activerecord.backend.expression.serialization import default_registry

    registry = default_registry()
    pkg = importlib.import_module(package_path)
    if hasattr(pkg, "__path__"):
        modnames = [
            m for _, m, _ in pkgutil.walk_packages(
                path=pkg.__path__, prefix=package_path + ".", onerror=lambda x: None
            )
        ]
    else:
        modnames = [package_path]
    for modname in modnames:
        try:
            mod = importlib.import_module(modname)
        except Exception:
            continue
        for name in dir(mod):
            obj = getattr(mod, name, None)
            if not isinstance(obj, type) or obj.__module__ != modname:
                continue
            if issubclass(obj, _enum.Enum):
                try:
                    registry.register_enum(obj)
                except RegistryError:
                    pass
            elif dataclasses.is_dataclass(obj):
                try:
                    registry.register_dataclass(obj)
                except RegistryError:
                    pass


def assert_params_equal(a: Any, b: Any, path: str = "params") -> None:
    """Deep-compare two get_params() outputs, treating nested BaseExpression
    instances as structurally equal and nested dataclasses as recursively compared.
    """
    if a is b:
        return
    if isinstance(a, BaseExpression) and isinstance(b, BaseExpression):
        assert_params_equal(a.get_params(), b.get_params(), path + ".<expr>")
        return
    if dataclasses.is_dataclass(a) and not isinstance(a, type):
        assert dataclasses.is_dataclass(b) and not isinstance(b, type), (
            f"{path}: expected dataclass instance, got {type(b).__name__}"
        )
        for f in dataclasses.fields(a):
            assert_params_equal(getattr(a, f.name), getattr(b, f.name), f"{path}.{f.name}")
        return
    assert type(a) is type(b) or (
        isinstance(a, (list, tuple, dict)) and isinstance(b, (list, tuple, dict))
    ), f"{path}: type mismatch {type(a).__name__} vs {type(b).__name__}"
    if isinstance(a, dict):
        assert set(a) == set(b), f"{path}: keys differ {set(a) ^ set(b)}"
        for k in a:
            assert_params_equal(a[k], b[k], f"{path}.{k}")
        return
    if isinstance(a, (list, tuple)):
        assert len(a) == len(b), f"{path}: length differ"
        # strict=False because the length assert above is the intended check
        # and carries the better message; a strict zip would pre-empt it with
        # a bare ValueError.
        for i, (x, y) in enumerate(zip(a, b, strict=False)):
            assert_params_equal(x, y, f"{path}[{i}]")
        return
    assert a == b, f"{path}: {a!r} != {b!r}"


def roundtrip_expression(fqn: str, instance: BaseExpression, dialect: Any) -> None:
    """Assert an instance round-trips losslessly through dict / JSON / XML."""
    original = instance.get_params()
    for restored in (
        _rt_dict(instance, dialect),
        _rt_json(instance, dialect),
        _rt_xml(instance, dialect),
    ):
        assert_params_equal(restored.get_params(), original, fqn)


def _rt_dict(instance, dialect):
    from rhosocial.activerecord.backend.expression.serialization import deserialize, serialize

    return deserialize(serialize(instance), dialect)


def _rt_json(instance, dialect):
    from rhosocial.activerecord.backend.expression.serialization import deserialize_json, serialize_json

    return deserialize_json(serialize_json(instance), dialect)


def _rt_xml(instance, dialect):
    from rhosocial.activerecord.backend.expression.serialization import deserialize_xml, serialize_xml

    return deserialize_xml(serialize_xml(instance), dialect)


def sql_consistent(fqn: str, instance: BaseExpression, dialect: Any) -> None:
    """Assert to_sql is identical after round-trip, when the dialect supports it."""
    try:
        expected = instance.to_sql()
    except Exception:
        return
    for restored in (_rt_dict(instance, dialect), _rt_json(instance, dialect), _rt_xml(instance, dialect)):
        assert restored.to_sql() == expected, fqn


__all__ = [
    "assert_params_equal",
    "collect_expression_classes",
    "make_instance",
    "register_all",
    "register_enums_and_dataclasses",
    "register_special_constructor",
    "roundtrip_expression",
    "sql_consistent",
]