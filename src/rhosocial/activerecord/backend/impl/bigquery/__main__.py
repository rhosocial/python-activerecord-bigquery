# src/rhosocial/activerecord/backend/impl/bigquery/__main__.py
"""BigQuery backend command-line interface.

Parses ``rhosocial-activerecord-bigquery <command> [options]`` and
dispatches to the handler :mod:`~.cli` resolved. The five introspection
commands are ``tables``, ``views``, ``table``, ``columns`` and
``datasets``; ``--help`` lists them with the environment variables each
connection flag reads.
"""

import argparse
import sys


def main():
    """Main CLI entry point for the BigQuery backend."""
    parser = argparse.ArgumentParser(
        prog="rhosocial-activerecord-bigquery",
        description=(
            "Introspect a BigQuery project: datasets, tables, views and "
            "columns, from the INFORMATION_SCHEMA views."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Connection flags read the environment: BIGQUERY_PROJECT, "
            "BIGQUERY_DATASET, BIGQUERY_LOCATION, BIGQUERY_CREDENTIALS_PATH "
            "(or GOOGLE_APPLICATION_CREDENTIALS), BIGQUERY_CREDENTIALS_JSON, "
            "BIGQUERY_API_ENDPOINT."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version="rhosocial-activerecord-bigquery 1.0.0.dev1",
    )

    from .cli import COMMAND_NAMES, get_handler, register_commands

    subparsers = parser.add_subparsers(dest="command")
    register_commands(subparsers)

    args = parser.parse_args()

    if args.command is None:
        print(
            f"Error: Please specify a command: {', '.join(COMMAND_NAMES)}",
            file=sys.stderr,
        )
        print("Use --help for more information.", file=sys.stderr)
        sys.exit(1)

    handler = get_handler(args.command)
    handler(args)


if __name__ == "__main__":
    main()
