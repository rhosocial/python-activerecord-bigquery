# src/rhosocial/activerecord/backend/impl/bigquery/cli/__init__.py
"""BigQuery CLI: subcommand registration and handler lookup.

The package's shape follows the other backends' small CLIs: ``__main__.py``
parses, this module registers and routes, and each subcommand module owns
its parser and its handler. Every introspection subcommand -- the catalogue
ones, the partitions family this backend answers on its own and the nine
families the dialect answers or declines -- lives in :mod:`~.introspect`, so
this module routes their names there directly.
"""

#: The subcommands the package defines. ``__main__`` names them when a run
#: specifies none.
#:
#: Derived from the introspect module's own list rather than restated here,
#: so adding a family to the mapping there and forgetting it here cannot
#: happen -- an unlisted subcommand still parses but exits with "unknown
#: command" in ``get_handler``, which is the wrong error for a registered
#: one.
from .introspect import INTROSPECT_SUBCOMMANDS as COMMAND_NAMES  # noqa: E402

COMMAND_NAMES = list(COMMAND_NAMES)


def register_commands(subparsers):
    """Register all subcommands.

    Args:
        subparsers: The parser's subcommand group.
    """
    from .introspect import create_parser as introspect_parser

    introspect_parser(subparsers)


def get_handler(command_name: str):
    """Return the handler function for a subcommand.

    Args:
        command_name: The subcommand as spelled on the command line.

    Returns:
        The ``handle(args)`` entry point for that command.

    Raises:
        SystemExit: The name is not a command this package defines.
    """
    import sys

    from .introspect import get_handler as introspect_handler

    if command_name not in COMMAND_NAMES:
        print(
            f"Error: unknown command {command_name!r}: "
            f"expected one of {', '.join(COMMAND_NAMES)}",
            file=sys.stderr,
        )
        sys.exit(1)
    return introspect_handler(command_name)


__all__ = ["COMMAND_NAMES", "register_commands", "get_handler"]
