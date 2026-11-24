# src/rhosocial/activerecord/backend/impl/bigquery/mixins/index.py
"""BigQuery index DDL capability.

BigQuery has **no plain ``CREATE INDEX`` / ``DROP INDEX`` statement**.
The DDL reference's index productions are a different statement family:

* ``CREATE SEARCH INDEX [ IF NOT EXISTS ] index_name ON table_name
  ( { ALL COLUMNS [ WITH COLUMN OPTIONS (...) ] | column [, ...] } )
  [ OPTIONS ( index_option_list ) ]``
* ``DROP SEARCH INDEX [ IF EXISTS ] index_name ON table_name``
* ``ALTER SEARCH INDEX [ IF EXISTS ] index_name ON table_name alter_action
  [, ...] [ REBUILD ]``

There is also a preview ``CREATE AI INDEX [ IF NOT EXISTS ] index_name ON
table_name ( { AUTO COLUMNS | column_name [, ...] } )`` /
``DROP AI INDEX [ IF EXISTS ] index_name ON table_name`` family.

None of those statements is modelled by core's ``CreateIndexStatement``,
``DropIndexStatement`` or ``IndexDefinition``: those classes spell the plain
index form, and their grammar has no ``ON``-table search-index shape, no
``ALL COLUMNS`` / ``WITH COLUMN OPTIONS`` clause, and no ``REBUILD`` action.
This module therefore invents no SEARCH INDEX or AI INDEX support.  Every
plain-index probe answers ``False`` and both statement formatters refuse by
name rather than emit SQL the service rejects.  A caller that needs a search
index or an AI index must issue raw SQL until a dedicated expression node
exists for that family.

References (fetched 2026-11-25):
https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language#create_search_index_statement
https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language#drop_search_index
https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language#alter_search_index_statement
"""

from typing import TYPE_CHECKING, Tuple

from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError

if TYPE_CHECKING:  # pragma: no cover
    from rhosocial.activerecord.backend.expression.statements import (
        CreateIndexStatement,
        DropIndexStatement,
    )


