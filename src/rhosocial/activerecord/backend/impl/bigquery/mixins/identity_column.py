# src/rhosocial/activerecord/backend/impl/bigquery/mixins/identity_column.py
"""BigQuery identity-column probes and the documented clause formatter.

BigQuery gained identity columns on 2026-08-31 (release notes) / 2026-09-02
(announcement). The feature is in **Preview** and its documented spelling is
GoogleSQL's own form of the SQL-standard clause::

    identity_column :=
      [ GENERATED { ALWAYS | BY DEFAULT } ] AS IDENTITY (
        [ START WITH start_value ]
        [ INCREMENT BY increment_value ])

Two documented facts drive this mixin:

* only ``START WITH`` and ``INCREMENT BY`` exist -- there is no
  ``MINVALUE`` / ``MAXVALUE`` / ``CYCLE`` in the grammar, so those probes
  answer ``False`` and the formatter refuses a requested one by name rather
  than dropping it;
* the option parentheses are literal in the grammar (they are not wrapped in
  the optional-clause brackets used elsewhere on the page), so the bare
  clause still renders them -- ``AS IDENTITY ()`` -- while core's default
  formatter omits them when no option was requested. The override below is
  therefore a spelling fix on top of core's fail-closed gates, not a new
  capability.

Evidence (fetched 2026-10-07, no BigQuery instance was available to execute
against):

* https://cloud.google.com/bigquery/docs/identity-columns
* https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language
  (``column_schema`` -> ``identity_column`` grammar)
* https://cloud.google.com/bigquery/docs/reference/standard-sql/dml-syntax
  (``GENERATED ALWAYS AS IDENTITY ( INCREMENT BY 2 )``)
* https://cloud.google.com/bigquery/docs/release-notes (2026-08-31 entry)
* https://cloud.google.com/blog/products/data-analytics/bigquery-identity-columns-to-auto-generate-sequential-integers

**Not server-verified**: these probes and the rendering are documentation
comparisons only. There is no BigQuery instance in this repository's test
environment, and the emulator used by CI does not implement the Preview
identity-column grammar.
"""

from typing import Tuple, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from rhosocial.activerecord.backend.expression.statements import IdentityClause


