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
            self.connection.execute("ROLLBACK TRANSACTION")
            raise

    @contextmanager
    def savepoint(self, name: Optional[str] = None):
        self._savepoint_counter += 1
        name = name or f"sp_{self._savepoint_counter}"
        yield
