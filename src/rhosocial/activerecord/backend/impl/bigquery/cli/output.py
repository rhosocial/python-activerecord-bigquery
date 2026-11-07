# src/rhosocial/activerecord/backend/impl/bigquery/cli/output.py
"""Output provider factory, the format lists, and display helpers.

Four formats, one factory: ``table`` renders through ``rich`` when it is
installed and falls back to ``json`` when it is not, because the table
renderer is an optional dependency and a missing one must degrade rather
than refuse the run. The lists a caller picks from live here too, beside
the factory that has to be able to produce every member of them.
"""

from rhosocial.activerecord.backend.output import (
    CsvOutputProvider,
    JsonOutputProvider,
    TsvOutputProvider,
)

try:
    from rhosocial.activerecord.backend.output_rich import RichOutputProvider

    RICH_AVAILABLE = True
except ImportError:  # pragma: no cover -- exercised only without rich
    RICH_AVAILABLE = False
    RichOutputProvider = None  # type: ignore[misc,assignment]


#: The output formats the introspect subcommand offers.
#:
#: The provider factory below is what makes them available: a format listed
#: here must map to a provider, and a provider nobody is offered is
#: unreachable. Defining the list once, beside the factory that has to be
#: able to produce every member, is what keeps "offered" and "producible"
#: from drifting apart -- a second spelling somewhere else would be
#: advertising an output the factory cannot build.
OUTPUT_CHOICES = ["table", "json", "csv", "tsv"]


def create_provider(output_format: str, ascii_borders: bool = False):
    """Return the output provider for one format.

    Args:
        output_format: One of ``table``, ``json``, ``csv``, ``tsv``.
        ascii_borders: Whether a rich table draws ASCII borders.

    Returns:
        The provider, or a JSON provider for an unknown format.
    """
    if output_format == "table" and not RICH_AVAILABLE:
        output_format = "json"

    if output_format == "table" and RICH_AVAILABLE:
        from rich.console import Console

        return RichOutputProvider(console=Console(), ascii_borders=ascii_borders)
    if output_format == "json":
        return JsonOutputProvider()
    if output_format == "csv":
        return CsvOutputProvider()
    if output_format == "tsv":
        return TsvOutputProvider()

    return JsonOutputProvider()


__all__ = ["OUTPUT_CHOICES", "create_provider", "RICH_AVAILABLE"]
