# src/rhosocial/activerecord/backend/impl/bigquery/cli/introspect.py
"""The introspection subcommands: the catalogue questions, the engine's own
``partitions`` family, and the nine families the dialect answers or declines.

Each one wires ``backend.introspector`` to an output format:

========================  =======================================
Command                   Introspector question
``tables``                ``list_tables()``
``views``                 ``list_views()``
``columns NAME``          ``list_columns()``
``datasets``              ``list_datasets()`` (the SCHEMATA view)
``database``              ``get_database_info()`` (@@project_id)
``partitions NAME``       ``list_partitions()`` (PARTITIONS view)
``column-profiles NAME``  ``list_column_data_profiles()``
``value-samples NAME``    ``sample_column_values()``
``join-coverage NAME``    ``estimate_join_coverage()``
========================  =======================================

The six families this backend declines -- ``unused-indexes``,
``table-stats``, ``runtime``, ``index-stats``, ``dependencies`` and
``ddl`` -- are listed too, so that asking one of them is answered by the
capability gate rather than by an "unknown command".

``--dataset`` selects the dataset every question is scoped to, and the
schema argument each question receives is BigQuery's **dataset** -- the two
are the same level, which is why one flag answers both. ``database`` is the
one question scoped to the project instead, because ``@@project_id`` names
the project and no dataset.

No command fabricates an answer. Without a dataset the introspector raises
with the exact instruction, and without credentials the client refuses to
connect; both exit non-zero with the reason on stderr.
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
from .output import create_provider

OUTPUT_CHOICES = ["table", "json", "csv", "tsv"]

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
#: BigQuery declares three of the nine families beyond its catalogue and its
#: partitions view: the three that read the *rows* (a profile, a value
#: listing, an overlap measurement), because ``INFORMATION_SCHEMA`` describes
#: what a column declares and no view reports what its rows hold. The other
#: six answer False -- there is no unused-index view, no usage counters, no
#: runtime metrics and no dependency graph in ``INFORMATION_SCHEMA`` -- so
#: their subcommands exist to be refused rather than to run.
_TYPE_CAPABILITIES = {
    "tables": "supports_table_introspection",
    "views": "supports_view_introspection",
    "columns": "supports_column_introspection",
    "datasets": "supports_dataset_introspection",
    "database": "supports_database_info",
    "partitions": "supports_partition_info",
    "unused-indexes": "supports_unused_indexes_detection",
    "table-stats": "supports_table_stats",
    "runtime": "supports_runtime_stats",
    "index-stats": "supports_index_stats",
    "dependencies": "supports_object_dependencies",
    "ddl": "supports_ddl_extraction",
    "column-profiles": "supports_column_data_profile",
    "value-samples": "supports_column_value_sample",
    "join-coverage": "supports_join_coverage",
}

#: The subcommands this module owns. ``cli.get_handler`` routes each name
#: here; nothing else registers one of them.
INTROSPECT_SUBCOMMANDS = tuple(_TYPE_CAPABILITIES)

#: The subcommands that act on a named table, so they carry the
#: positional name the others do not. ``partitions`` is one of them: the
#: question is one table's partitions, and the answer without a name would
#: be a different question (every partition in the dataset) that the
#: statement has no filter to ask.
_NAME_COMMANDS = (
    "columns",
    "partitions",
    "ddl",
    "column-profiles",
    "value-samples",
    "join-coverage",
)

#: The subcommands that can also answer for one named object but answer the
#: whole family without it. ``dependencies`` narrows to one object's edges
#: when a name is given; omitting it asks for the whole graph. BigQuery
#: declines the family, so both spellings reach the same refusal -- but the
#: name still has to parse, or the refusal would be argparse's instead of
#: the capability answer.
_OPTIONAL_NAME_COMMANDS = ("dependencies",)

#: Said before a column profile prints. It goes to stderr so the machine
#: formats stay parseable, and it says the one thing a reader cannot infer
#: from the rows: BigQuery charges by bytes read, so a profile is a full
#: scan of the table and the most expensive thing this CLI can be asked.
#: Each row carries ``source='aggregate'`` itself, which is what says the
#: figures are exact counts rather than estimates -- this sentence only
#: keeps a reader from taking an exact full-table count for a cheap
#: catalogue reading.
_PROFILE_COST_NOTE = (
    "Note: a column profile is one full scan of the table, and BigQuery "
    "bills by bytes read -- the most expensive introspection this command "
    "offers. The figures are exact counts (source='aggregate'), not "
    "estimates."
)

_EPILOG = """Examples:
  # Every dataset in the project, and the project itself
  %(prog)s datasets --project my-project
  %(prog)s database --project my-project

  # Tables and views in one dataset
  %(prog)s tables --project my-project --dataset my_dataset
  %(prog)s views --project my-project --dataset my_dataset

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
  %(prog)s ddl orders --project my-project --dataset my_dataset

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
    for name in INTROSPECT_SUBCOMMANDS:
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
    "ddl": "The DDL that recreates one table (not supported by BigQuery)",
    # The three families that read the rows rather than the catalogue.
    "column-profiles": "Profile every column of a table from its data",
    "value-samples": "List one column's most frequent values",
    "join-coverage": "Measure how two columns' value domains overlap",
}

