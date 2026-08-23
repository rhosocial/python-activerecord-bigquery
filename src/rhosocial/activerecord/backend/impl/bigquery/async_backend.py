"""BigQuery asynchronous backend implementation."""
from typing import Any, Dict, List, Optional, Tuple

from rhosocial.activerecord.backend.base import AsyncStorageBackend
from rhosocial.activerecord.backend.errors import ConnectionError, DatabaseError
from rhosocial.activerecord.backend.result import QueryResult

from .config import BigQueryConnectionConfig
from .dialect import BigQueryDialect
from .transaction import BigQueryTransactionManager


class AsyncBigQueryBackend(AsyncStorageBackend):
    """BigQuery native async backend."""

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

    async def connect(self) -> None:
        try:
            from google.cloud import bigquery
            config = self.config
            if getattr(config, 'credentials_path', None):
                self._client = bigquery.Client.from_service_account_json(config.credentials_path)
            elif getattr(config, 'credentials_json', None):
                import json
                self._client = bigquery.Client.from_service_account_info(config.credentials_json)
            else:
                project = getattr(config, 'project', None)
                self._client = bigquery.Client(project=project)
            self._connected = True
        except Exception as e:
            raise ConnectionError(f"Failed to connect to BigQuery: {e}") from e

    async def disconnect(self) -> None:
        if hasattr(self, '_client') and self._client:
            self._client = None
            self._connected = False

    async def ping(self, reconnect: bool = True) -> bool:
        if not hasattr(self, '_client') or self._client is None:
            if reconnect:
                await self.connect()
                return True
            return False
        try:
            dataset_ref = self._client.dataset(getattr(self.config, 'dataset', None) or 'default')
            list(self._client.list_dataset_refs(dataset_ref))
            return True
        except Exception:
            if reconnect:
                await self.disconnect()
                await self.connect()
                return True if self._client else False
            return False

    @property
    def transaction_manager(self):
        return BigQueryTransactionManager(self)

    @property
    def dialect(self) -> BigQueryDialect:
        return BigQueryDialect(version=self._version)

    async def execute(self, sql: str, params: Optional[Tuple] = None, returning: Optional[Any] = None, column_adapters: Optional[Dict] = None) -> QueryResult:
        try:
            job = self._client.query(sql, job_config=None)
            result = job.result()
            rows = [tuple(row.values()) for row in result]
            return QueryResult(rows=rows)
        except Exception as e:
            raise DatabaseError(str(e)) from e
