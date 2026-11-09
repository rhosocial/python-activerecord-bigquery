# src/rhosocial/activerecord/backend/impl/bigquery/cli/introspect.py
"""The introspection subcommands: the catalogue questions, the engine's own
``partitions`` family, the routines family, and the nine families the
dialect answers or declines.

Each one wires ``backend.introspector`` to an output format:

========================  =======================================
Command                   Introspector question
``tables``                ``list_tables()``
``views``                 ``list_views()``
``routines [NAME]``       ``list_routines()`` / ``get_routine_info()``
``columns NAME``          ``list_columns()``
``datasets``              ``list_datasets()`` (the SCHEMATA view)
``database``              ``get_database_info()`` (@@project_id)
``partitions NAME``       ``list_partitions()`` (PARTITIONS view)
``column-profiles NAME``  ``list_column_data_profiles()``
``value-samples NAME``    ``sample_column_values()``
``join-coverage NAME``    ``estimate_join_coverage()``
========================  =======================================

The five families this backend declines -- ``unused-indexes``,
``table-stats``, ``runtime``, ``index-stats`` and ``dependencies`` -- are
listed too, so that asking one of them is answered by the capability gate
rather than by an "unknown command". ``ddl`` is not offered at all: the
dialect's ``supports_ddl_extraction()`` is False and no extraction statement
exists here, so the subcommand would only ever be a refusal.

``--dataset`` selects the dataset every question is scoped to, and the
schema argument each question receives is BigQuery's **dataset** -- the two
are the same level, which is why one flag answers both. ``database`` is the
one question scoped to the project instead, because ``@@project_id`` names
the project and no dataset.

No command fabricates an answer. Without a dataset the introspector raises
with the exact instruction, and without credentials the client refuses to
connect; both exit non-zero with the reason on stderr.

``NAME`` is required, optional or refused per subcommand, and the rule for
each lives in ``_NAME_RULE`` rather than inside the question that needs it:
a name a command has no question for is refused with exit 2, never parsed
and dropped, because a dropped name prints the family listing under a
one-object question.
"""

import argparse
import asyncio
import sys
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any, Callable, Dict

from rhosocial.activerecord.backend.errors import ConnectionError, QueryError

from .connection import (
    add_connection_args,
    resolve_connection_config_from_args,
)
from .output import OUTPUT_CHOICES, create_provider

#: Subcommand -> the dialect capability switch that decides whether the
#: connected project can answer it.
#:
#: The advertised list is derived from this mapping, so a subcommand cannot
#: be offered without saying which switch gates it. A subcommand whose
#: switch is False is refused when handled, rather than run and answered
#: with an empty row -- "this project cannot report per-index use counters"
#: and "this project has no counters" are different answers, and only one
#: of them is what happened.
#:
#: Two questions sit beside them that this backend answers on its own.
#: ``database`` is the project-level question -- the documented
#: ``@@project_id`` system variable, which names no dataset -- and
#: ``partitions`` is the engine's own: ``INFORMATION_SCHEMA.PARTITIONS``
#: answers one row per partition of one table, which no core family covers.
#: Both are declared by the dialect, so a CLI that could not ask them would
#: be "answerable but unaskable", the defect §6 exists to prevent.
#:
#: BigQuery declares three of the families beyond its catalogue and its
#: partitions view: the three that read the *rows* (a profile, a value
#: listing, an overlap measurement), because ``INFORMATION_SCHEMA`` describes
#: what a column declares and no view reports what its rows hold. The other
#: five answer False -- there is no unused-index view, no usage counters, no
#: runtime metrics, no index counters and no dependency graph in
#: ``INFORMATION_SCHEMA`` -- so their subcommands exist to be refused rather
#: than to run. ``ddl`` is absent from this mapping because
#: ``supports_ddl_extraction()`` is False and there is no extraction statement
#: here; a subcommand whose capability is permanently false is not advertised.
_TYPE_CAPABILITIES = {
    "tables": "supports_table_introspection",
    "views": "supports_view_introspection",
    "routines": "supports_routine_introspection",
    "columns": "supports_column_introspection",
    "datasets": "supports_dataset_introspection",
    "database": "supports_database_info",
    "partitions": "supports_partition_info",
    "unused-indexes": "supports_unused_indexes_detection",
    "table-stats": "supports_table_stats",
    "runtime": "supports_runtime_stats",
    "index-stats": "supports_index_stats",
    "dependencies": "supports_object_dependencies",
    "column-profiles": "supports_column_data_profile",
    "value-samples": "supports_column_value_sample",
    "join-coverage": "supports_join_coverage",
}

