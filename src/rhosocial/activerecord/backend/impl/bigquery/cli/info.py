# src/rhosocial/activerecord/backend/impl/bigquery/cli/info.py
"""info subcommand - Display BigQuery environment information.

The info command is connection-free: it reports the backend's configured
feature-level version (never queried from a server), the protocol/capability
matrix and the suggestion support of a locally constructed dialect. BigQuery
does not expose server variables through this backend, so the server section
is reported as unsupported rather than filled by a database query.
"""

import argparse
import json
from typing import Any, Dict, List

from rhosocial.activerecord.backend.dialect import capabilities as _cap
from rhosocial.activerecord.backend.dialect.protocols import (
    AdvancedGroupingSupport,
    ArraySupport,
    ConstraintSupport,
    CreateSchemaSupport,
    CreateTableSupport,
    CTESupport,
    DataTypeSupport,
    DqlOrderSupport,
    ExplainSupport,
    FilterClauseSupport,
    IndexObjectSupport,
    IntrospectionSupport,
    JoinSupport,
    JSONSupport,
    LateralJoinSupport,
    MergeSupport,
    NamespaceSupport,
    OrderedSetAggregationSupport,
    QualifyClauseSupport,
    ReturningSupport,
    SchemaNameSupport,
    SetOperationSupport,
    TableObjectSupport,
    TimestampSupport,
    TransactionControlSupport,
    TruncateSupport,
    UpsertSupport,
    ViewObjectSupport,
    WindowFunctionSupport,
)

from rhosocial.activerecord.backend.impl.bigquery.protocols import (
    BigQueryArraySupport,
    BigQueryColumnQualificationSupport,
    BigQueryGeographySupport,
    BigQueryJSONSupport,
    BigQueryMaterializedViewSupport,
    BigQuerySchemaSupport,
    BigQueryStructSupport,
)

from .output import RICH_AVAILABLE

# info only supports table and json output (csv/tsv are not suitable for the
# nested capability structures this command prints).
OUTPUT_CHOICES = ["table", "json"]

# Groups whose protocols are declared by this backend rather than by core.
DIALECT_SPECIFIC_GROUPS = {"BigQuery-specific"}

# The protocol family groups reported by the capability matrix. This is a
# reasonable subset of the re-exports in
# ``rhosocial.activerecord.backend.dialect.protocols`` plus the BigQuery-only
# protocols. Supported protocols keep their true origin (reuse/override);
# BigQuery-specific ones are forced to "proprietary" by the shared helper.
PROTOCOL_FAMILY_GROUPS: Dict[str, list] = {
    "Query Features": [
        WindowFunctionSupport,
        CTESupport,
        FilterClauseSupport,
        SetOperationSupport,
        AdvancedGroupingSupport,
        QualifyClauseSupport,
        DqlOrderSupport,
    ],
    "JOIN Support": [JoinSupport, LateralJoinSupport],
    "Data Types": [JSONSupport, ArraySupport, DataTypeSupport, TimestampSupport],
    "DML Features": [
        ReturningSupport,
        UpsertSupport,
        MergeSupport,
        OrderedSetAggregationSupport,
    ],
    "Transaction Control": [TransactionControlSupport],
    "Query Analysis": [ExplainSupport],
    "Named objects": [
        TableObjectSupport,
        ViewObjectSupport,
        NamespaceSupport,
        SchemaNameSupport,
    ],
    "DDL": [
        CreateSchemaSupport,
        CreateTableSupport,
        IndexObjectSupport,
        ConstraintSupport,
        TruncateSupport,
    ],
    "Introspection": [IntrospectionSupport],
    "BigQuery-specific": [
        BigQueryStructSupport,
        BigQueryArraySupport,
        BigQueryJSONSupport,
        BigQueryGeographySupport,
        BigQuerySchemaSupport,
        BigQueryColumnQualificationSupport,
        BigQueryMaterializedViewSupport,
    ],
}

# No support probe here needs parameterised arguments, so the shared helper
# evaluates zero-argument probes only.
SUPPORT_METHOD_ALL_ARGS: Dict[str, List[str]] = {}

# Source labels used in the JSON output, kept in English for user-facing text.
VERSION_SOURCE = "not queried from server (backend feature level, not a server version)"
SERVER_VARIABLES_SOURCE = "this backend does not expose server variables"


