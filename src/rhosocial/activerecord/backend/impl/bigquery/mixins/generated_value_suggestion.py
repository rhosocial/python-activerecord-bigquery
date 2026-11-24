# src/rhosocial/activerecord/backend/impl/bigquery/mixins/generated_value_suggestion.py
"""BigQueryGeneratedValueSuggestionMixin -- BigQuery's generated-value suggestion.

BigQuery declares identity-column support through
``BigQueryIdentityColumnMixin.supports_identity_column()``; this mixin supplies
the matching suggestion. The answer is the backend's own spelling, rendered by
the returned clause's formatter (``format_identity_clause`` in
``BigQueryIdentityColumnMixin``), so nothing is rendered here.

Deliberately a plain class, like the other suggestion mixins: a protocol
subclass would intercept ``super().__init__()`` and leave ``strict_validation``
unset on a fully constructed dialect.
"""
from typing import TYPE_CHECKING

from rhosocial.activerecord.backend.suggestion import GeneratedValueSuggestion

from ....expression.statements import IdentityClause

if TYPE_CHECKING:  # pragma: no cover
    from ....expression.types import DataType


class BigQueryGeneratedValueSuggestionMixin:
    """Suggest BigQuery's ``GENERATED ... AS IDENTITY`` for a generated key."""

    def suggest_generated_value(self, default_type: "DataType") -> GeneratedValueSuggestion:
        return GeneratedValueSuggestion(
            state="generate",
            storage_type=default_type,
            clause=IdentityClause(self),
        )


__all__ = ["BigQueryGeneratedValueSuggestionMixin"]
