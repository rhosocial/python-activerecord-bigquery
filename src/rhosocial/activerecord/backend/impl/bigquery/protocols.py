"""BigQuery-specific protocol definitions."""
from typing import Protocol, runtime_checkable


@runtime_checkable
class BigQueryStructSupport(Protocol):
    def supports_struct(self) -> bool: ...


@runtime_checkable
class BigQueryArraySupport(Protocol):
    def supports_array(self) -> bool: ...


@runtime_checkable
class BigQueryJSONSupport(Protocol):
    def supports_json(self) -> bool: ...


@runtime_checkable
class BigQueryGeographySupport(Protocol):
    def supports_geography(self) -> bool: ...