def create_parser(subparsers):
    """Create the info subcommand parser."""
    parser = subparsers.add_parser(
        "info",
        help="Display BigQuery environment information (no connection needed)",
        epilog="""Examples:
  # Show basic info
  %(prog)s info

  # Show detailed protocol support
  %(prog)s info -vv

  # Show info as JSON
  %(prog)s info -o json
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "-o",
        "--output",
        choices=OUTPUT_CHOICES,
        default="table",
        help="Output format (default: table)",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity. -v for families, -vv for details.",
    )

    parser.add_argument(
        "--rich-ascii",
        action="store_true",
        help="Use ASCII characters for rich table borders.",
    )

    return parser


def handle(args):
    """Handle the info subcommand.

    A backend is constructed locally but never connected, so the reported
    version is the configured feature level rather than a server response.
    Capabilities and suggestions are derived from that backend's dialect.
    """
    output_format = args.output if args.output != "table" or RICH_AVAILABLE else "json"

    from ..backend.backend import BigQueryBackend

    backend = BigQueryBackend()
    version_tuple = backend._version
    version_str = ".".join(map(str, version_tuple))
    dialect = backend.dialect

    capabilities = _cap.build_capability_report(
        dialect,
        family_groups=PROTOCOL_FAMILY_GROUPS,
        dialect_specific_groups=DIALECT_SPECIFIC_GROUPS,
        all_args=SUPPORT_METHOD_ALL_ARGS,
        verbose=args.verbose,
    )

    info: Dict[str, Any] = {
        "database": {
            "type": "bigquery",
            "version": version_str,
            "version_tuple": list(version_tuple),
            "version_source": VERSION_SOURCE,
        },
        "server": {
            "version": version_str,
            "variables": {},
            "source": SERVER_VARIABLES_SOURCE,
            "connected": False,
        },
        "features": {},
        "capabilities": capabilities,
        "suggestions": _cap.build_suggestion_report(dialect, args.verbose),
        # compatibility alias for one release cycle
        "protocols": capabilities,
    }

    if output_format == "json" or not RICH_AVAILABLE:
        print(json.dumps(info, indent=2))
    else:
        _display_info_rich(info, args.verbose, version_str, args.rich_ascii)

    return info


# ---------------------------------------------------------------------------
# Internal helper functions
# ---------------------------------------------------------------------------


def _display_info_rich(
    info: Dict[str, Any], verbose: int, version_str: str, ascii_borders: bool = False
) -> None:
    """Display the info report using rich."""
    from rich.console import Console

    console = Console(force_terminal=True, ascii_only=ascii_borders)

    sym_ok = "[OK]"
    sym_fail = "[X]"

    console.print("\n[bold cyan]BigQuery Environment Information[/bold cyan]\n")
    console.print(
        f"[bold]BigQuery Version:[/bold] {version_str} "
        "[yellow](not queried from server)[/yellow]\n"
    )

    server = info["server"]
    console.print("[bold green]Server Variables:[/bold green]")
    console.print(f"  [dim]Not available:[/dim] {server['source']}")
    console.print(f"  [dim]Connected:[/dim] {server['connected']}\n")

    label = "Detailed" if verbose >= 2 else "Family Overview"
    console.print(f"[bold green]Protocol Support ({label}):[/bold green]")

    for group_name, protocols in info["capabilities"].items():
        if group_name in DIALECT_SPECIFIC_GROUPS:
            console.print(
                f"\n  [bold underline]{group_name}:[/bold underline] [dim](dialect-specific)[/dim]"
            )
        else:
            console.print(f"\n  [bold underline]{group_name}:[/bold underline]")
        for protocol_name, stats in protocols.items():
            pct = stats["percentage"]
            if pct == 100:
                color, symbol = "green", sym_ok
            elif pct >= 50:
                color, symbol = "yellow", "[~]"
            elif pct > 0:
                color, symbol = "red", "[~]"
            else:
                color, symbol = "red", sym_fail

            bar_len = 20
            filled = int(pct / 100 * bar_len)
            bar = "#" * filled + "-" * (bar_len - filled)

            origin = stats.get("origin", "")
            origin_tag = f" [dim][{origin}][/dim]" if origin else ""
            console.print(
                f"    [{color}]{symbol}[/{color}] {protocol_name}{origin_tag}: "
                f"[{color}]{bar}[/{color}] {pct:.0f}% "
                f"({stats['supported']}/{stats['total']})"
            )

            if verbose >= 2 and "methods" in stats:
                for method, value in stats["methods"].items():
                    method_display = (
                        method.replace("supports_", "")
                        .replace("is_", "")
                        .replace("_available", "")
                        .replace("_", " ")
                    )
                    method_status = "[green][OK][/green]" if value else "[red][X][/red]"
                    console.print(f"        {method_status} {method_display}")

    suggestions = info.get("suggestions", {})
    if suggestions:
        console.print("\n[bold green]Suggestion Support:[/bold green]")
        for proto_name, entry in suggestions.items():
            supported = entry.get("supported", False)
            symbol = sym_ok if supported else sym_fail
            color = "green" if supported else "red"
            console.print(f"    [{color}]{symbol}[/{color}] {proto_name}")

    console.print()


__all__ = ["create_parser", "handle"]
