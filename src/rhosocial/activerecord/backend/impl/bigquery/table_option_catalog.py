# src/rhosocial/activerecord/backend/impl/bigquery/table_option_catalog.py
"""BigQuery table ``OPTIONS(...)`` catalogue used by ``ALTER TABLE SET OPTIONS``.

The official DDL reference enumerates a closed ``table_set_options_list``: each
``NAME`` has one documented ``VALUE`` shape. The names are recorded here so the
formatter can refuse an option BigQuery does not document for a table by name
instead of emitting it. Materialized-view options (``enable_refresh`` and
friends) are a different list and are deliberately absent.

Reference (fetched 2026-11-25):
https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language#alter_table_set_options_statement
"""
from enum import Enum
from typing import Dict, Optional

__all__ = [
    "BigQueryTableOption",
    "BigQueryTableOptionValueKind",
    "DEFAULT_ROUNDING_MODES",
    "FILE_FORMATS",
    "INTERVAL_PARTS",
    "TABLE_FORMATS",
    "resolve_table_option",
]


class BigQueryTableOptionValueKind(str, Enum):
    """Value shape BigQuery documents for a table option.

    A ``str`` enum whose ``__str__`` is ``str.__str__``: a member is the word it
    carries, so it interpolates as that word and travels as a plain JSON string.
    """

    __str__ = str.__str__

    STRING = "string"
    BOOLEAN = "boolean"
    NUMBER = "number"
    TIMESTAMP = "timestamp"
    INTERVAL = "interval"
    LABEL_ARRAY = "label_array"


class BigQueryTableOption(str, Enum):
    """Options documented for ``ALTER TABLE ... SET OPTIONS``.

    The string value is the exact BigQuery option name.
    """

    __str__ = str.__str__

    EXPIRATION_TIMESTAMP = "expiration_timestamp"
    PARTITION_EXPIRATION_DAYS = "partition_expiration_days"
    REQUIRE_PARTITION_FILTER = "require_partition_filter"
    KMS_KEY_NAME = "kms_key_name"
    FRIENDLY_NAME = "friendly_name"
    DESCRIPTION = "description"
    LABELS = "labels"
    DEFAULT_ROUNDING_MODE = "default_rounding_mode"
    ENABLE_CHANGE_HISTORY = "enable_change_history"
    MAX_STALENESS = "max_staleness"
    ENABLE_FINE_GRAINED_MUTATIONS = "enable_fine_grained_mutations"
    STORAGE_URI = "storage_uri"
    FILE_FORMAT = "file_format"
    TABLE_FORMAT = "table_format"
    TAGS = "tags"

    @property
    def value_kind(self) -> BigQueryTableOptionValueKind:
        """The documented value shape for this option."""
        return _VALUE_KINDS[self]


_VALUE_KINDS: Dict[BigQueryTableOption, BigQueryTableOptionValueKind] = {
    BigQueryTableOption.EXPIRATION_TIMESTAMP: BigQueryTableOptionValueKind.TIMESTAMP,
    BigQueryTableOption.PARTITION_EXPIRATION_DAYS: BigQueryTableOptionValueKind.NUMBER,
    BigQueryTableOption.REQUIRE_PARTITION_FILTER: BigQueryTableOptionValueKind.BOOLEAN,
    BigQueryTableOption.KMS_KEY_NAME: BigQueryTableOptionValueKind.STRING,
    BigQueryTableOption.FRIENDLY_NAME: BigQueryTableOptionValueKind.STRING,
    BigQueryTableOption.DESCRIPTION: BigQueryTableOptionValueKind.STRING,
    BigQueryTableOption.LABELS: BigQueryTableOptionValueKind.LABEL_ARRAY,
    BigQueryTableOption.DEFAULT_ROUNDING_MODE: BigQueryTableOptionValueKind.STRING,
    BigQueryTableOption.ENABLE_CHANGE_HISTORY: BigQueryTableOptionValueKind.BOOLEAN,
    BigQueryTableOption.MAX_STALENESS: BigQueryTableOptionValueKind.INTERVAL,
    BigQueryTableOption.ENABLE_FINE_GRAINED_MUTATIONS: BigQueryTableOptionValueKind.BOOLEAN,
    BigQueryTableOption.STORAGE_URI: BigQueryTableOptionValueKind.STRING,
    BigQueryTableOption.FILE_FORMAT: BigQueryTableOptionValueKind.STRING,
    BigQueryTableOption.TABLE_FORMAT: BigQueryTableOptionValueKind.STRING,
    BigQueryTableOption.TAGS: BigQueryTableOptionValueKind.LABEL_ARRAY,
}

#: The documented closed value sets of the three enum-shaped STRING options.
DEFAULT_ROUNDING_MODES = frozenset({"ROUND_HALF_AWAY_FROM_ZERO", "ROUND_HALF_EVEN"})
FILE_FORMATS = frozenset({"PARQUET"})
TABLE_FORMATS = frozenset({"ICEBERG"})

#: INTERVAL is spelled ``INTERVAL <string> <qualifier>`` (for example
#: ``INTERVAL "4:0:0" HOUR TO SECOND``). Only documented date/time parts are
#: accepted as the qualifier, so it can never carry arbitrary SQL text.
INTERVAL_PARTS = frozenset({"YEAR", "MONTH", "DAY", "HOUR", "MINUTE", "SECOND"})


def resolve_table_option(name: object) -> Optional[BigQueryTableOption]:
    """Resolve an option from an enum member or its BigQuery name.

    Returns ``None`` when the name is not a documented table option; the
    formatter names the refusal rather than emitting an unknown option.
    """
    if isinstance(name, BigQueryTableOption):
        return name
    if isinstance(name, str):
        try:
            return BigQueryTableOption(name)
        except ValueError:
            return None
    return None