#: The subcommands this module owns. ``cli.get_handler`` routes each name
#: here; nothing else registers one of them.
INTROSPECT_TYPES = list(_TYPE_CAPABILITIES)

#: What the optional NAME positional means for each subcommand.
#:
#: ``required`` -- the subcommand asks about one object and cannot be
#: answered without it. ``optional`` -- a family that can also answer for
#: one named object, so a given name narrows it and omitting it asks for the
#: whole family. ``forbidden`` -- the subcommand has no single-object
#: question here, so a name would read as a filter that matched everything.
#:
#: The order is the order ``_TYPE_CAPABILITIES`` declares and the parser and
#: ``--help`` print, and the two tables cover the same keys: a subcommand
#: offered without a rule is one whose NAME decision nobody has made.
#:
#: ``tables`` and ``datasets`` are listings over the whole dataset or
#: project and take no positional at all; argparse refuses a stray one.
#: ``database`` answers for the project the run connected to, and the four
#: counter families for the dataset as a whole, so a name beside any of them
#: is refused rather than parsed and dropped. ``routines`` is a listing that
#: can also answer for one named routine, and ``dependencies`` can answer for
#: one object's edges, so both names are optional. ``partitions`` is a
#: one-table question: without a name
#: the read is the dataset-wide one the storage reducer asks, which is a
#: different question the statement has no filter for.
_NAME_RULE = {
    "tables": "forbidden",
    "views": "forbidden",
    "routines": "optional",
    "columns": "required",
    "datasets": "forbidden",
    "database": "forbidden",
    "partitions": "required",
    "unused-indexes": "forbidden",
    "table-stats": "forbidden",
    "runtime": "forbidden",
    "index-stats": "forbidden",
    "dependencies": "optional",
    "column-profiles": "required",
    "value-samples": "required",
    "join-coverage": "required",
}

#: The subcommands that act on a named object, so they carry the positional
#: name the others do not. Derived from the rule table rather than written a
#: second time: one decision, read by the parser and by the validator alike.
_NAME_COMMANDS = tuple(
    name for name, rule in _NAME_RULE.items() if rule == "required"
)

#: The subcommands that can also answer for one named object but answer the
#: whole family without it. ``routines`` narrows to one routine when a name
#: is given; ``dependencies`` narrows to one object's edges. BigQuery
#: declines the dependency family, so both of its spellings reach the same
#: refusal -- but the name still has to parse, or the refusal would be
#: argparse's instead of the capability answer.
_OPTIONAL_NAME_COMMANDS = tuple(
    name for name, rule in _NAME_RULE.items() if rule == "optional"
)

