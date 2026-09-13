# src/rhosocial/activerecord/backend/impl/bigquery/mixins/identifier.py
"""BigQuery identifier formatting mixin."""


class BigQueryIdentifierMixin:
    """BigQuery identifier formatting using backtick quoting."""

    def format_identifier(self, identifier: str, need_quote: bool = True) -> str:
        """Format a BigQuery identifier using backtick quoting.

        Args:
            identifier: Raw identifier string.
            need_quote: Whether the identifier needs quoting. When False the
                identifier is returned unchanged (with a warning if it is a
                reserved word).
        """
        if not need_quote:
            if self.is_reserved_word(identifier):
                import warnings

                from rhosocial.activerecord.backend.warnings import (
                    IdentifierQuotingWarning,
                )

                warnings.warn(
                    f"Identifier '{identifier}' is a reserved word in {self.name} "
                    f"and may cause SQL errors without quoting.",
                    IdentifierQuotingWarning,
                    stacklevel=2,
                )
            return identifier
        escaped = identifier.replace("`", "``")
        return f"`{escaped}`"


__all__ = ['BigQueryIdentifierMixin']
