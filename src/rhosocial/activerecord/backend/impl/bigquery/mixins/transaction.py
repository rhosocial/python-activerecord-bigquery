# src/rhosocial/activerecord/backend/impl/bigquery/mixins/transaction.py
"""BigQuery transaction formatters.

BigQuery's transaction statements are ``BEGIN TRANSACTION``, ``COMMIT
TRANSACTION`` and ``ROLLBACK TRANSACTION``.  The grammar has no lock-wait
clause and no ``SET TRANSACTION``, while the expression layer's two
transaction expressions carry the ``wait`` / ``no_wait`` pair (Firebird's
grammar).  Both spellings are refused by name here instead of being silently
dropped by core's generic renderer.
"""
from typing import Tuple, TYPE_CHECKING

from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError

if TYPE_CHECKING:  # pragma: no cover
    from rhosocial.activerecord.backend.expression.transaction import (
        BeginTransactionExpression,
        SetTransactionExpression,
    )


class BigQueryTransactionMixin:
    """BigQuery transaction control formatting.

    Must be listed before core's ``TransactionControlMixin`` in
    ``BigQueryDialect`` so these formatters take precedence.
    """

    def supports_transaction_wait(self) -> bool:
        """Whether the transaction lock-wait clause (``WAIT`` / ``NO WAIT``) exists.

        ``False``: the transactions reference documents ``BEGIN TRANSACTION``,
        ``COMMIT TRANSACTION`` and ``ROLLBACK TRANSACTION``; the string
        ``WAIT`` does not occur on it, and neither does ``SET TRANSACTION``.
        The pair is carried by ``BeginTransactionExpression`` and
        ``SetTransactionExpression`` all the same, so both spellings are
        refused by name below rather than dropped.

        Reference (fetched 2026-10-08):
        https://cloud.google.com/bigquery/docs/reference/standard-sql/transactions
        """
        return False

    def format_begin_transaction(
        self, expr: "BeginTransactionExpression"
    ) -> Tuple[str, tuple]:
        """Format a BEGIN statement, refusing the wait pair by name.

        Renders ``BEGIN`` -- the backend's transaction manager executes the
        documented ``BEGIN TRANSACTION`` itself.  ``wait`` / ``no_wait`` are
        not silently droppable: with the probe ``False`` each requested
        spelling raises ``UnsupportedFeatureError`` naming it, and the render
        branch after the gate is what a subclass that declares the clause
        exercises.

        Raises:
            UnsupportedFeatureError: If a ``WAIT`` / ``NO WAIT`` spelling was
                requested and :meth:`supports_transaction_wait` declines it.
        """
        params = expr.get_params()
        wait = params.get("wait")
        no_wait = params.get("no_wait")
        parts = ["BEGIN"]
        if wait or no_wait:
            if not self.supports_transaction_wait():
                feature = "WAIT" if wait else "NO WAIT"
                raise UnsupportedFeatureError(
                    self.name, f"transaction {feature}",
                    f"{self.name} does not support the {feature} transaction clause.",
                )
            parts.append("WAIT" if wait else "NO WAIT")
        return " ".join(parts), ()

    def format_set_transaction(
        self, expr: "SetTransactionExpression"
    ) -> Tuple[str, tuple]:
        """Refuse ``SET TRANSACTION``; name the wait pair when it was requested.

        BigQuery has no ``SET TRANSACTION`` statement, so the fallback is
        core's statement-level ``NotImplementedError`` (pinned by the
        expression round-trip matrix).  A requested ``wait`` / ``no_wait`` is
        refused by name first: the caller learns which spelling BigQuery
        cannot express, with the missing statement named as the reason.

        Raises:
            UnsupportedFeatureError: If a ``WAIT`` / ``NO WAIT`` spelling was
                requested.
            NotImplementedError: Otherwise, for the absent statement.
        """
        params = expr.get_params()
        wait = params.get("wait")
        no_wait = params.get("no_wait")
        if wait or no_wait:
            feature = "WAIT" if wait else "NO WAIT"
            raise UnsupportedFeatureError(
                self.name, f"transaction {feature}",
                f"{self.name} has no SET TRANSACTION statement, so the "
                f"{feature} clause cannot be expressed.",
            )
        return super().format_set_transaction(expr)


__all__ = ['BigQueryTransactionMixin']
