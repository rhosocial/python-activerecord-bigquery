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

The generated value is reported as ``embedded-in-type``: the value lives in
the column's declared storage type, with no DDL clause appended, so the
portable baseline stays byte-for-byte ``INT64 PRIMARY KEY``. This is the
actionable answer that lets core accept both an inferred key and an explicit
``IdentityAttribute`` -- ``no-action`` is read by core as "not a generated
column" and makes an explicit declaration raise. The expression-layer
``IdentityClause`` / ``format_identity_clause`` path for an explicitly
requested clause remains independent of this suggestion.

Deliberately a plain class, like the other suggestion mixins: a protocol
subclass would intercept ``super().__init__()`` and leave ``strict_validation``
unset on a fully constructed dialect.
"""
from typing import TYPE_CHECKING

from rhosocial.activerecord.backend.suggestion import GeneratedValueSuggestion

if TYPE_CHECKING:  # pragma: no cover
    from ....expression.types import DataType


class BigQueryGeneratedValueSuggestionMixin:
    """Report the generated-value mechanism as embedded in the storage type."""

    def suggest_generated_value(self, default_type: "DataType") -> GeneratedValueSuggestion:
        """Keep the declared type and append no clause for a generated key.

        ``embedded-in-type`` keeps the rendered DDL identical to a plain
        column -- no IDENTITY clause -- while giving core an actionable answer
        for both inferred and explicitly declared integer keys.
        """
        return GeneratedValueSuggestion(
            state="embedded-in-type",
            storage_type=default_type,
        )


__all__ = ["BigQueryGeneratedValueSuggestionMixin"]
