# src/rhosocial/activerecord/backend/impl/bigquery/protocols/__init__.py
"""BigQuery protocol definitions.

One module per capability, which is the layout the other backends use and the
reason a protocol can be found by its name instead of by grepping a single
growing file.

BigQuery has two namespaces -- a **project** above and a **dataset** below --
and exactly one protocol declares them: core's
:class:`~rhosocial.activerecord.backend.dialect.protocols.NamespaceSupport`,
which asks both slots the same question and is therefore the same protocol.
This package used to carry a second one,
``BigQueryCatalogSupport``, declaring the same three switches and the same
``validate_catalog_name``. It duplicated ``NamespaceSupport`` member for member,
which under ``runtime_checkable`` structural matching made
``isinstance(dialect, BigQueryCatalogSupport)`` true of any dialect with those
methods -- it asserted nothing specific to BigQuery. The switches live on
:class:`~rhosocial.activerecord.backend.impl.bigquery.mixins.namespace.BigQueryNamespaceMixin`
and the protocol that remains is :class:`~.schema.BigQuerySchemaSupport`, which
answers the *other* question: ``CREATE SCHEMA`` / ``DROP SCHEMA``.

Whether ``CREATE PROJECT`` is a statement is a third question again, answered by
core's ``CreateDatabaseSupport``.

:mod:`.column` carries the rule that makes BigQuery different from every other
backend in the family: a column is qualified by its *relation* and never by a
namespace, so a dataset on a bare column has to be reported rather than
dropped.
"""

from .column import BigQueryColumnQualificationSupport
from .data_type import (
    BigQueryArraySupport,
    BigQueryGeographySupport,
    BigQueryJSONSupport,
    BigQueryStructSupport,
)
from .materialized_view import BigQueryMaterializedViewSupport
from .schema import BigQuerySchemaSupport

__all__ = [
    "BigQueryArraySupport",
    "BigQueryColumnQualificationSupport",
    "BigQueryGeographySupport",
    "BigQueryJSONSupport",
    "BigQueryMaterializedViewSupport",
    "BigQuerySchemaSupport",
    "BigQueryStructSupport",
]