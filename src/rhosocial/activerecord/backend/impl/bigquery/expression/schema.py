# src/rhosocial/activerecord/backend/impl/bigquery/expression/schema.py
"""
BigQuery schema resolution functions.

Provides SQL expression factories related to namespace resolution.

Follows the expression-dialect separation architecture:
- First parameter is always the dialect instance
- Returns an Expression object
- Does not concatenate SQL strings directly

BigQuery has no session-level current schema. A dataset is bound per query or
per connection config, not as server state that can be read back, so there is
nothing for a value function to return. Backends raise
UnsupportedFeatureError instead of guessing a dataset; see
BigQueryBackend.get_current_schema.
"""

from typing import TYPE_CHECKING

from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError

if TYPE_CHECKING:  # pragma: no cover
    from rhosocial.activerecord.backend.dialect import SQLDialectBase


def current_schema_unsupported(dialect: "SQLDialectBase") -> None:
    """Reject a current-schema query: BigQuery has no session-level schema.

    Args:
        dialect: The SQL dialect instance

    Raises:
        UnsupportedFeatureError: Always. BigQuery binds a dataset per query
            rather than exposing a readable current schema, so there is no
            value to return and none should be inferred from config.
    """
    raise UnsupportedFeatureError(
        dialect.name,
        "reading the current schema",
        "A dataset is bound per query rather than tracked as session state, so "
        "it cannot be read back from the server. Pass schema_name explicitly "
        "instead.",
    )
