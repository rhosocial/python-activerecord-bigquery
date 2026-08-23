"""BigQuery synchronous backend implementation."""
import logging
from typing import Any, Dict, List, Optional, Tuple

from rhosocial.activerecord.backend.base import StorageBackend
from rhosocial.activerecord.backend.errors import (
    ConnectionError, DatabaseError, IntegrityError, QueryError,
)
from rhosocial.activerecord.backend.result import QueryResult

from .config import BigQueryConnectionConfig
from .dialect import BigQueryDialect
from .transaction import BigQueryTransactionManager


class BigQueryBackend(StorageBackend):
    """BigQuery-specific backend (synchronous)."""

    def __init__(self, **kwargs):
        version = kwargs.pop('version', None) or (3, 0, 0)
        if 'connection_config' not in kwargs or kwargs.get('connection_config') is None:
            config_params = {
                'project': kwargs.get('project'),
                'dataset': kwargs.get('dataset'),
                'location': kwargs.get('location'),
                'credentials_path': kwargs.get('credentials_path'),
                'credentials_json': kwargs.get('credentials_json'),
            }
            config_params = {k: v for k, v in config_params.items() if v is not None}
            kwargs['connection_config'] = BigQueryConnectionConfig(**config_params)
        super().__init__(**kwargs)
        self._version = version
        self._register_bigquery_adapters()

    def connect(self) -> None:
        try:
            from google.cloud import bigquery
            from google.auth.credentials import AnonymousCredentials
            from google.api_core.client_options import ClientOptions
            config = self.config
            endpoint = getattr(config, 'api_endpoint', None) or None
            use_anonymous = getattr(config, 'use_anonymous_credentials', False)
            client_options = ClientOptions(api_endpoint=endpoint) if endpoint else None
            if use_anonymous:
                self._client = bigquery.Client(
                    project=getattr(config, 'project', None) or 'test',
                    credentials=AnonymousCredentials(),
                    client_options=client_options,
                )
            elif getattr(config, 'credentials_path', None):
                self._client = bigquery.Client.from_service_account_json(
                    config.credentials_path,
                    client_options=client_options,
                )
            elif getattr(config, 'credentials_json', None):
                import json
                self._client = bigquery.Client.from_service_account_info(
                    config.credentials_json,
                    client_options=client_options,
                )
            else:
                project = getattr(config, 'project', None)
                self._client = bigquery.Client(
                    project=project,
                    client_options=client_options,
                )
            self._connected = True
            self.log(logging.INFO, "Connected to BigQuery")
        except Exception as e:
            raise ConnectionError(f"Failed to connect to BigQuery: {e}") from e

    def disconnect(self) -> None:
        if hasattr(self, '_client') and self._client:
            try:
                # BigQuery client doesn't require explicit close
                pass
            except Exception as e:
                self.log(logging.WARNING, f"Error disconnecting from BigQuery: {e}")
            finally:
                self._client = None
                self._connected = False

    def ping(self, reconnect: bool = True) -> bool:
        if not hasattr(self, '_client') or self._client is None:
            if reconnect:
                self.connect()
                return True
            return False
        try:
            from google.cloud import bigquery
            dataset_ref = self._client.dataset(getattr(self.config, 'dataset', None) or 'default')
            list(self._client.list_dataset_refs(dataset_ref))
            return True
        except Exception:
            if reconnect:
                try:
                    self.disconnect()
                    self.connect()
                    return True
                except Exception:
                    return False
            return False

    def _handle_error(self, error: Exception) -> None:
        category = self._classify_error(error)
        if category == 'connection':
            raise ConnectionError(str(error)) from error
        elif category == 'integrity':
            raise IntegrityError(str(error)) from error
        elif category == 'query':
            raise QueryError(str(error)) from error
        else:
            raise DatabaseError(str(error)) from error

    def get_server_version(self) -> Tuple[int, ...]:
        return self._version

    def introspect_and_adapt(self) -> None:
        pass

    @property
    def transaction_manager(self):
        return BigQueryTransactionManager(self)

    @property
    def dialect(self) -> BigQueryDialect:
        return BigQueryDialect(version=self._version)

    def execute(self, sql: str, params: Optional[Tuple] = None, returning: Optional[Any] = None, column_adapters: Optional[Dict] = None) -> QueryResult:
        from rhosocial.activerecord.backend.result import QueryResult
        try:
            job = self._client.query(sql, job_config=None)
            result = job.result()
            rows = [tuple(row.values()) for row in result]
            return QueryResult(rows=rows)
        except Exception as e:
            self._handle_error(e)

    def get_default_adapter_suggestions(self) -> Dict:
        return {
            dict: (self.adapter_registry.get_adapter(dict, str) or self.adapter_registry.get_adapter(dict, dict), str),
        }

    def _register_bigquery_adapters(self):
        from .adapters import (
            BigQueryStructAdapter, BigQueryArrayAdapter,
            BigQueryJSONAdapter, BigQueryDecimalAdapter,
            BigQueryTimestampAdapter,
        )
        for adapter in [
            BigQueryStructAdapter(), BigQueryArrayAdapter(),
            BigQueryJSONAdapter(), BigQueryDecimalAdapter(),
            BigQueryTimestampAdapter(),
        ]:
            for py_type, driver_types in adapter.supported_types.items():
                for driver_type in driver_types:
                    self.adapter_registry.register(adapter, py_type, driver_type, allow_override=True)