_EPILOG = """Examples:
  # Every dataset in the project, and the project itself
  %(prog)s datasets --project my-project
  %(prog)s database --project my-project

  # Tables and views in one dataset
  %(prog)s tables --project my-project --dataset my_dataset
  %(prog)s views --project my-project --dataset my_dataset

  # The dataset's routines, and one named routine
  %(prog)s routines --project my-project --dataset my_dataset
  %(prog)s routines my_function --project my-project --dataset my_dataset

  # One table's columns, and its partitions
  %(prog)s columns orders --project my-project --dataset my_dataset
  %(prog)s partitions orders --project my-project --dataset my_dataset

  # What the rows hold: a profile, the most frequent values, an overlap
  %(prog)s column-profiles orders --project my-project --dataset my_dataset
  %(prog)s value-samples orders --column status --project my-project --dataset my_dataset
  %(prog)s join-coverage orders --column buyer_id --right-table users \\
    --right-column id --project my-project --dataset my_dataset

  # The families BigQuery declines -- refused, not answered with an empty row
  %(prog)s unused-indexes --project my-project --dataset my_dataset
  %(prog)s dependencies --project my-project --dataset my_dataset

  # JSON output, and the environment-variable form
  %(prog)s tables -o json
  export BIGQUERY_PROJECT=my-project BIGQUERY_DATASET=my_dataset
  export BIGQUERY_CREDENTIALS_PATH=/path/to/key.json
  %(prog)s tables
"""


