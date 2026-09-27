# src/rhosocial/activerecord/backend/impl/bigquery/materialized_view_options.py
"""BigQuery materialized view ``OPTIONS(...)`` catalogue.

BigQuery configures a materialized view through a fixed, documented option set
(``materialized_view_option_list`` in the GoogleSQL DDL reference). The names
are enumerated here so callers validate against the catalogue instead of
emitting arbitrary option names.

Reference:
- CREATE MATERIALIZED VIEW: https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language#create_materialized_view_statement
"""
from enum import Enum
from typing import Any, Dict, Optional, Tuple


__all__ = [
    "BigQueryMaterializedViewOption",
    "BigQueryMaterializedViewOptionValueType",
    "resolve_materialized_view_option",
    "validate_materialized_view_options",
]


class BigQueryMaterializedViewOptionValueType(Enum):
    """Value type of a materialized view option."""

    BOOLEAN = "boolean"
    FLOAT64 = "float64"
    INT64 = "int64"
    INTERVAL = "interval"
    TIMESTAMP = "timestamp"
    STRING = "string"
    LABEL_ARRAY = "label_array"


class BigQueryMaterializedViewOption(str, Enum):
    """Options accepted by ``CREATE`` / ``ALTER MATERIALIZED VIEW``.

    The string value is the exact BigQuery option name.

    Example:
        >>> from rhosocial.activerecord.backend.impl.bigquery import (
        ...     BigQueryMaterializedViewOption as O,
        ... )
        >>> O.ENABLE_REFRESH.value
        'enable_refresh'
        >>> O("refresh_interval_minutes") is O.REFRESH_INTERVAL_MINUTES
        True
    """

    ENABLE_REFRESH = "enable_refresh"
    REFRESH_INTERVAL_MINUTES = "refresh_interval_minutes"
    EXPIRATION_TIMESTAMP = "expiration_timestamp"
    MAX_STALENESS = "max_staleness"
    ALLOW_NON_INCREMENTAL_DEFINITION = "allow_non_incremental_definition"
    KMS_KEY_NAME = "kms_key_name"
    FRIENDLY_NAME = "friendly_name"
    DESCRIPTION = "description"
    LABELS = "labels"
    TAGS = "tags"

    @property
    def value_type(self) -> BigQueryMaterializedViewOptionValueType:
        """The value type BigQuery expects for this option."""
        return _VALUE_TYPES[self]

    @property
    def default(self) -> Optional[str]:
        """Documented default, as text; ``None`` when there is no default."""
        return _DEFAULTS.get(self)


_VALUE_TYPES: Dict[BigQueryMaterializedViewOption, BigQueryMaterializedViewOptionValueType] = {
    BigQueryMaterializedViewOption.ENABLE_REFRESH:
        BigQueryMaterializedViewOptionValueType.BOOLEAN,
    BigQueryMaterializedViewOption.REFRESH_INTERVAL_MINUTES:
        BigQueryMaterializedViewOptionValueType.FLOAT64,
    BigQueryMaterializedViewOption.EXPIRATION_TIMESTAMP:
        BigQueryMaterializedViewOptionValueType.TIMESTAMP,
    BigQueryMaterializedViewOption.MAX_STALENESS:
        BigQueryMaterializedViewOptionValueType.INTERVAL,
    BigQueryMaterializedViewOption.ALLOW_NON_INCREMENTAL_DEFINITION:
        BigQueryMaterializedViewOptionValueType.BOOLEAN,
    BigQueryMaterializedViewOption.KMS_KEY_NAME:
        BigQueryMaterializedViewOptionValueType.STRING,
    BigQueryMaterializedViewOption.FRIENDLY_NAME:
        BigQueryMaterializedViewOptionValueType.STRING,
    BigQueryMaterializedViewOption.DESCRIPTION:
        BigQueryMaterializedViewOptionValueType.STRING,
    BigQueryMaterializedViewOption.LABELS:
        BigQueryMaterializedViewOptionValueType.LABEL_ARRAY,
    BigQueryMaterializedViewOption.TAGS:
        BigQueryMaterializedViewOptionValueType.LABEL_ARRAY,
}

# Defaults documented by Google. Only defaults that pin behaviour are recorded;
# options that are simply "not set" are left out.
_DEFAULTS: Dict[BigQueryMaterializedViewOption, str] = {
    BigQueryMaterializedViewOption.ENABLE_REFRESH: "true",
    BigQueryMaterializedViewOption.REFRESH_INTERVAL_MINUTES: "30",
}


def resolve_materialized_view_option(name: Any) -> Optional[BigQueryMaterializedViewOption]:
    """Resolve an option from an enum member or its BigQuery name.

    Args:
        name: A :class:`BigQueryMaterializedViewOption` member or its string value.

    Returns:
        The matching member, or ``None`` when the name is not a documented option.
    """
    if isinstance(name, BigQueryMaterializedViewOption):
        return name
    if isinstance(name, str):
        try:
            return BigQueryMaterializedViewOption(name)
        except ValueError:
            return None
    return None


def validate_materialized_view_options(
    options: Any,
    field_name: str = "options",
) -> Tuple[BigQueryMaterializedViewOption, ...]:
    """Validate option names against the documented catalogue.

    Args:
        options: Mapping of option name (or enum member) to value.
        field_name: Field name used in error messages.

    Returns:
        The resolved members, in input order.

    Raises:
        ValueError: If a name is not a documented materialized view option.
    """
    if not isinstance(options, dict):
        raise TypeError(f"{field_name} must be a dict of option name to value")
    resolved = []
    for name in options:
        option = resolve_materialized_view_option(name)
        if option is None:
            raise ValueError(
                f"{field_name} contains an option BigQuery does not document for "
                f"materialized views: {name!r}. Valid options: "
                f"{', '.join(o.value for o in BigQueryMaterializedViewOption)}"
            )
        resolved.append(option)
    return tuple(resolved)
