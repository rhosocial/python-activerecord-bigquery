# src/rhosocial/activerecord/backend/impl/bigquery/protocols/data_type.py
"""BigQuery data type capability protocols."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class BigQueryStructSupport(Protocol):
    """BigQuery has the native ``STRUCT`` type."""

    def supports_struct(self) -> bool: ...


@runtime_checkable
class BigQueryArraySupport(Protocol):
    """BigQuery has native arrays (``ARRAY<...>``)."""

    def supports_array(self) -> bool: ...


@runtime_checkable
class BigQueryJSONSupport(Protocol):
    """BigQuery has a native ``JSON`` type."""

    def supports_json(self) -> bool: ...


@runtime_checkable
class BigQueryGeographySupport(Protocol):
    """BigQuery has native ``GEOGRAPHY``."""

    def supports_geography(self) -> bool: ...