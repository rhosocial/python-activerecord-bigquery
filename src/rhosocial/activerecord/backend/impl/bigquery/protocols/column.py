# src/rhosocial/activerecord/backend/impl/bigquery/protocols/column.py
"""BigQuery column qualification protocol."""

from typing import Any, Protocol, runtime_checkable, Tuple


@runtime_checkable
class BigQueryColumnQualificationSupport(Protocol):
    """How BigQuery qualifies a column reference.

    This is the one namespace rule in the family that is *not* "render what
    you were given". GoogleSQL has no ``dataset.column`` construct: a column
    is qualified by its relation -- ``table.column``, or the fully qualified
    ``project.dataset.table.column`` path when a query has to reach across
    datasets -- and the namespace belongs to the relation named in the FROM
    clause, not to the column.

    Stating that as a capability, rather than letting the formatter quietly
    leave a dataset out, is what makes the interesting case visible. When a
    column carries a dataset **and** a table, the rule above applies and the
    rendering is correct. When it carries a dataset and *no* table, there is no
    relation for the namespace to qualify, and the only two honest outcomes
    are to report it or to throw it away. Reporting it is what this backend
    does: a name the caller supplied must either appear in the SQL or be
    named in an error.
    """

    def supports_column_namespace_qualification(self) -> bool:
        """Whether a project or dataset on a column is rendered.

        ``False`` for BigQuery; see the class docstring.
        """
        ...  # pragma: no cover

    def format_column(self, expr: Any) -> Tuple[str, tuple]:
        """Format a column reference, qualified by its relation only.

        Raises:
            UnsupportedFeatureError: the column carries a namespace and no
                table to hang it on.
        """
        ...  # pragma: no cover