_POSITIONAL_HELP = {
    "columns": "Table name (required)",
    "partitions": "Table name (required)",
    "ddl": "Table name (required)",
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
        command_name: One of :data:`INTROSPECT_SUBCOMMANDS`.

    Returns:
        The ``handle`` entry point.

    Raises:
        KeyError: *command_name* is not an introspection subcommand.
    """
    if command_name not in INTROSPECT_SUBCOMMANDS:
        raise KeyError(f"{command_name!r} is not one of {list(INTROSPECT_SUBCOMMANDS)}")
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


def _one(name: str, args) -> str:
    """The positional name of a command that requires one, or an exit."""
    if not args.name:
        print(
            f"Error: a table name is required for the '{name}' command",
            file=sys.stderr,
        )
        sys.exit(1)
    return args.name


def _refuse_name(args, hint: str = "it answers for the whole dataset") -> None:
    """Refuse a positional NAME the command has no question for.

    The operational families describe the dataset or the project as a
    whole: dropping the name instead would print the family listing under
    a one-object question, which is a different answer than the one asked
    for. ``database`` is the project-wide case and says so, because
    "the whole dataset" would send a reader looking for a dataset question
    that does not exist.
    """
    print(
        f"Error: '{args.command}' does not take an object name; {hint}",
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
    def _unused_indexes(introspector, _args=args):
        if getattr(_args, "name", None):
            _refuse_name(_args)
        return introspector.list_unused_indexes(schema=schema)

    def _table_usage_stats(introspector, _args=args):
        if getattr(_args, "name", None):
            _refuse_name(_args)
        return introspector.list_table_usage_stats(schema=schema)

    def _runtime_metrics(introspector, _args=args):
        if getattr(_args, "name", None):
            _refuse_name(_args)
        return introspector.list_runtime_metrics(schema=schema)

    def _index_usage_stats(introspector, _args=args):
        if getattr(_args, "name", None):
            _refuse_name(_args)
        return introspector.list_index_usage_stats(schema=schema)

    def _database_info(introspector, _args=args):
        if getattr(_args, "name", None):
            # The project the run connected to, not one object in it: a name
            # is refused rather than dropped, because ``@@project_id`` answers
            # for the whole project and a "database described by name" does
            # not exist here.
            _refuse_name(_args, "it describes the project the run connected to")
        return introspector.get_database_info()

    return {
        "tables": lambda introspector: introspector.list_tables(
            schema=schema, include_system=args.include_system
        ),
        "views": lambda introspector: introspector.list_views(schema=schema),
        "columns": lambda introspector: introspector.list_columns(
            _one("columns", args), schema=schema
        ),
        "datasets": lambda introspector: introspector.list_datasets(),
        "database": _database_info,
        # One table, one partition row each: the name is required because the
        # question filters partitions by it, and a name-less ``PARTITIONS``
        # read is the dataset-wide one the storage reducer asks rather than
        # this family.
        "partitions": lambda introspector: introspector.list_partitions(
            _one("partitions", args), schema=schema
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
        "ddl": lambda introspector: introspector.get_ddl_statement(
            _one("ddl", args), object_type=None, schema=schema
        ),
        "column-profiles": lambda introspector: introspector.list_column_data_profiles(
            _one("column-profiles", args), schema=schema
        ),
        "value-samples": lambda introspector: introspector.sample_column_values(
            _one("value-samples", args),
            _require_column("value-samples", args),
            schema=schema,
        ),
        "join-coverage": lambda introspector: introspector.estimate_join_coverage(
            _one("join-coverage", args),
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


def _display_ddl(args, provider, statement) -> None:
    """Show one object's DDL as the engine handed it back.

    A DDL text is a block, not a field of a row: a bordered cell wraps every
    one of its lines and reads worse than the text itself. So the terminal
    format prints the engine's own text, and the formats a caller parses
    keep the record -- schema, object type, object name, ``native`` and the
    text -- which is what ``native`` is for: it says the engine retrieved
    this rather than the library assembling it.
    """
    record = _serialize_for_output(statement)
    if isinstance(record, dict):
        text = record.get("ddl")
        object_name = record.get("object_name") or args.name
        object_type = record.get("object_type") or "OBJECT"
    else:  # pragma: no cover - a statement is a record, not a scalar
        text, object_name, object_type = statement, args.name, "OBJECT"
    if not text:
        # Not "no such table": the object exists and the engine answers
        # with no text rather than an assembled fragment that would read as
        # authoritative. The two are worth telling apart, so this exits
        # without printing an empty row.
        print(
            f"Error: no DDL available for '{args.name}'",
            file=sys.stderr,
        )
        sys.exit(1)
    if args.output == "table":
        print(f"-- {object_type} {object_name}")
        print(text)
        return
    provider.display_results([record], title=f"DDL of {object_name}")


def _report(result: Any, args, provider) -> None:
    """Print one question's result.

    One result, one table of rows. The two answers ``table`` used to print
    together -- columns and primary key -- are now the ``columns`` command
    and the key columns it reports.
    """
    if args.command == "ddl":
        _display_ddl(args, provider, result)
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
        print(_PROFILE_COST_NOTE, file=sys.stderr)
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
    "INTROSPECT_SUBCOMMANDS",
    "create_parser",
    "get_handler",
    "handle",
]
