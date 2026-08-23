"""BigQuery-specific connection configuration."""
from dataclasses import dataclass
from typing import Optional, Dict, Any

from rhosocial.activerecord.backend.config import (
    ConnectionConfig,
    ConnectionPoolMixin,
    SSLMixin,
    CharsetMixin,
    TimezoneMixin,
    VersionMixin,
    LoggingMixin,
)


@dataclass
class BigQueryConnectionConfig(
    ConnectionConfig,
    ConnectionPoolMixin,
    SSLMixin,
    CharsetMixin,
    TimezoneMixin,
    VersionMixin,
    LoggingMixin,
):
    """BigQuery connection configuration."""

    project: Optional[str] = None
    dataset: Optional[str] = None
    location: Optional[str] = None
    credentials_path: Optional[str] = None
    credentials_json: Optional[Dict[str, Any]] = None
    # Emulator settings
    api_endpoint: Optional[str] = None  # e.g. http://localhost:9050 for bigquery-emulator
    use_anonymous_credentials: bool = False

    def to_dict(self) -> Dict[str, Any]:
        config_dict = super().to_dict()
        bq_params = {
            "project": self.project,
            "dataset": self.dataset,
            "location": self.location,
            "credentials_path": self.credentials_path,
            "credentials_json": self.credentials_json,
        }
        for key, value in bq_params.items():
            if value is not None:
                config_dict[key] = value
        return config_dict
