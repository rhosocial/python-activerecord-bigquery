# src/rhosocial/activerecord/backend/impl/bigquery/mixins/namespace.py
"""BigQueryNamespaceMixin -- how a BigQuery name carries its two levels.

BigQuery's fully qualified name is ``project.dataset.table``. The shared
schema-object package fixes the slots by name, and BigQuery's two levels land
where two other engines' do: the project in ``catalog_name``, the dataset in
``schema_name``. Nothing here invents a fourth level or a BigQuery-specific
object subclass.

This is the backend's one naming-side mixin. It used to be called
``BigQueryCatalogMixin`` and sat beside ``BigQuerySchemaMixin``, with the
naming answers -- including ``supports_schema_qualification`` -- inside the one
named for the outer level, on the reasoning that with one resolvable level the
outer slot "is" the whole namespace. That reasoning does not survive contact
with the tree: BigQuery resolves *two* levels, the DDL question ("does the engine
have schemas, can it ``CREATE SCHEMA``") is a different one from the naming
question, and the naming question is already answered once for both slots by
core's ``NamespaceMixin``. One mixin, named for what it answers, holding only
what differs from core's default.

What is here, and why each is not just a ``True``
------------------------------------------------

* ``supports_catalog`` and ``supports_catalog_qualification`` are separate
  questions. BigQuery renders the project as a matter of course; PostgreSQL has
  a database and returns ``False`` for the second.
* ``supports_schema_qualification`` is the naming switch and not
  :meth:`supports_schema`, which lives on :class:`~.schema.BigQuerySchemaMixin`
  and answers the DDL question. An engine may answer the two differently.
* ``validate_catalog_name`` is the one place BigQuery is *stricter* than core's
  default, which accepts anything non-empty. A BigQuery path is
  ``project.dataset.table``, so ``project.table`` names nothing BigQuery can
  resolve.

``separator`` is left at core's default ``"."``, which is what BigQuery writes,
and ``format_qualified_name`` is not overridden: core's already spells the two
levels in the order BigQuery needs, because for a two-level engine the two
arrangements coincide. That is the whole reason no override is needed, and it is
why the mixin is this short.

Position in the base list is load-bearing
----------------------------------------

Core's ``NamespaceMixin`` supplies the defaults for all three switches, and C3
linearisation gives the *first* name in ``BigQueryDialect``'s base list
priority. This mixin therefore stays ahead of ``NamespaceMixin`` -- moved after
it, every BigQuery name would render unqualified and no test on earth would
catch it, because the statement would still be well-formed. It is likewise ahead
of the object protocols, which derive from ``NamespaceSupport`` and therefore
require it first.
"""

from typing import Any


class BigQueryNamespaceMixin:
    """The namespace levels a BigQuery name may carry, and what they may mean."""

    #: What goes between the name's levels. BigQuery writes
    #: ``project.dataset.table``, so this states the fact rather than leaning on
    #: core's default, which is what made the two-level shape implicit.
    separator: str = "."

    def supports_catalog(self) -> bool:
        """BigQuery models a project above the dataset."""
        return True

    def supports_catalog_qualification(self) -> bool:
        """BigQuery renders the project when a name carries one.

        ``project.dataset.table`` is the spelling BigQuery documents, so the
        project is never left implicit the way PostgreSQL's database is.
        """
        return True

    def supports_schema_qualification(self) -> bool:
        """BigQuery renders the dataset when a name carries one.

        ``dataset.table`` is the two-part form the ``FROM`` clause documents, so
        a dataset on a name is rendered rather than left implicit.

        This is the *naming* switch and not :meth:`supports_schema`, which
        answers the DDL question -- does the engine have schemas at all, can it
        ``CREATE SCHEMA`` -- and belongs to :class:`~.schema.BigQuerySchemaMixin`.
        An engine may answer the two differently.
        """
        return True

    def validate_catalog_name(self, expr: Any) -> None:
        """Accept or reject the project *expr* carries.

        A BigQuery path is ``project.dataset.table``: the project never stands
        alone above a table, so ``project.table`` is not a name BigQuery can
        resolve. A project with no dataset is therefore refused here rather
        than rendered into SQL the server would reject.

        The check runs while rendering, not while constructing, because only
        then is the dialect -- and therefore what this dialect can express --
        known. It is reached from core's ``validate_namespace``, which calls it
        for every named object; there is no per-object path to it.

        Args:
            expr: The schema object being rendered.

        Raises:
            ValueError: *expr* carries a project but no dataset.
        """
        if expr.catalog_name and not expr.schema_name:
            raise ValueError(
                f"BigQuery renders a project only together with a dataset; "
                f"{type(expr).__name__} {expr.name!r} carries "
                f"catalog_name={expr.catalog_name!r} but no schema_name"
            )


__all__ = ["BigQueryNamespaceMixin"]