class BigQueryIdentityColumnMixin:
    """BigQuery's ``GENERATED ... AS IDENTITY`` capability and spelling.

    One mechanism, one mixin: the parameterised identity clause. The
    parameterless ``AUTO_INCREMENT`` marker is a different mechanism and
    stays refused on this backend (BigQuery has no such keyword); see
    :class:`BigQueryCapabilityMixin`.
    """

    def supports_identity_column(self) -> bool:
        """Whether BigQuery accepts a ``GENERATED ... AS IDENTITY`` column.

        ``True`` -- a **policy choice**, not an unknown capability.

        Identity columns shipped on 2026-08-31 and are documented in
        **Preview**: the feature is subject to the Pre-GA Offerings Terms, and
        a project must have it enabled before the clause can be used. The
        probe still answers ``True`` because it answers "can this dialect
        express the clause", not "is the clause GA": the grammar exists, this
        backend can render it, and Preview status belongs to the service and
        the project's enablement, not to the dialect's expressive power.
        Answering ``False`` would instead claim that BigQuery cannot express
        the clause at all, which the documentation contradicts.

        Source (fetched 2026-10-07, no BigQuery instance available -- this is
        a documentation answer, not an execution result):
        https://cloud.google.com/bigquery/docs/identity-columns
        (Preview badge and Pre-GA terms note; see also the 2026-08-31 release
        notes entry).

        A table can have at most one identity column, and the column must be a
        top-level INT64.
        """
        return True

    def supports_identity_generation_always(self) -> bool:
        """Whether ``GENERATED ALWAYS AS IDENTITY`` can be expressed.

        ``True``: documented, and it is the mode BigQuery uses when neither
        ``ALWAYS`` nor ``BY DEFAULT`` is written. BigQuery generates the value
        on every insert and rejects user-supplied values for the column.
        """
        return True

    def supports_identity_start(self) -> bool:
        """Whether the ``START WITH`` identity option can be expressed.

        ``True``: documented; the default start value is 1.
        """
        return True

    def supports_identity_increment(self) -> bool:
        """Whether the ``INCREMENT BY`` identity option can be expressed.

        ``True``: documented; the default increment is 1, and 0 is rejected
        by BigQuery.
        """
        return True

    def supports_identity_minvalue(self) -> bool:
        """Whether the ``MINVALUE`` identity option can be expressed.

        ``False``: not part of BigQuery's ``identity_column`` grammar. A
        requested minimum is refused by name, never dropped.
        """
        return False

    def supports_identity_maxvalue(self) -> bool:
        """Whether the ``MAXVALUE`` identity option can be expressed.

        ``False``: not part of BigQuery's ``identity_column`` grammar. A
        requested maximum is refused by name, never dropped.
        """
        return False

    def supports_identity_cycle(self) -> bool:
        """Whether the ``CYCLE`` / ``NO CYCLE`` identity option can be expressed.

        ``False``: not part of BigQuery's ``identity_column`` grammar. A
        requested cycle setting is refused by name, never dropped.
        """
        return False

    def format_identity_clause(self, expr: "IdentityClause") -> Tuple[str, Tuple]:
        """Render BigQuery's documented identity clause.

        Renders `` GENERATED {ALWAYS|BY DEFAULT} AS IDENTITY (...)`` with the
        option parentheses always present, matching the grammar on the DDL
        reference page; only the option list is optional. The per-option gates
        are core's, restated here because the spelling differs:

        * :meth:`supports_identity_column` gates the clause as a whole;
        * :meth:`supports_identity_generation_always` gates ``ALWAYS``;
        * :meth:`supports_identity_start` / ``_increment`` gate the two
          documented options;
        * :meth:`supports_identity_minvalue` / ``_maxvalue`` / ``_cycle``
          answer ``False``, so a requested one raises
          ``UnsupportedFeatureError`` naming that option.

        Why the bare form renders ``AS IDENTITY ()``: in the grammar

            identity_column :=
              [ GENERATED { ALWAYS | BY DEFAULT } ] AS IDENTITY (
                [ START WITH start_value ]
                [ INCREMENT BY increment_value ])

        the ``(`` and ``)`` sit outside every ``[ ]`` optional marker, so they
        are a literal paren group and only their contents are optional. The
        same page uses literal parentheses the same way in ``OPTIONS ( ... )``
        and ``GENERATED ALWAYS AS (generation_expression) STORED``. The
        announcement blog's only concrete example is
        ``AS IDENTITY (START WITH 1 INCREMENT BY 1)`` -- a space before the
        paren, matching this renderer.

        **No official material shows the clause's literal paren group empty**:
        every example carries options, and the prose that names
        ``GENERATED ALWAYS AS IDENTITY`` without parentheses is naming the
        mode, not exhibiting the syntax. This is the round's single assertion
        that cannot be execution-confirmed -- there is no BigQuery instance to
        run it against. One query against a real connection (``CREATE TABLE``
        with a bare identity column) would settle it; until then the empty
        paren group is the documented-grammar reading, not an observed result.

        Grammar and conventions:
        https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language

        Args:
            expr: The ``IdentityClause`` carrying the identity parameters.

        Returns:
            A ``(sql, params)`` tuple with a leading space.

        Raises:
            UnsupportedFeatureError: If BigQuery cannot express the clause,
                the requested generation mode, or one of the requested
                options.
        """
        from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError

        if not self.supports_identity_column():
            raise UnsupportedFeatureError(
                self.name, "IDENTITY column",
                f"{self.name} does not support IDENTITY columns."
            )
        generation = (expr.generation or "BY DEFAULT").upper()
        if generation == "ALWAYS" and not self.supports_identity_generation_always():
            raise UnsupportedFeatureError(
                self.name, "IDENTITY GENERATED ALWAYS",
                f"{self.name} cannot express GENERATED ALWAYS for an identity "
                f"column; only BY DEFAULT is available."
            )
        attributes = []
        if expr.start is not None:
            if not self.supports_identity_start():
                raise UnsupportedFeatureError(
                    self.name, "IDENTITY START",
                    f"{self.name} does not support the START WITH identity option."
                )
            attributes.append(f"START WITH {expr.start}")
        if expr.increment is not None:
            if not self.supports_identity_increment():
                raise UnsupportedFeatureError(
                    self.name, "IDENTITY INCREMENT",
                    f"{self.name} does not support the INCREMENT BY identity option."
                )
            attributes.append(f"INCREMENT BY {expr.increment}")
        if expr.minvalue is not None:
            if not self.supports_identity_minvalue():
                raise UnsupportedFeatureError(
                    self.name, "IDENTITY MINVALUE",
                    f"{self.name} does not support the MINVALUE identity option."
                )
            attributes.append(f"MINVALUE {expr.minvalue}")
        if expr.maxvalue is not None:
            if not self.supports_identity_maxvalue():
                raise UnsupportedFeatureError(
                    self.name, "IDENTITY MAXVALUE",
                    f"{self.name} does not support the MAXVALUE identity option."
                )
            attributes.append(f"MAXVALUE {expr.maxvalue}")
        if expr.cycle is not None:
            if not self.supports_identity_cycle():
                raise UnsupportedFeatureError(
                    self.name, "IDENTITY CYCLE",
                    f"{self.name} does not support the CYCLE identity option."
                )
            attributes.append("CYCLE" if expr.cycle else "NO CYCLE")
        return f" GENERATED {generation} AS IDENTITY ({' '.join(attributes)})", ()


__all__ = ['BigQueryIdentityColumnMixin']
