# src/rhosocial/activerecord/backend/impl/bigquery/mixins/generated_value_suggestion.py
"""BigQueryGeneratedValueSuggestionMixin -- BigQuery's generated-value suggestion.

An ``Optional[int]`` single-column primary key is inferred by core as a
database-generated key. On BigQuery that inference does not hold: ``INT64``
primary keys are supplied by the client (the key is chiefly a clustering /
streaming-ordering device), and BigQuery does not generate them by default.
The documented Preview ``GENERATED ... AS IDENTITY`` clause exists and is
rendered by ``BigQueryIdentityColumnMixin.format_identity_clause`` when a
column clause is explicitly requested, but it is not the default answer for
an inferred key.

Returning ``no-action`` therefore keeps the portable column baseline plain
(``INT64 PRIMARY KEY``). The core consumer degrades an inferred identity to a
plain column on ``no-action``; only an explicitly declared ``IdentityAttribute``
that cannot be honoured raises. An explicit identity request is still rendered
through the expression-layer ``IdentityClause`` channel, independent of this
suggestion.

Deliberately a plain class, like the other suggestion mixins: a protocol
subclass would intercept ``super().__init__()`` and leave ``strict_validation``
unset on a fully constructed dialect.
"""
from typing import TYPE_CHECKING

from rhosocial.activerecord.backend.suggestion import GeneratedValueSuggestion

if TYPE_CHECKING:  # pragma: no cover
    from ....expression.types import DataType


class BigQueryGeneratedValueSuggestionMixin:
    """Decline a generated value for an inferred key; keep the column plain."""

    def suggest_generated_value(self, default_type: "DataType") -> GeneratedValueSuggestion:
        return GeneratedValueSuggestion(state="no-action")


__all__ = ["BigQueryGeneratedValueSuggestionMixin"]
