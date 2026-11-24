# src/rhosocial/activerecord/backend/impl/bigquery/mixins/general_suggestions.py
"""BigQuery's non-type production suggestions."""
from rhosocial.activerecord.backend.suggestion.definitions import (
    CreateTableLayoutSuggestion,
)
from rhosocial.activerecord.backend.suggestion.protocols import (
    CreateTableLayoutSuggestionSupport,
)


class BigQueryCreateTableLayoutSuggestionMixin(CreateTableLayoutSuggestionSupport):
    def suggest_create_table_layout(self) -> CreateTableLayoutSuggestion:
        # Assembled from the dialect's own probes: BigQuery has no inline index
        # clause (the core default answers False) but does carry a table comment
        # inline via OPTIONS(description=...).  Mixed capabilities mean the
        # indexes have to be emitted as separate statements, hence "split".
        inline_index = self.supports_inline_index()
        inline_comment = self.supports_table_comment()
        return CreateTableLayoutSuggestion(
            strategy="single" if inline_index and inline_comment else "split",
            inline_index=inline_index,
            inline_comment=inline_comment,
            state="actions",
        )


__all__ = ["BigQueryCreateTableLayoutSuggestionMixin"]
