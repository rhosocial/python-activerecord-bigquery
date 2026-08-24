"""BigQuery async transaction management."""
from contextlib import asynccontextmanager
from typing import Optional


class AsyncBigQueryTransactionManager:
    def __init__(self, backend):
        self.connection = backend
        self._savepoint_counter = 0

    @asynccontextmanager
    async def transaction(self, isolation_level: Optional[str] = None):
        try:
            await self.connection.execute("BEGIN TRANSACTION")
            yield self
            await self.connection.execute("COMMIT TRANSACTION")
        except Exception:
            try:
                await self.connection.execute("ROLLBACK TRANSACTION")
            except Exception:
                # The original exception must propagate; a backend that
                # rejects ROLLBACK (e.g. the emulator) should not mask it.
                import logging
                logging.getLogger(__name__).warning(
                    "Failed to roll back BigQuery transaction", exc_info=True
                )
            raise

    @asynccontextmanager
    async def savepoint(self, name: Optional[str] = None):
        self._savepoint_counter += 1
        name = name or f"sp_{self._savepoint_counter}"
        yield