class BigQueryIndexMixin:
    """Plain-index answers for a dialect whose index DDL uses another family."""

    def supports_create_index(self) -> bool:
        """Whether ``CREATE INDEX`` is supported.

        ``False``: the DDL reference contains no plain ``CREATE INDEX``
        production at all.  ``CREATE SEARCH INDEX`` and the preview
        ``CREATE AI INDEX`` are different statements with their own grammar,
        and this expression does not model either.  The formatter refuses by
        name.

        Reference (fetched 2026-11-25):
        https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language#create_search_index_statement
        """
        return False

    def supports_unique_index(self) -> bool:
        """Whether ``UNIQUE INDEX`` is supported.

        ``False``: there is no ``CREATE INDEX`` production, so there is no
        position for a ``UNIQUE`` qualifier.  Uniqueness is expressed by
        ``PRIMARY KEY`` / ``FOREIGN KEY`` table constraints, not by an index.
        """
        return False

    def supports_index_if_not_exists(self) -> bool:
        """Whether ``CREATE INDEX IF NOT EXISTS`` is supported.

        ``False``: ``IF NOT EXISTS`` exists only on ``CREATE SEARCH INDEX``
        and ``CREATE AI INDEX``, neither of which this dialect models.
        """
        return False

    def supports_index_type(self) -> bool:
        """Whether ``CREATE INDEX ... USING <type>`` is supported.

        ``False``: there is no ``CREATE INDEX`` production, and the
        search-index family has no ``USING`` clause.
        """
        return False

    def supports_partial_index(self) -> bool:
        """Whether ``CREATE INDEX ... WHERE`` (partial index) is supported.

        ``False``: there is no ``CREATE INDEX`` production, and no search-index
        statement carries a ``WHERE`` clause.
        """
        return False

    def supports_functional_index(self) -> bool:
        """Whether an index over an expression is supported.

        ``False``: there is no ``CREATE INDEX`` production.  A search index
        lists columns and per-column options; it has no expression position.
        """
        return False

    def supports_index_include(self) -> bool:
        """Whether ``CREATE INDEX ... INCLUDE (...)`` is supported.

        ``False``: there is no ``CREATE INDEX`` production, and the
        search-index family has no ``INCLUDE`` clause.
        """
        return False

    def supports_index_tablespace(self) -> bool:
        """Whether ``CREATE INDEX ... TABLESPACE`` is supported.

        ``False``: BigQuery has no tablespaces at all, and no plain-index
        production to carry the clause.
        """
        return False

    def supports_concurrent_index(self) -> bool:
        """Whether ``CREATE INDEX CONCURRENTLY`` is supported.

        ``False``: ``CONCURRENTLY`` belongs to the plain-index production
        (PostgreSQL).  BigQuery has neither the production nor the keyword.
        """
        return False

    def supports_drop_index(self) -> bool:
        """Whether ``DROP INDEX`` is supported.

        ``False``: the DDL reference contains no plain ``DROP INDEX``
        production.  ``DROP SEARCH INDEX [ IF EXISTS ] index_name ON
        table_name`` and the preview ``DROP AI INDEX`` are different
        statements, and this expression does not model either.  The formatter
        refuses by name.

        Reference (fetched 2026-11-25):
        https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language#drop_search_index
        """
        return False

    def supports_index_if_exists(self) -> bool:
        """Whether ``DROP INDEX IF EXISTS`` is supported.

        ``False``: ``IF EXISTS`` exists only on ``DROP SEARCH INDEX`` and the
        preview ``DROP AI INDEX``, neither of which this dialect models.
        """
        return False

    def supports_drop_index_on_table(self) -> bool:
        """Whether ``DROP INDEX`` takes an ``ON <table>`` suffix.

        ``False`` for the plain statement, because there is no plain
        ``DROP INDEX``.  The ``ON table_name`` spelling belongs to
        ``DROP SEARCH INDEX`` / ``DROP AI INDEX``, a family this dialect does
        not model.
        """
        return False

    def supports_fulltext_index(self) -> bool:
        """Whether a ``FULLTEXT INDEX`` clause exists.

        ``False``: BigQuery has no ``FULLTEXT`` index clause.  Full-text
        search is served by ``CREATE SEARCH INDEX`` plus the ``SEARCH``
        function; the statement family is not this expression's.
        """
        return False

    def supports_inline_index(self) -> bool:
        """Whether ``CREATE TABLE`` accepts inline index definitions.

        ``False``: the ``CREATE TABLE`` grammar has no index definition
        branch.  Core's renderer refuses an expression carrying ``indexes``
        regardless, and this local declaration keeps the answer from moving
        with a core default.
        """
        return False

    def format_create_index_statement(
        self, expr: "CreateIndexStatement"
    ) -> Tuple[str, tuple]:
        """Refuse the plain ``CREATE INDEX`` statement by name.

        Raises:
            UnsupportedFeatureError: always on this dialect.  None of the
                search-index / AI-index family is being emitted here.
        """
        if not self.supports_create_index():
            raise UnsupportedFeatureError(
                self.name,
                "CREATE INDEX",
                "BigQuery has no CREATE INDEX statement. Its only index DDL "
                "is CREATE SEARCH INDEX (and the preview CREATE AI INDEX), a "
                "different statement with ON <table> syntax that this backend "
                "does not model.",
            )
        return super().format_create_index_statement(expr)

    def format_drop_index_statement(
        self, expr: "DropIndexStatement"
    ) -> Tuple[str, tuple]:
        """Refuse the plain ``DROP INDEX`` statement by name.

        Raises:
            UnsupportedFeatureError: always on this dialect.  None of the
                search-index / AI-index family is being emitted here.
        """
        if not self.supports_drop_index():
            raise UnsupportedFeatureError(
                self.name,
                "DROP INDEX",
                "BigQuery has no DROP INDEX statement. Its only index DDL is "
                "DROP SEARCH INDEX (and the preview DROP AI INDEX), a "
                "different statement with ON <table> syntax that this backend "
                "does not model.",
            )
        return super().format_drop_index_statement(expr)


__all__ = ["BigQueryIndexMixin"]