def create_parser(subparsers):
    """Register every introspection subcommand.

    Args:
        subparsers: The parser's subcommand group.

    Returns:
        None; the subcommands are registered into *subparsers*.
    """
    for name in INTROSPECT_TYPES:
        parser = subparsers.add_parser(
            name,
            help=_HELP[name],
            epilog=_EPILOG,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        if name in _NAME_COMMANDS:
            # It acts on one named table; the others list everything and
            # take no positional.
            parser.add_argument(
                "name",
                help=_POSITIONAL_HELP[name],
            )
        if name in _OPTIONAL_NAME_COMMANDS:
            # It answers the whole family without a name and one object's
            # part of it with one, so the positional is optional rather than
            # required or absent.
            parser.add_argument(
                "name",
                nargs="?",
                default=None,
                help="Optional object name; omit it for the whole graph",
            )
        # The flags the row families read. They stay flags rather than more
        # positionals because ``name`` already means "the table" everywhere
        # else, and ``value-samples orders.email`` would read as a dotted
        # object name. A subcommand that reads none of them refuses them
        # (see :func:`_refuse_unused_arguments`) rather than parsing and
        # dropping them.
        if name in _COLUMN_COMMANDS:
            parser.add_argument(
                "--column",
                default=None,
                help="Column name: the column to sample for value-samples, "
                "and the left column for join-coverage",
            )
        if name == "join-coverage":
            parser.add_argument(
                "--right-table",
                dest="right_table",
                default=None,
                help="Right-hand table for the join-coverage type",
            )
            parser.add_argument(
                "--right-column",
                dest="right_column",
                default=None,
                help="Right-hand column for the join-coverage type",
            )
        parser.add_argument(
            "-o",
            "--output",
            choices=OUTPUT_CHOICES,
            default="table",
            help="Output format (default: table)",
        )
        parser.add_argument(
            "--include-system",
            action="store_true",
            help=("Include system tables (ignored: BigQuery's INFORMATION_SCHEMA " "lists none)"),
        )
        parser.add_argument(
            "--rich-ascii",
            action="store_true",
            help="Use ASCII characters for rich table borders.",
        )
        add_connection_args(parser)


_HELP = {
    "tables": "List the tables and views in a dataset",
    "views": "List the views in a dataset",
    "routines": "List a dataset's routines, or report one named routine",
    "columns": "List one table's columns",
    "datasets": "List the project's datasets",
    # The project-level question: BigQuery answers it from the documented
    # ``@@project_id`` system variable, so it is a family rather than a
    # refusal -- the connection already names the project, and the CLI can
    # report it.
    "database": "Report the project this run is connected to",
    # The engine's own family: one row per partition, with the rows and the
    # bytes each holds. Core's per-table storage minimum is one slot this
    # reduces its sums onto; the partition rows are finer than that and stay
    # here where the dialect declares them.
    "partitions": "List one table's partitions, with their sizes",
    # The four operational families: declined here, so the help says what
    # the subcommand is for and the gate says it cannot be answered.
    "unused-indexes": "Indexes with no recorded use (not supported by BigQuery)",
    "table-stats": "Per-table usage counters (not supported by BigQuery)",
    "runtime": "Live runtime measurements (not supported by BigQuery)",
    "index-stats": "Per-index usage counters (not supported by BigQuery)",
    "dependencies": "The object dependency graph (not supported by BigQuery)",
    # ``ddl`` is not offered: supports_ddl_extraction() is False and no
    # extraction statement exists, so the subcommand would only be refused.
    # The three families that read the rows rather than the catalogue.
    "column-profiles": "Profile every column of a table from its data",
    "value-samples": "List one column's most frequent values",
    "join-coverage": "Measure how two columns' value domains overlap",
}

_POSITIONAL_HELP = {
    "columns": "Table name (required)",
    "partitions": "Table name (required)",
    "column-profiles": "Table name (required)",
    "value-samples": "Table name (required)",
    "join-coverage": "Left table name (required)",
}

#: The subcommands that read ``--column``. Only these may be given it; the
#: flag check refuses it everywhere else rather than dropping it.
_COLUMN_COMMANDS = ("value-samples", "join-coverage")


def get_handler(command_name: str) -> Callable[[argparse.Namespace], None]:
    """Return :func:`handle` for one introspection subcommand name.

    Args:
        command_name: One of :data:`INTROSPECT_TYPES`.

    Returns:
        The ``handle`` entry point.

    Raises:
        KeyError: *command_name* is not an introspection subcommand.
    """
    if command_name not in INTROSPECT_TYPES:
        raise KeyError(f"{command_name!r} is not one of {list(INTROSPECT_TYPES)}")
    return handle


def handle(args):
    """Handle one introspection subcommand.

    The backend is built from the parsed arguments and handed to the sync or
    the async runner, which runs the question and prints the result.
    """
    provider = create_provider(args.output, ascii_borders=args.rich_ascii)
    backend = _build_backend(args)

    if args.use_async:
        asyncio.run(_run_async(args, backend, provider))
    else:
        _run_sync(args, backend, provider)


def _build_backend(args):
    """The backend class and config this run talks to."""
    from rhosocial.activerecord.backend.impl.bigquery.backend.async_backend import (
        AsyncBigQueryBackend,
    )
    from rhosocial.activerecord.backend.impl.bigquery.backend.backend import (
        BigQueryBackend,
    )

    config = resolve_connection_config_from_args(args)
    backend_class = AsyncBigQueryBackend if args.use_async else BigQueryBackend
    return backend_class(connection_config=config)


def _serialize_for_output(obj: Any) -> Any:
    """Make an introspection result JSON/CSV-serialisable.

    Dataclasses become dicts, enums their wire word, and anything left over
    its ``str()`` -- a representation the reader can see rather than a
    ``TypeError`` naming the type.
    """
    if obj is None:
        return None
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _serialize_for_output(v) for k, v in asdict(obj).items()}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {k: _serialize_for_output(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize_for_output(item) for item in obj]
    if isinstance(obj, (str, int, float, bool)):
        return obj
    return str(obj)


def _validate_name(args) -> None:
    """Apply the NAME rule table, once, instead of inside each question.

    A silently ignored argument is the worst of the three outcomes: the run
    succeeds, prints a family listing, and reads as though it had been
    narrowed to one object. So the table above is read here, once -- a
    question that forgot would answer a wider question than the one asked
    and look successful doing it.

    The name is read with ``getattr`` because the parser only declares the
    positional for the subcommands that have one, so an absent attribute is
    "no name was given" rather than an error. A *missing* name is an
    incomplete invocation and leaves with 1, the code a missing ``--dataset``
    gets; a name the command has no question for is a request this command
    declines and leaves with 2.
    """
    rule = _NAME_RULE.get(args.command)
    name = getattr(args, "name", None)
    if rule == "required" and not name:
        print(
            f"Error: a table name is required for the '{args.command}' command",
            file=sys.stderr,
        )
        sys.exit(1)
    if rule == "forbidden" and name:
        print(
            f"Error: '{args.command}' does not take an object name; "
            "it answers for everything in scope, not one object",
            file=sys.stderr,
        )
        sys.exit(2)


def _require_column(command: str, args) -> str:
    """The ``--column`` a value listing or an overlap measurement needs."""
    column = getattr(args, "column", None)
    if not column:
        print(
            f"Error: --column is required for the '{command}' command",
            file=sys.stderr,
        )
        sys.exit(1)
    return column


def _require_right_table(args) -> str:
    """The ``--right-table`` an overlap measurement needs."""
    right_table = getattr(args, "right_table", None)
    if not right_table:
        print(
            "Error: --right-table and --right-column are required for the "
            "'join-coverage' command",
            file=sys.stderr,
        )
        sys.exit(1)
    return right_table


def _require_right_column(args) -> str:
    """The ``--right-column`` an overlap measurement needs."""
    right_column = getattr(args, "right_column", None)
    if not right_column:
        print(
            "Error: --right-table and --right-column are required for the "
            "'join-coverage' command",
            file=sys.stderr,
        )
        sys.exit(1)
    return right_column


def _refuse_unused_arguments(args) -> None:
    """Refuse a flag the chosen command has no question for.

    The same defect as a silently dropped name, one flag over: ``--column``
    beside ``tables`` would be ignored and the listing printed as if the
    column had been part of the question. Only the two families whose probe
    takes a column read ``--column``, and only ``join-coverage`` reads the
    two right-hand names, so only they may be given them.

    The flags are read with ``getattr`` because the handler is also driven
    with hand-built namespaces (the offline tests), which carry no flags at
    all -- an absent attribute is "not given", not an error.
    """
    column = getattr(args, "column", None)
    right_table = getattr(args, "right_table", None)
    right_column = getattr(args, "right_column", None)

    if column is not None and args.command not in _COLUMN_COMMANDS:
        print(
            f"Error: '{args.command}' does not take --column; use "
            "'value-samples' or 'join-coverage'",
            file=sys.stderr,
        )
        sys.exit(2)
    if (right_table is not None or right_column is not None) and args.command != "join-coverage":
        print(
            f"Error: '{args.command}' does not take --right-table or "
            "--right-column; use 'join-coverage'",
            file=sys.stderr,
        )
        sys.exit(2)


def _require_capability(backend, args) -> None:
    """Refuse a family this project cannot answer.

    BigQuery exposes a stable standard SQL feature set and its dialect is
    not version-adapted, so the switches answer for the dialect this
    backend constructs rather than for a negotiated version -- the same
    answer every call of the same construction gets. A project that cannot
    answer is refused at the capability question, rather than handed a
    statement the engine would reject or, worse, an empty row that reads
    like an answer of zero.
    """
    switch = _TYPE_CAPABILITIES.get(args.command)
    if switch is None:
        return
    dialect = getattr(backend, "dialect", None)
    if dialect is None:
        # A stub standing in for the backend (the offline CLI tests) has no
        # dialect to ask; a real one always does.
        return
    supported = getattr(dialect, switch, None)
    if supported is None or supported():
        return
    print(
        f"Error: {args.command} introspection is not supported by this server",
        file=sys.stderr,
    )
    sys.exit(2)


def _schema_arg(args):
    """The dataset a question is scoped to.

    One flag, ``--dataset``, which the connection already takes: BigQuery has
    no schema under a dataset, so the dataset is the only namespace level a
    question can be scoped to. An earlier version also accepted ``--schema``
    and fell back to ``--dataset`` when it was absent, which spelled the same
    level under a word BigQuery does not use -- and made the fallback order the
    thing a reader had to work out.
    """
    return args.dataset


# ---------------------------------------------------------------------------
# The questions, as data: each sync handler and its async twin
# ---------------------------------------------------------------------------


def _questions(args) -> Dict[str, Callable[[Any], Any]]:
    """Map each subcommand onto the introspector call it runs (sync)."""
    schema = _schema_arg(args)

    # The four operational families are listings over the dataset's scope, so
    # none takes a name. Refused by the gate on this backend; the entries
    # exist so the refusal is a capability answer rather than an unhandled
    # subcommand. They are defined before the mapping because a ``def`` is a
    # statement and cannot sit inside a dict display.
    # The four counter families and the project-level question are
    # ``forbidden`` in ``_NAME_RULE``: they answer for everything in scope,
    # so ``_validate_name`` has already refused a run that named one object.
    # What is left here is the question itself.

    def _unused_indexes(introspector):
        return introspector.list_unused_indexes(schema=schema)

    def _table_usage_stats(introspector):
        return introspector.list_table_usage_stats(schema=schema)

    def _runtime_metrics(introspector):
        return introspector.list_runtime_metrics(schema=schema)

    def _index_usage_stats(introspector):
        return introspector.list_index_usage_stats(schema=schema)

    def _database_info(introspector):
        return introspector.get_database_info()

    def _routines(introspector):
        # A family with one listing and one named-object question: the name
        # is optional, so it narrows the same catalogue read rather than
        # selecting a different method.
        if args.name:
            return introspector.get_routine_info(args.name, schema=schema)
        return introspector.list_routines(schema=schema)

    return {
        "tables": lambda introspector: introspector.list_tables(
            schema=schema, include_system=args.include_system
        ),
        "views": lambda introspector: introspector.list_views(schema=schema),
        "routines": _routines,
        "columns": lambda introspector: introspector.list_columns(
            args.name, schema=schema
        ),
        "datasets": lambda introspector: introspector.list_datasets(),
        "database": _database_info,
        # One table, one partition row each: the name is required because the
        # question filters partitions by it, and a name-less ``PARTITIONS``
        # read is the dataset-wide one the storage reducer asks rather than
        # this family.
        "partitions": lambda introspector: introspector.list_partitions(
            args.name, schema=schema
        ),
        "unused-indexes": _unused_indexes,
        "table-stats": _table_usage_stats,
        "runtime": _runtime_metrics,
        "index-stats": _index_usage_stats,
        # ``dependencies`` narrows to one object when a name is given and
        # answers the whole graph without one, so a name is optional rather
        # than refused.
        "dependencies": lambda introspector: introspector.list_object_dependencies(
            object_name=args.name, schema=schema
        ),
        # ---- the one-object and two-object families -------------------
        "column-profiles": lambda introspector: introspector.list_column_data_profiles(
            args.name, schema=schema
        ),
        "value-samples": lambda introspector: introspector.sample_column_values(
            args.name,
            _require_column("value-samples", args),
            schema=schema,
        ),
        "join-coverage": lambda introspector: introspector.estimate_join_coverage(
            args.name,
            _require_column("join-coverage", args),
            _require_right_table(args),
            _require_right_column(args),
            schema=schema,
        ),
    }


def _async_questions(args) -> Dict[str, Callable[[Any], Any]]:
    """The same mapping, for the async introspector.

    The calls are literally the same: an async introspector's method
    returns the awaitable the runner awaits, so the mapping is built once
    in :func:`_questions` and read here unchanged.
    """
    return _questions(args)


def _report(result: Any, args, provider) -> None:
    """Print one question's result.

    One result, one table of rows. The two answers ``table`` used to print
    together -- columns and primary key -- are now the ``columns`` command
    and the key columns it reports.
    """
    if args.command == "routines" and getattr(args, "name", None):
        # A named-routine answer is one record, not a listing. ``None`` is
        # "the dataset has no routine with that name", which is not an empty
        # listing and should not exit 0 with a blank table.
        if result is None:
            print(
                f"Error: no routine named '{args.name}' in the dataset",
                file=sys.stderr,
            )
            sys.exit(1)
        provider.display_results(
            [_serialize_for_output(result)],
            title=_TITLES.get(args.command, args.command.title()),
        )
        return

    if args.command == "database":
        # One record, not a listing: the answer describes the project the run
        # connected to, and ``list()`` on it would iterate the object's
        # fields. Printed as one row, the way the other one-object answers
        # are.
        provider.display_results(
            [_serialize_for_output(result)],
            title=_TITLES.get(args.command, args.command.title()),
        )
        return

    if args.command == "column-profiles":
        # The price sentence, before the rows, so a reader sees it while
        # looking at figures that cost a scan. On stderr, so the machine
        # formats on stdout stay parseable.
        print(
            "Note: a column profile is one full scan of the table, and BigQuery "
            "bills by bytes read -- the most expensive introspection this command "
            "offers. The figures are exact counts (source='aggregate'), not "
            "estimates.",
            file=sys.stderr,
        )
        rows = _serialize_for_output(list(result))
        provider.display_results(rows, title=_TITLES.get(args.command, args.command.title()))
        return

    if args.command == "value-samples":
        if result is None:
            # ``None`` is "no measurement", which is not an empty column;
            # printing an empty listing would read as a measured zero.
            print(
                f"Error: this server could not measure '{args.command}'",
                file=sys.stderr,
            )
            sys.exit(1)
        title = _TITLES.get(args.command, args.command.title())
        provider.display_results(_serialize_for_output(list(result)), title=title)
        return

    if args.command == "join-coverage":
        if result is None:
            # ``None`` is "no measurement", which is not zero overlap;
            # printing a row of nulls would read as a measured zero.
            print(
                f"Error: this server could not measure '{args.command}'",
                file=sys.stderr,
            )
            sys.exit(1)
        # One measurement, printed as one row: the coverage is a record, not
        # a listing, and ``list()`` on it would iterate its fields.
        provider.display_results(
            _serialize_for_output([result]),
            title=_TITLES.get(args.command, args.command.title()),
        )
        return

    title = _TITLES.get(args.command, args.command.title())
    provider.display_results(_serialize_for_output(list(result)), title=title)


#: How each subcommand's rows are titled. Hyphenated names need a word
#: ``str.title()`` would spell ``Unused-Indexes``, and the four operational
#: families read better as what they measure than as their subcommand name.
_TITLES = {
    "database": "Database Info",
    "routines": "Routines",
    "partitions": "Partitions",
    "unused-indexes": "Indexes with no recorded use",
    "table-stats": "Table usage counters",
    "runtime": "Runtime metrics",
    "index-stats": "Index usage counters",
    "dependencies": "Object dependencies",
    "column-profiles": "Column profiles",
    "value-samples": "Most frequent values",
    "join-coverage": "Join coverage",
}


def _run_sync(args, backend, provider) -> None:
    """Run the question synchronously and report it."""
    try:
        backend.connect()
        _require_capability(backend, args)
        _refuse_unused_arguments(args)
        _validate_name(args)
        _report(_questions(args)[args.command](backend.introspector), args, provider)
    except ConnectionError as exc:
        print(f"Connection error: {exc}", file=sys.stderr)
        sys.exit(1)
    except QueryError as exc:
        print(f"Query error: {exc}", file=sys.stderr)
        sys.exit(1)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        if getattr(backend, "_client", None):
            backend.disconnect()


async def _run_async(args, backend, provider) -> None:
    """Run the question asynchronously and report it."""
    try:
        await backend.connect()
        _require_capability(backend, args)
        _refuse_unused_arguments(args)
        _validate_name(args)
        call = _async_questions(args)[args.command]
        _report(await call(backend.introspector), args, provider)
    except ConnectionError as exc:
        print(f"Connection error: {exc}", file=sys.stderr)
        sys.exit(1)
    except QueryError as exc:
        print(f"Query error: {exc}", file=sys.stderr)
        sys.exit(1)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        if getattr(backend, "_client", None):
            await backend.disconnect()


__all__ = [
    "INTROSPECT_TYPES",
    "create_parser",
    "get_handler",
    "handle",
]
