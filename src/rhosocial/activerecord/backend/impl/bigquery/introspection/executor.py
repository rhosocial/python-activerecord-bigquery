# src/rhosocial/activerecord/backend/impl/bigquery/introspection/executor.py
"""Introspector executors for BigQuery.

The core executors run SQL through ``backend._get_cursor()`` because every
DB-API backend has a cursor. BigQuery has none: the backend talks to the
``google-cloud-bigquery`` client (or, for the emulator, a single REST call)
and returns a :class:`~rhosocial.activerecord.backend.result.QueryResult`
whose ``data`` is already a list of column-name → value dicts.

So these two subclasses exist for one reason: to run the statement through
``backend.execute()`` instead of inventing a cursor. Everything else — SQL
building, row parsing, caching — is the shared introspection code.
"""

from typing import Any, Dict, List, Tuple

from rhosocial.activerecord.backend.introspection.executor import (
    AsyncIntrospectorExecutor,
    SyncIntrospectorExecutor,
)


def _rows_from_result(result: Any) -> List[Dict[str, Any]]:
    """Return the rows of a ``QueryResult`` as a list of dicts.

    ``QueryResult.data`` is ``None`` for a statement that returned no result
    set. An introspection statement always selects, so that should not
    happen; returning an empty list keeps a surprising result from turning
    into an ``AttributeError`` deep inside a ``parse_*`` method.
    """
    data = getattr(result, "data", None)
    if not data:
        return []
    return list(data)


class SyncBigQueryIntrospectorExecutor(SyncIntrospectorExecutor):
    """Synchronous BigQuery executor: SQL in, list-of-dict rows out."""

    def execute(self, sql: str, params: Tuple = ()) -> List[Dict[str, Any]]:
        """Execute one introspection query through the backend.

        Args:
            sql: The statement built by the introspector.
            params: Positional parameters, using the dialect's ``?``
                placeholder.

        Returns:
            The result rows as column-name → value dicts.
        """
        result = self._backend.execute(sql, params)
        return _rows_from_result(result)


class AsyncBigQueryIntrospectorExecutor(AsyncIntrospectorExecutor):
    """Asynchronous BigQuery executor: SQL in, list-of-dict rows out."""

    async def execute(self, sql: str, params: Tuple = ()) -> List[Dict[str, Any]]:
        """Execute one introspection query through the async backend.

        Args:
            sql: The statement built by the introspector.
            params: Positional parameters, using the dialect's ``?``
                placeholder.

        Returns:
            The result rows as column-name → value dicts.
        """
        result = await self._backend.execute(sql, params)
        return _rows_from_result(result)


__all__ = [
    "SyncBigQueryIntrospectorExecutor",
    "AsyncBigQueryIntrospectorExecutor",
]
