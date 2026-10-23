# src/rhosocial/activerecord/backend/impl/bigquery/cli/introspect.py
"""The introspection subcommands: ``tables``, ``views``, ``table``,
``columns`` and ``datasets``.

Each one wires ``backend.introspector`` to an output format:

===============================  ======================================
Command                          Introspector question
===============================  ======================================
``tables``                       ``list_tables()``
``views``                        ``list_views()``
``table NAME``                   ``get_table_info()`` -- columns and
                                 primary key of one table
``columns NAME``                 ``list_columns()``
``datasets``                     ``list_datasets()`` (the SCHEMATA view)
===============================  ======================================

``--dataset`` selects the dataset every question is scoped to, and the
schema argument each question receives is BigQuery's **dataset** -- the two
are the same level, which is why one flag answers both.

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

#: The subcommands this module owns. ``cli.get_handler`` routes each name
#: here; nothing else registers one of them.
INTROSPECT_SUBCOMMANDS = ("tables", "views", "table", "columns", "datasets")

#: The two subcommands that act on one named table, so they carry the
#: positional name the other three do not.
_NAME_COMMANDS = ("table", "columns")

_EPILOG = """Examples:
  # Every dataset in the project
  %(prog)s datasets --project my-project

  # Tables and views in one dataset
  %(prog)s tables --project my-project --dataset my_dataset
  %(prog)s views --project my-project --dataset my_dataset

  # One table's columns and primary key
  %(prog)s table orders --project my-project --dataset my_dataset
  %(prog)s columns orders --project my-project --dataset my_dataset

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
            # Only these two act on one named table; the others list
            # everything and take no positional.
            parser.add_argument(
                "name",
                help=_POSITIONAL_HELP[name],
            )
        parser.add_argument(
            "-o",
            "--output",
            choices=OUTPUT_CHOICES,
            default="table",
            help="Output format (default: table)",
        )
        parser.add_argument(
            "--schema",
            dest="schema",
            default=None,
            help=(
                "Dataset to introspect (default: --dataset / the "
                "connection default). A dataset ID, or project.dataset."
            ),
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
    "table": "Show one table's columns and primary key",
    "columns": "List one table's columns",
    "datasets": "List the project's datasets",
}

_POSITIONAL_HELP = {
    "table": "Table name (required)",
    "columns": "Table name (required)",
}


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


def _schema_arg(args):
    """The dataset a question is scoped to: ``--schema`` over ``--dataset``."""
    return args.schema if args.schema is not None else args.dataset


# ---------------------------------------------------------------------------
# The five questions, as data: each sync handler and its async twin
# ---------------------------------------------------------------------------


def _questions(args) -> Dict[str, Callable[[Any], Any]]:
    """Map each subcommand onto the introspector call it runs (sync)."""
    schema = _schema_arg(args)
    return {
        "tables": lambda introspector: introspector.list_tables(
            schema=schema, include_system=args.include_system
        ),
        "views": lambda introspector: introspector.list_views(schema=schema),
        "table": lambda introspector: introspector.get_table_info(
            _one("table", args), schema=schema
        ),
        "columns": lambda introspector: introspector.list_columns(
            _one("columns", args), schema=schema
        ),
        "datasets": lambda introspector: introspector.list_datasets(),
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

    ``table`` answers a whole object, so its columns and primary key are
    two tables under their own titles -- the shape the question has. A
    missing table is an exit, not an empty table.
    """
    if args.command == "table":
        if result is None:
            print(f"Error: table '{args.name}' was not found", file=sys.stderr)
            sys.exit(1)
        provider.display_results(
            _serialize_for_output(result.columns),
            title=f"Columns of {args.name}",
        )
        if result.indexes:
            provider.display_results(
                _serialize_for_output(result.indexes),
                title=f"Primary key of {args.name}",
            )
        return
    title = "Datasets" if args.command == "datasets" else args.command.title()
    provider.display_results(_serialize_for_output(list(result)), title=title)


def _run_sync(args, backend, provider) -> None:
    """Run the question synchronously and report it."""
    try:
        backend.connect()
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
