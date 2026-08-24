"""BigQuery transaction management."""
from contextlib import contextmanager
from typing import Optional


class BigQueryTransactionManager:
    def __init__(self, backend):
        self.connection = backend
        self._savepoint_counter = 0

    @contextmanager
    def transaction(self, isolation_level: Optional[str] = None):
        # BigQuery uses session-level transactions
        try:
            self.connection.execute("BEGIN TRANSACTION")
            yield self
            self.connection.execute("COMMIT TRANSACTION")
        except Exception:
            try:
                self.connection.execute("ROLLBACK TRANSACTION")
            except Exception:
                # The original exception must propagate; a backend that
                # rejects ROLLBACK (e.g. the emulator) should not mask it.
                import logging
                logging.getLogger(__name__).warning(
                    "Failed to roll back BigQuery transaction", exc_info=True
                )
            raise

    @contextmanager
    def savepoint(self, name: Optional[str] = None):
        self._savepoint_counter += 1
        name = name or f"sp_{self._savepoint_counter}"
        yield
