# src/rhosocial/activerecord/backend/impl/bigquery/mixins/constraint.py
"""BigQuery constraint capability declarations, read off the official grammar.

Every switch here is declared **in this package**, even where core's
``ConstraintMixin`` / ``DDLColumnMixin`` already defaults it to the same value.
That is deliberate: those mixins are shared with the dummy dialect and are
exactly the kind of default that can move, and a silent move of a core default
would move BigQuery's contract with it.  A declaration here is the pin.  Before
this module the backend declared **zero** constraint switches, so every value
below was whatever core happened to say -- and core defaults most of them to
``True``, which is the opposite of what BigQuery's grammar allows for ``CHECK``,
``UNIQUE``, ``MATCH``, ``DEFERRABLE`` and both referential actions.

Evidence level: 文档（待云验）
----------------------------
**Every value below is official-grammar-only.  Nothing here was measured.**
There is no BigQuery instance reachable from this repository's test
environment -- no cloud credentials exist -- and the emulator CI uses
(``goccy/bigquery-emulator`` on ``localhost:9050``) does **not** implement the
``ALTER TABLE ADD FOREIGN KEY`` or ``ALTER TABLE DROP CONSTRAINT`` statements at
all, so it cannot adjudicate these switches either.  A ``待云验`` marker means
"a real BigQuery run must confirm this before a caller relies on it"; the
contract tests assert the *declaration*, never the server's agreement with it.

Source, transcribed 2026-10-12 from the one page every production below is on:

  https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language

Column level, verbatim::

    column_schema :=
    { simple_type | STRUCT<field_list> | ARRAY<array_element_schema> }
    [PRIMARY KEY NOT ENFORCED | REFERENCES table_name(column_name) NOT ENFORCED]
    [ DEFAULT default_expression | embedding_generation | identity_column ]
    [NOT NULL]
    [OPTIONS(column_option_list)]

Table level, verbatim::

    CREATE TABLE [ OR REPLACE ] [ TEMP | TEMPORARY ] TABLE [ IF NOT EXISTS ]
    table_name
    [ ( column | constraint_definition[, ...] ) ] ...

    constraint_definition :=
    [primary_key]
    | [[CONSTRAINT constraint_name] foreign_key, ...]

    primary_key := PRIMARY KEY (column_name[, ...]) NOT ENFORCED
    foreign_key := FOREIGN KEY (column_name[, ...]) foreign_reference
    foreign_reference :=
    REFERENCES primary_key_table(column_name[, ...]) NOT ENFORCED

ALTER TABLE, verbatim -- these two statements are the **only** constraint
operations the page defines::

    ALTER TABLE [[project_name.]dataset_name.]fk_table_name
    ADD [CONSTRAINT [IF NOT EXISTS] constraint_name] FOREIGN KEY (fk_column_name[, ...])
    REFERENCES pk_table_name(pk_column_name[,...]) NOT ENFORCED
    [ADD...];

    ALTER TABLE [[project_name.]dataset_name.]table_name
    DROP CONSTRAINT [IF EXISTS] constraint_name;

Three facts about BigQuery that invert what the SQL-standard backends do
-----------------------------------------------------------------------------

**1. The column level has exactly two constraint kinds, and neither can be
named or enforced.**  ``PRIMARY KEY`` and ``REFERENCES`` are the whole of it;
there is no ``CHECK``, no ``UNIQUE``, and -- unlike every other backend in this
group -- **no ``CONSTRAINT <name>`` keyword at column level at all**.  The
``NOT ENFORCED`` token is written into both productions, not into an optional
``[NOT]``-alternatives bracket, so it is *mandatory and unforgiving*: there is
no spelling of a BigQuery primary key or foreign key that omits it.

**2. At table level only a FOREIGN KEY can be named.**  ``primary_key`` appears
bare in ``constraint_definition`` -- the page fetched on 2026-10-12 has no
``[CONSTRAINT constraint_name]`` in front of it -- while the foreign-key branch
reads ``[[CONSTRAINT constraint_name] foreign_key, ...]``.  The page's own
prose agrees about enforcement: *"BigQuery only supports unenforced primary
keys"* and *"BigQuery only supports unenforced foreign keys"*.

  > Note for the next reader: this corrects
  > ``.claude/plan/2026-10-11/bigquery-constraint-coverage.md``, whose
  > transcription of ``constraint_definition`` shows
  > ``[ [ CONSTRAINT constraint_name ] primary_key ]``.  The live page does not.
  > The plan's *verdict* (only a foreign key can be named at table level) was
  > right; only its transcription was stale.

**3. ``ALTER TABLE ADD`` can only add a foreign key.**  There is no general
``ADD CONSTRAINT`` form on this page at all -- the heading is literally
``ALTER TABLE ADD FOREIGN KEY statement`` and the sentence under it is *"Adds a
foreign key constraint to an existing table."*  ``CHECK``, ``UNIQUE`` and
``PRIMARY KEY`` cannot be added to an existing BigQuery table by any statement.
``DROP CONSTRAINT`` is the mirror image: *"You can use this statement to drop
foreign key constraints from a table."*  ``IF EXISTS`` is optional on ``DROP``
and ``IF NOT EXISTS`` is optional on ``ADD``.

So BigQuery's whole constraint capability is one notch: **CREATE** admits only
primary keys and foreign keys, **ALTER** admits only foreign keys, and all of
them are unenforced.  That is narrower than every other backend measured this
session.

What the switches answer, and what the render path narrows
---------------------------------------------------------
Two questions are separate and this backend answers them in two places, which
is why the values below are not the whole story:

* **The switches answer the grammar question** -- "does this dialect have the
  clause at all" -- with no kind and no version.  They take ``(self)`` and
  nothing else.
* **The kind question** -- "which constraints may carry the clause" -- belongs
  to the render path, because only a formatter can see the branch.  BigQuery's
  answer is the narrowest in the family: enforcement rides a primary key or a
  foreign key and nothing else, and the two kinds that do not exist here
  (``CHECK``, ``UNIQUE``) are refused by :meth:`_require_bigquery_table_kind`
  at the table level, where core consults no probe of its own.

Still gaps a switch cannot close (recorded, not worked around)
--------------------------------------------------------------
These are **render-path** problems that remain after the narrowing above.  Each
is named here so the next reader does not mistake the pins for working
behaviour:

* **``NOT ENFORCED`` is mandatory, and it is only emitted on request.**
  Core appends the token when a caller sets ``constraint.not_enforced = True``,
  which is the shape BigQuery wants -- on both the primary-key and the
  foreign-key path, since core's S3 moved the trait to the production level.
  What core does not do is *insist* on it: with neither ``enforced`` nor
  ``not_enforced`` set, ``_format_constraint_enforcement`` returns ``""`` and a
  caller who omits the flag gets ``PRIMARY KEY`` / ``REFERENCES t(c)`` -- a
  shape the grammar does not have.  Insisting is a core printing decision, not
  a switch value; see :meth:`_require_bigquery_enforcement`, which refuses the
  *wrong* spelling but cannot add the right one.
* **The explicit ``NULL`` column modifier is unguarded.**  ``column_schema`` has
  ``[NOT NULL]`` and says the *absence* of it means NULLABLE mode; there is no
  ``NULL`` token to write.  Core renders ``" NULL"`` with no probe at all (it
  treats an explicitly nullable column as belonging to every grammar), so that
  spelling needs a gate this backend cannot supply without a core change.
* **``ADD CONSTRAINT`` renders the wrong shape for a foreign key.**  Core emits
  ``ADD FOREIGN KEY (a) REFERENCES b(id)``; BigQuery's grammar accepts exactly
  that head (``ADD`` with no ``CONSTRAINT`` keyword), but the trailing
  ``NOT ENFORCED`` is missing, per the first bullet.

Name note
---------
The per-level (``supports_{column,table}_*``) and per-kind
(``supports_*_check_constraint``, ``supports_table_add_*``) probes, the
``naming_*`` family, ``supports_add_constraint_if_not_exists``,
``supports_table_rename_constraint``, ``supports_table_alter_constraint`` and
``supports_table_drop_foreign_key_constraint`` are **backend-only** on this
core: no ``ConstraintMixin`` or ``DDLColumnMixin`` in
``rhosocial.activerecord.backend.dialect.mixins`` declares or consults any of
them.  They are the names from
``.claude/plan/2026-10-11/bigquery-constraint-coverage.md`` and they are
declared here so the grammar answer is written down in one place next to its
evidence, **on the understanding that core S3 may rename or absorb them**.  The
flat switches below are the ones core's renderers actually consult today; the
two groups are kept apart deliberately, and every docstring says which it is.
"""

from typing import TYPE_CHECKING, Tuple

if TYPE_CHECKING:  # pragma: no cover
    from rhosocial.activerecord.backend.expression.statements.ddl_table import (
        ColumnConstraint,
        TableConstraint,
    )

#: The grammar every value in this module was transcribed from. Kept as a
#: constant so the docstrings, the tests and the plan document cannot drift onto
#: different pages.
OFFICIAL_GRAMMAR_URL = (
    "https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language"
)


class BigQueryConstraintMixin:
    """BigQuery constraint capability declarations.

    Every value in this class comes from the official ``column_schema`` /
    ``constraint_definition`` / ``ALTER TABLE`` grammar productions
    transcribed at ``OFFICIAL_GRAMMAR_URL`` on 2026-10-12.  **None of them is
    a live measurement** -- no BigQuery instance is reachable from this
    repository and the CI emulator implements neither of the two ``ALTER
    TABLE`` constraint statements.  Read each value as "this is what the
    grammar says", not as "this is what a server was seen to do"; see the
    module docstring for the evidence level and the known gaps.
    """

    # ------------------------------------------------------------------
    # Column level -- ``column_schema``
    #
    #     [PRIMARY KEY NOT ENFORCED | REFERENCES table_name(column_name) NOT ENFORCED]
    #     [ DEFAULT default_expression | embedding_generation | identity_column ]
    #     [NOT NULL]
    #     [OPTIONS(column_option_list)]
    #
    # Two kinds, neither nameable, both forced to NOT ENFORCED.  The four
    # ``False`` values below are the corrections: core defaults every one of
    # these questions to ``True``, which on this backend means rendering
    # ``CHECK (...)``, ``UNIQUE`` or ``CONSTRAINT <name>`` into a column
    # definition that BigQuery's parser rejects.
    # ------------------------------------------------------------------

    def supports_column_primary_key_constraint(self) -> bool:
        """True: ``[PRIMARY KEY NOT ENFORCED]`` is the column grammar's first slot.

        Official grammar (``column_schema``, first optional group), verbatim::

            [PRIMARY KEY NOT ENFORCED | REFERENCES table_name(column_name) NOT ENFORCED]

        The keyword pair is written out in full -- there is no
        ``[PRIMARY KEY [NOT] ENFORCED]`` form -- so a BigQuery primary key is
        only expressible as a primary key, and it is never enforced (the page's
        prose: *"BigQuery only supports unenforced primary keys"*).

        Distinct from :meth:`supports_primary_key_constraint`, which is the
        flat probe core's ``format_column_primary_key_constraint`` consults and
        which is also ``True``.  Name note: the per-level pair is
        documentation vocabulary -- no core probe is per-level, and core
        consults the flat switch.

        文档（待云验）: grammar-only, not server-verified.
        """
        return True

    def supports_column_foreign_key_constraint(self) -> bool:
        """True: ``[REFERENCES table_name(column_name) NOT ENFORCED]`` is in the grammar.

        Official grammar (``column_schema``, same optional group), verbatim::

            REFERENCES table_name(column_name) NOT ENFORCED

        A single referenced column -- note the production has no ``[, ...]``
        after ``(column_name)``, so a column-level reference names exactly one
        column.  A composite reference has to be spelled as a table-level
        ``foreign_key`` instead.

        ``NOT ENFORCED`` is inside the production, so it is mandatory here as
        it is everywhere else on this dialect (see the module docstring).

        文档（待云验）: grammar-only, not server-verified.
        """
        return True

    def supports_column_check_constraint(self) -> bool:
        """False: there is no ``CHECK`` anywhere in ``column_schema``.

        Official grammar, verbatim::

            column_schema :=
            { simple_type | STRUCT<field_list> | ARRAY<array_element_schema> }
            [PRIMARY KEY NOT ENFORCED | REFERENCES table_name(column_name) NOT ENFORCED]
            [ DEFAULT default_expression | embedding_generation | identity_column ]
            [NOT NULL]
            [OPTIONS(column_option_list)]

        Four optional groups, none of them ``CHECK``.  Declared locally because
        core's ``ConstraintMixin`` answers ``True`` for this question, and that
        inherited answer is what makes ``format_column_check_constraint`` emit
        `` CHECK (<predicate>)`` into a column definition BigQuery will not
        parse.  ``False`` turns that into an ``UnsupportedFeatureError`` by
        name instead -- see the table-level counterpart for the two levels'
        relationship.

        文档（待云验）: grammar-only, not server-verified.
        """
        return False

    def supports_column_unique_constraint(self) -> bool:
        """False: there is no ``UNIQUE`` anywhere in ``column_schema``.

        Official grammar: the same four-group ``column_schema`` production
        quoted in :meth:`supports_column_check_constraint`; ``UNIQUE`` is in
        none of them.

        Declared locally because core defaults this to ``True`` and core's
        ``format_column_unique_constraint`` consults *this* probe for the
        ``ColumnUniqueConstraint`` branch -- so the inherited ``True`` renders
        a bare `` UNIQUE`` on a BigQuery column.  With ``False`` the caller is
        refused by name.

        Worth saying plainly, because it is the kind of absence a reader
        questions: BigQuery does not have a ``UNIQUE`` *constraint* and never
        had one at this level.  Its uniqueness story is a clustering or
        merge-time property, not DDL, so there is nothing to gate off.

        文档（待云验）: grammar-only, not server-verified.
        """
        return False

    def supports_column_naming_primary_key_constraint(self) -> bool:
        """False: the column level has no ``CONSTRAINT <name>`` keyword.

        Official grammar, verbatim: ``column_schema``'s first optional group is
        ``[PRIMARY KEY NOT ENFORCED | REFERENCES ... NOT ENFORCED]``.  Neither
        branch has a ``CONSTRAINT constraint_name`` in front of it -- the
        keyword does not occur in the production at all, so a column-level
        constraint cannot be named on BigQuery.

        This is the asymmetry that makes BigQuery unusual in this group: every
        other backend that has ``CONSTRAINT <name>`` has it at column level
        too, and here it is table-level-only (and even there only for a foreign
        key).

        Name note: no core probe is per-level or ``naming_*`` yet.
        文档（待云验）: grammar-only, not server-verified.
        """
        return False

    def supports_column_naming_foreign_key_constraint(self) -> bool:
        """False: same reason as :meth:`supports_column_naming_primary_key_constraint`.

        Official grammar: the ``REFERENCES table_name(column_name) NOT
        ENFORCED`` branch of ``column_schema`` carries no ``CONSTRAINT`` keyword.
        Only the *table-level* foreign key can be named on BigQuery; see
        :meth:`supports_table_naming_foreign_key_constraint`.

        Name note: no core probe is per-level or ``naming_*`` yet.
        文档（待云验）: grammar-only, not server-verified.
        """
        return False

    def supports_column_enforced_primary_key_constraint(self) -> bool:
        """True: the column primary key carries a mandatory ``NOT ENFORCED``.

        Official grammar, verbatim::

            [PRIMARY KEY NOT ENFORCED | REFERENCES table_name(column_name) NOT ENFORCED]

        ``NOT ENFORCED`` is part of the production, not an optional
        alternative, so the enforcement marker is **always written** and there
        is nothing to choose.  The page says the same in prose: *"BigQuery only
        supports unenforced primary keys."*

        This is why the value is ``True`` rather than "n/a": the marker is not
        optional, it is compulsory.  A renderer that could not emit it could
        never produce a valid BigQuery primary key at all.

        Name note: per-kind enforcement probes are a core S3 question; core
        consults the flat :meth:`supports_constraint_enforced` today.
        文档（待云验）: grammar-only, not server-verified.
        """
        return True

    def supports_column_enforced_foreign_key_constraint(self) -> bool:
        """True: the column reference carries a mandatory ``NOT ENFORCED``.

        Official grammar: ``REFERENCES table_name(column_name) NOT ENFORCED``,
        with the marker inside the production.  Page prose: *"BigQuery only
        supports unenforced foreign keys."*

        Same reasoning as :meth:`supports_column_enforced_primary_key_constraint`
        -- the token is compulsory, so the capability is ``True`` and what is
        missing is a renderer that emits it (see the module docstring's known
        gaps).

        Name note: per-kind enforcement probes are a core S3 question.
        文档（待云验）: grammar-only, not server-verified.
        """
        return True

    def supports_column_enforced_check_constraint(self) -> bool:
        """False: an enforcement marker on a constraint that cannot exist.

        The column level has no ``CHECK`` (see
        :meth:`supports_column_check_constraint`), so there is nothing for
        ``NOT ENFORCED`` to attach to.  ``False`` rather than "n/a" because the
        combination a caller would be asking for -- an unenforced column CHECK
        -- is not expressible on BigQuery at all.

        文档（待云验）: grammar-only, not server-verified.
        """
        return False

    def supports_column_enforced_unique_constraint(self) -> bool:
        """False: an enforcement marker on a constraint that cannot exist.

        The column level has no ``UNIQUE`` (see
        :meth:`supports_column_unique_constraint`); ``ENFORCED`` /
        ``NOT ENFORCED`` on one is equally inexpressible.

        文档（待云验）: grammar-only, not server-verified.
        """
        return False

    # ------------------------------------------------------------------
    # Table level -- ``constraint_definition``
    #
    #     constraint_definition :=
    #     [primary_key]
    #     | [[CONSTRAINT constraint_name] foreign_key, ...]
    #
    #     primary_key := PRIMARY KEY (column_name[, ...]) NOT ENFORCED
    #     foreign_key := FOREIGN KEY (column_name[, ...]) foreign_reference
    #     foreign_reference :=
    #     REFERENCES primary_key_table(column_name[, ...]) NOT ENFORCED
    #
    # The same two kinds as the column level, but the column lists may be
    # composite here, and only the foreign key may be named.
    # ------------------------------------------------------------------

    def supports_table_primary_key_constraint(self) -> bool:
        """True: ``PRIMARY KEY (column_name[, ...]) NOT ENFORCED`` is a table element.

        Official grammar, verbatim::

            constraint_definition :=
            [primary_key]
            | [[CONSTRAINT constraint_name] foreign_key, ...]

            primary_key := PRIMARY KEY (column_name[, ...]) NOT ENFORCED

        The comma makes this the composite form the column level cannot
        express.  ``NOT ENFORCED`` is inside the production again, so it is
        mandatory (page prose: *"BigQuery only supports unenforced primary
        keys."*).

        This is the same ``True`` as :meth:`supports_column_primary_key_constraint`
        seen from the other side of the grammar; it is not the core probe --
        see :meth:`supports_primary_key_constraint`.

        文档（待云验）: grammar-only, not server-verified.
        """
        return True

    def supports_table_foreign_key_constraint(self) -> bool:
        """True: the second branch of ``constraint_definition`` is the foreign key.

        Official grammar, verbatim::

            constraint_definition :=
            [primary_key]
            | [[CONSTRAINT constraint_name] foreign_key, ...]

            foreign_key := FOREIGN KEY (column_name[, ...]) foreign_reference

            foreign_reference :=
            REFERENCES primary_key_table(column_name[, ...]) NOT ENFORCED

        Note the trailing ``, ...`` on the branch itself: a table may carry a
        comma-separated list of foreign keys (and each may be individually
        named), which is the only place on this dialect where several
        constraints of one kind share a production.

        This is also the **only** kind ``ALTER TABLE`` can add or drop; see
        :meth:`supports_add_constraint`.

        文档（待云验）: grammar-only, not server-verified.
        """
        return True

    def supports_table_check_constraint(self) -> bool:
        """False: ``CHECK`` is not one of the two branches of ``constraint_definition``.

        Official grammar, verbatim::

            constraint_definition :=
            [primary_key]
            | [[CONSTRAINT constraint_name] foreign_key, ...]

        Two branches, and neither is ``CHECK``.  There is no other production
        on the page that declares a check constraint at any level, and
        ``ALTER TABLE`` cannot add one either, so a BigQuery table can never
        carry a ``CHECK``.

        Declared locally rather than left to core's ``True`` because the
        two-level pair is the finding: the *column* half
        (:meth:`supports_column_check_constraint`) is ``False`` for the same
        reason, and having one ``True`` and one ``False`` would misrepresent
        the engine in whichever direction it went.

        Load-bearing on the render path: core's ``format_table_constraint``
        dispatches by branch and consults no per-kind probe (only ``EXCLUDE``
        is gated there), so this ``False`` would not by itself refuse anything.
        The refusal is this dialect's own: ``format_table_constraint`` calls
        :meth:`_require_bigquery_table_kind` before the ``CONSTRAINT <name>``
        prefix is rendered, and a table-level CHECK is refused by name.

        文档（待云验）: grammar-only, not server-verified.
        """
        return False

    def supports_table_unique_constraint(self) -> bool:
        """False: ``UNIQUE`` is not one of the two branches of ``constraint_definition``.

        Official grammar, verbatim::

            constraint_definition :=
            [primary_key]
            | [[CONSTRAINT constraint_name] foreign_key, ...]

        Same absence as :meth:`supports_table_check_constraint`, and the same
        note about the column level agreeing; the refusal comes from the same
        place too -- this dialect's ``format_table_constraint`` calls
        :meth:`_require_bigquery_table_kind`, because core gates no per-kind
        table switch.  This backend's own DDL fixtures already state the
        consequence in prose -- ``tests/providers/fixtures`` builds every
        scenario without a ``UNIQUE`` clause and without foreign keys -- which
        is only true because of this ``False``.

        文档（待云验）: grammar-only, not server-verified.
        """
        return False

    def supports_table_naming_primary_key_constraint(self) -> bool:
        """False: the ``primary_key`` branch is bare -- no ``CONSTRAINT <name>``.

        Official grammar, verbatim::

            constraint_definition :=
            [primary_key]
            | [[CONSTRAINT constraint_name] foreign_key, ...]

        Read the two branches against each other: the foreign-key branch
        brackets the name (``[[CONSTRAINT constraint_name] foreign_key, ...]``)
        and the primary-key branch does not (``[primary_key]``).  So a BigQuery
        table's primary key **cannot be named**, and ``ALTER TABLE DROP
        CONSTRAINT`` therefore cannot address it either.

        This is the one value here that corrects the plan document rather than
        confirming it: ``.claude/plan/2026-10-11/bigquery-constraint-coverage.md``
        transcribes this branch as
        ``[ [ CONSTRAINT constraint_name ] primary_key ]``.  The page fetched on
        2026-10-12 has no such brackets, and the plan's own summary row (only
        a foreign key can be named at table level) agrees with the page.
        Recorded in the module docstring so the two documents do not keep
        disagreeing silently.

        文档（待云验）: grammar-only, not server-verified.
        """
        return False

    def supports_table_naming_foreign_key_constraint(self) -> bool:
        """True: this is the one place on BigQuery where a constraint may be named.

        Official grammar, verbatim::

            constraint_definition :=
            [primary_key]
            | [[CONSTRAINT constraint_name] foreign_key, ...]

        The name is optional and per-key (``[CONSTRAINT constraint_name]
        foreign_key``, then ``, ...`` for the rest), which is why the ALTER
        side can then use ``DROP CONSTRAINT [IF EXISTS] constraint_name`` to
        remove one -- see :meth:`supports_drop_constraint`.  Every other kind,
        at every level, is unnameable on BigQuery.

        文档（待云验）: grammar-only, not server-verified.
        """
        return True

    def supports_table_enforced_primary_key_constraint(self) -> bool:
        """True: the table primary key carries a mandatory ``NOT ENFORCED``.

        Official grammar, verbatim::

            primary_key := PRIMARY KEY (column_name[, ...]) NOT ENFORCED

        Inside the production, so mandatory.  Page prose: *"BigQuery only
        supports unenforced primary keys."*

        文档（待云验）: grammar-only, not server-verified.
        """
        return True

    def supports_table_enforced_foreign_key_constraint(self) -> bool:
        """True: the table foreign key carries a mandatory ``NOT ENFORCED``.

        Official grammar, verbatim::

            foreign_reference :=
            REFERENCES primary_key_table(column_name[, ...]) NOT ENFORCED

        The marker sits on the *reference*, not on the ``FOREIGN KEY`` head, so
        it follows the referenced table and column list.  Same compulsory
        reading as the other three enforced entries, and the same page prose
        (*"BigQuery only supports unenforced foreign keys."*).

        文档（待云验）: grammar-only, not server-verified.
        """
        return True

    def supports_table_enforced_check_constraint(self) -> bool:
        """False: no ``CHECK`` exists at table level to carry a marker.

        See :meth:`supports_table_check_constraint` for the two-branch
        ``constraint_definition`` that excludes it.

        文档（待云验）: grammar-only, not server-verified.
        """
        return False

    def supports_table_enforced_unique_constraint(self) -> bool:
        """False: no ``UNIQUE`` exists at table level to carry a marker.

        See :meth:`supports_table_unique_constraint`.

        文档（待云验）: grammar-only, not server-verified.
        """
        return False

    def supports_exclude_constraint(self) -> bool:
        """False: ``EXCLUDE`` is a PostgreSQL family feature, absent here.

        Official grammar: ``constraint_definition`` has two branches, a bare
        ``[primary_key]`` and ``[[CONSTRAINT constraint_name] foreign_key, ...]``
        (quoted at :meth:`supports_table_primary_key_constraint`).  Neither is an
        exclusion constraint, and no other production on the page declares one.

        Declared locally because this switch is one of the few *table*-level
        probes core's ``format_table_constraint`` actually gates on -- it is the
        only kind there whose absence refuses by name instead of rendering.  So
        the ``False`` is load-bearing in a way the neighbouring kind switches
        are not, and it must not be left to an inherited default.

        Declared ``False`` rather than omitted: BigQuery's ``ARRAY`` type does
        not imply an exclusion constraint, and nothing on this dialect can
        express one.

        文档（待云验）: grammar-only, not server-verified.
        """
        return False

    # ------------------------------------------------------------------
    # Flat kind switches -- the probes core's renderers actually consult
    # today.
    #
    # Read this section next to the two above: those describe the grammar's
    # per-level shape, these are what a formatter asks.  Where the two could
    # disagree they are documented at the entry that differs.
    # ------------------------------------------------------------------

    def supports_primary_key_constraint(self) -> bool:
        """True: ``format_column_primary_key_constraint`` may emit ``PRIMARY KEY``.

        Official grammar: ``[PRIMARY KEY NOT ENFORCED | ...]`` at column level
        and ``primary_key := PRIMARY KEY (column_name[, ...]) NOT ENFORCED`` at
        table level -- the keyword is in both, so ``True`` at both.

        **What this ``True`` does not cover is the mandatory marker.**  The
        probe answers "may a primary key be spelled at all", which is ``True``
        on both levels.  Whether the compulsory ``NOT ENFORCED`` is actually
        printed is a separate matter core decides at render time: it emits the
        token only when a caller asks for it, so a caller that omits the flag
        gets a bare ``PRIMARY KEY`` -- a shape the grammar does not have.  That
        gap is recorded in the module docstring rather than worked around here,
        and :meth:`_require_bigquery_enforcement` refuses the *wrong* spelling
        (``enforced=True``) on the same path.

        Declared locally even though core already answers ``True``: the value is
        load-bearing (it is the gate on the refusal) and must not be able to
        move with a core default.

        文档（待云验）: grammar-only, not server-verified.
        """
        return True

    def supports_foreign_key_constraint(self) -> bool:
        """True: core's ``format_column_fk_constraint`` may emit ``REFERENCES``.

        Official grammar: ``REFERENCES table_name(column_name) NOT ENFORCED`` in
        ``column_schema``, and ``foreign_key := FOREIGN KEY (column_name[, ...])
        foreign_reference`` at table level.  Both levels, so ``True``.

        Known coupling, inherited from core and worth restating: this one flat
        probe is consulted for the *column* level
        (``format_column_fk_constraint``), with no separate column-level
        question available.  BigQuery answers ``True`` at both levels, so the
        coupling costs nothing here -- unlike SQL Server, where it does.  The
        column-level answer is recorded explicitly at
        :meth:`supports_column_foreign_key_constraint` so that changes to one
        do not silently change the other.

        Declared locally so the ``True`` is BigQuery's statement.

        文档（待云验）: grammar-only, not server-verified.
        """
        return True

    def supports_check_constraint(self) -> bool:
        """False, and this is the correction with the widest blast radius.

        Official grammar: ``column_schema`` has four optional groups and
        ``constraint_definition`` has two branches; **neither mentions
        ``CHECK``** (both quoted in :meth:`supports_column_check_constraint` and
        :meth:`supports_table_check_constraint`).

        Before this declaration the backend inherited core's ``True``, which
        made core's ``format_column_check_constraint`` render `` CHECK
        (<predicate>)`` into a BigQuery column definition.  ``False`` now makes
        that path raise ``UnsupportedFeatureError`` naming "CHECK column
        constraint" instead.

        Note the two-level relationship, because it is the one place a reader
        may expect a contradiction: ``False`` here *and*
        :meth:`supports_table_check_constraint` ``False``, while
        ClickHouse's equivalent pair is ``False`` at column level and ``True`` at
        table level.  BigQuery genuinely has no ``CHECK`` anywhere -- the
        official grammar admits only primary keys and foreign keys -- so the
        asymmetry between the two backends is the engines'.

        文档（待云验）: grammar-only, not server-verified.
        """
        return False

    def supports_unique_constraint(self) -> bool:
        """False: no ``UNIQUE`` at column level, and core consults *this* probe there.

        Official grammar: ``UNIQUE`` is in none of ``column_schema``'s four
        optional groups, and in neither branch of ``constraint_definition``.

        The load-bearing detail is *where* core reads this probe:
        ``format_column_unique_constraint`` pairs the ``ColumnUniqueConstraint``
        branch with ``self.supports_unique_constraint`` and raises when it
        answers ``False``.  So the inherited ``True`` was rendering a bare
        `` UNIQUE`` on BigQuery columns, and this ``False`` turns that into a
        refusal by name.  See :meth:`supports_column_unique_constraint` for the
        level breakdown.

        文档（待云验）: grammar-only, not server-verified.
        """
        return False

    def supports_not_null_constraint(self) -> bool:
        """True: ``[NOT NULL]`` is the third optional group of ``column_schema``.

        Official grammar, verbatim::

            [ DEFAULT default_expression | embedding_generation | identity_column ]
            [NOT NULL]
            [OPTIONS(column_option_list)]

        Two facts in that quote that matter more than the ``True``:

        * the page explains the semantics -- *"When the NOT NULL constraint is
          present for a column or field, the column or field is created with
          REQUIRED mode.  Conversely, when the NOT NULL constraint is absent,
          the column or field is created with NULLABLE mode."*  Absent is how
          you spell nullable; there is no ``NULL`` token to write.
        * **it comes AFTER the ``DEFAULT`` / identity group.**  On most backends
          ``NOT NULL`` precedes ``DEFAULT``; here the order is fixed the other
          way, and the render path has to honour it.  See the ordering note on
          the class body of
          :class:`~rhosocial.activerecord.backend.impl.bigquery.mixins.ddl.BigQueryDDLColumnMixin`.

        One documented restriction the ``True`` does not cover: *"Columns and
        fields of ARRAY type do not support the NOT NULL modifier."*  That is a
        per-column condition, not a capability, so it does not belong in a
        dialect-level switch.

        文档（待云验）: grammar-only, not server-verified.
        """
        return True

    # ------------------------------------------------------------------
    # Referential actions, MATCH, deferral -- none of which are in
    # ``column_schema``, ``constraint_definition`` or ``foreign_reference``.
    #
    # Every ``False`` in this block is a **change** from the inherited core
    # value: ``ConstraintMixin`` answers ``True`` for all of them, and
    # ``DDLColumnMixin`` answers ``True`` for both ``ON DELETE`` / ``ON UPDATE``
    # pairs.  Each inherited ``True`` would let a caller attach a clause
    # BigQuery's parser rejects.
    # ------------------------------------------------------------------

    def supports_fk_on_delete(self) -> bool:
        """False: ``foreign_reference`` has no ``ON DELETE``.

        Official grammar, verbatim::

            foreign_reference :=
            REFERENCES primary_key_table(column_name[, ...]) NOT ENFORCED

        Four tokens after ``REFERENCES`` and nothing else: no
        ``[ MATCH ... ]``, no ``[ ON DELETE ... ]``, no ``[ ON UPDATE ... ]``,
        no deferral attributes.  A BigQuery foreign key is therefore purely
        declarative -- it records the relationship, and BigQuery does not act
        on it (the page is explicit that the keys are unenforced), so there is
        no cascade to ask for.

        Changed from core's ``True``.  The switch core's renderer consults for
        this clause is the pair below; this one is the flat declaration of the
        same fact, pinned locally so the two cannot disagree by accident.

        文档（待云验）: grammar-only, not server-verified.
        """
        return False

    def supports_fk_on_update(self) -> bool:
        """False: same production, same absence -- ``foreign_reference`` has no ``ON UPDATE``.

        Official grammar::

            foreign_reference :=
            REFERENCES primary_key_table(column_name[, ...]) NOT ENFORCED

        Oracle 21c is the one backend measured this session that has no
        ``ON UPDATE`` at all; BigQuery joins it, and joins it for the stronger
        reason that BigQuery's reference clause has no referential attributes
        of any kind.

        Changed from core's ``True``.

        文档（待云验）: grammar-only, not server-verified.
        """
        return False

    def supports_fk_match(self) -> bool:
        """False: no ``MATCH {SIMPLE|PARTIAL|FULL}`` in the reference clause.

        Official grammar::

            foreign_reference :=
            REFERENCES primary_key_table(column_name[, ...]) NOT ENFORCED

        ``MATCH`` is an SQL:1999 optional clause that PostgreSQL, MySQL,
        MariaDB and Firebird all spell; BigQuery's reference clause does not
        reach it.  Core's ``ConstraintMixin`` answers ``True`` for this
        question, and ``format_references_clause`` raises
        ``UnsupportedFeatureError`` only when the probe declines, so the
        inherited value would render ``MATCH FULL`` onto a BigQuery reference.

        Distinct from MySQL's trap, which is worth not conflating: MySQL
        *accepts* ``MATCH FULL`` and silently discards it, which is why it has
        to be refused there even though the server is happy.  BigQuery has no
        token at all, so this is the ordinary case.

        文档（待云验）: grammar-only, not server-verified.
        """
        return False

    def supports_deferrable_constraint(self) -> bool:
        """False: no ``DEFERRABLE`` / ``NOT DEFERRABLE`` / ``INITIALLY ...``.

        Official grammar: ``foreign_reference`` is four tokens wide (see
        :meth:`supports_fk_on_delete`), and neither ``column_schema`` nor
        ``constraint_definition`` mentions deferral either.

        Core's ``ConstraintMixin`` answers ``True``, and
        ``format_references_clause`` consults it whenever any of the four
        deferral flags is set -- so the inherited value renders `` DEFERRABLE``
        / `` INITIALLY DEFERRED`` onto a BigQuery reference clause.

        Changed from core's ``True``.

        文档（待云验）: grammar-only, not server-verified.
        """
        return False

    # ------------------------------------------------------------------
    # Enforcement control.
    # ------------------------------------------------------------------

    def supports_constraint_enforced(self) -> bool:
        """True -- and the reason is that ``NOT ENFORCED`` is **compulsory**.

        Official grammar, in both places the marker appears::

            [PRIMARY KEY NOT ENFORCED | REFERENCES table_name(column_name) NOT ENFORCED]
            ...
            primary_key := PRIMARY KEY (column_name[, ...]) NOT ENFORCED
            foreign_reference :=
            REFERENCES primary_key_table(column_name[, ...]) NOT ENFORCED
            ...
            ALTER TABLE ... ADD [CONSTRAINT [IF NOT EXISTS] constraint_name]
              FOREIGN KEY (fk_column_name[, ...])
              REFERENCES pk_table_name(pk_column_name[,...]) NOT ENFORCED

        **The token is inside every production**, not inside a ``[NOT]``
        optional group.  There is no BigQuery constraint spelling that omits
        ``NOT ENFORCED`` and no spelling that says ``ENFORCED``.  The page's
        prose is the same statement: *"BigQuery only supports unenforced primary
        keys"* and *"BigQuery only supports unenforced foreign keys."*

        So the honest answer to "may this dialect spell an enforcement
        marker?" is ``True`` -- it must, or it cannot express a primary key or
        a foreign key at all.  Answering ``False`` would be the wrong fix: it
        would refuse the *only* marker BigQuery has, and leave every primary key
        and foreign key unspellable.

        **The probe takes no kind, by the round's protocol** (rule 1): a probe
        answers whether the clause family exists on this dialect, and nothing
        else.  Which constraints may carry it is the render path's question,
        and BigQuery's answer is the narrow one: PK and FK only, expressed by
        :meth:`_require_bigquery_enforcement`, called from the dialect's own
        ``format_column_constraint`` and ``format_table_constraint``.  The
        kinds that do not exist here (``CHECK``, ``UNIQUE``) never reach this
        probe.

        文档（待云验）: grammar-only, not server-verified.
        """
        return True

    def supports_alter_constraint_enforced(self) -> bool:
        """False: there is no ``ALTER CONSTRAINT`` statement to carry a marker.

        Official grammar: the page defines exactly two constraint operations
        under ``ALTER TABLE`` and neither is this one::

            ALTER TABLE [[project_name.]dataset_name.]fk_table_name
            ADD [CONSTRAINT [IF NOT EXISTS] constraint_name] FOREIGN KEY (...)
            REFERENCES pk_table_name(pk_column_name[,...]) NOT ENFORCED
            [ADD...];

            ALTER TABLE [[project_name.]dataset_name.]table_name
            DROP CONSTRAINT [IF EXISTS] constraint_name;

        A BigQuery constraint's enforcement state is fixed at creation -- it is
        unenforced and there is no statement that changes it.  So while the
        marker is *mandatory* on the ADD path
        (:meth:`supports_constraint_enforced`), it is *unreachable* on an ALTER
        path.

        That the marker is still written on ``ADD ... FOREIGN KEY`` is not a
        contradiction: the grammar puts ``NOT ENFORCED`` in the ADD production
        itself, which is a creation-time statement, not an ``ALTER CONSTRAINT``.

        The probe answers the *verb's* existence and takes no kind: which kinds
        an ``ALTER CONSTRAINT`` would reach if it existed is not a question a
        BigQuery answer can have, and the gate below is the dialect's own
        ``format_alter_constraint_action``.

        Declared locally: core already answers ``False``, and this is the pin
        that keeps it.

        文档（待云验）: grammar-only, not server-verified.
        """
        return False

    # ------------------------------------------------------------------
    # The render path: kind narrowing and the trait's own gate.
    #
    # These three are the seam S3 asks for.  The probes above answer the
    # grammar question with no kind; the branch class is the only thing that
    # can say what kind a constraint is, so the per-kind answers live in
    # formatters the dialect owns -- no private *formatter* is added (the
    # ``_`` helpers are called from public formatters, per the ten rules), and
    # the branches whose absence is expressible (CHECK, UNIQUE) are refused by
    # name here rather than rendered into SQL the parser rejects.
    # ------------------------------------------------------------------

    #: Branch class -> the SQL spelling used in a refusal message. The spelling
    #: is the SQL keyword, not the Python class name, because the message is
    #: read by someone who wrote SQL.
    _CONSTRAINT_KIND_SQL = {
        "ColumnPrimaryKeyConstraint": "PRIMARY KEY",
        "ColumnUniqueConstraint": "UNIQUE",
        "ColumnCheckConstraint": "CHECK",
        "ColumnForeignKeyConstraint": "FOREIGN KEY",
        "TablePrimaryKeyConstraint": "PRIMARY KEY",
        "TableUniqueConstraint": "UNIQUE",
        "TableCheckConstraint": "CHECK",
        "TableForeignKeyConstraint": "FOREIGN KEY",
    }

    def _bigquery_kind_sql(self, branch: object) -> str:
        """The SQL spelling to name a constraint branch in a refusal."""
        return self._CONSTRAINT_KIND_SQL.get(type(branch).__name__, type(branch).__name__)

    def _require_bigquery_enforcement(self, constraint: object) -> None:
        """Refuse ``ENFORCED`` on BigQuery, and ``NOT ENFORCED`` off a PK/FK.

        ``NOT ENFORCED`` is inside every BigQuery constraint production, so
        the dialect can never *omit* it -- but it also has no ``ENFORCED``
        token at all, so a caller who asks for the bare marker is asking for
        something the grammar does not have.  And the token rides only the two
        kinds that exist here; the table-level ones that do not exist are
        refused by :meth:`_require_bigquery_table_kind` before this runs.

        Raises:
            UnsupportedFeatureError: For ``enforced=True``, or for the marker
                on a branch that cannot carry it.
        """
        from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError

        enforced = getattr(constraint, "enforced", False)
        not_enforced = getattr(constraint, "not_enforced", False)
        if not enforced and not not_enforced:
            return
        branch = getattr(constraint, "branch", None)
        kind = self._bigquery_kind_sql(branch)
        if enforced:
            feature = f"{kind} ENFORCED"
            raise UnsupportedFeatureError(
                self.name,
                feature,
                f"{self.name} does not support {feature}. BigQuery's "
                f"constraint grammar writes ``NOT ENFORCED`` into every "
                f"production and has no ``ENFORCED`` spelling.",
            )
        if type(branch).__name__ not in (
            "ColumnPrimaryKeyConstraint",
            "ColumnForeignKeyConstraint",
            "TablePrimaryKeyConstraint",
            "TableForeignKeyConstraint",
        ):
            feature = f"{kind} NOT ENFORCED"
            raise UnsupportedFeatureError(
                self.name,
                feature,
                f"{self.name} does not support {feature}.",
            )

    def _require_bigquery_table_kind(self, constraint: object) -> None:
        """Refuse the table-level kinds BigQuery has no production for.

        ``constraint_definition`` admits a bare ``[primary_key]`` and
        ``[[CONSTRAINT constraint_name] foreign_key, ...]`` and nothing else,
        so a table-level ``CHECK`` or ``UNIQUE`` cannot be written.  Core's
        ``format_table_constraint`` dispatches by branch and consults no
        per-kind probe, which is why the refusal is this dialect's own -- and
        why it happens before the name prefix is rendered.

        Raises:
            UnsupportedFeatureError: for a table-level CHECK or UNIQUE.
        """
        from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError

        kind = self._bigquery_kind_sql(getattr(constraint, "branch", None))
        if kind in ("CHECK", "UNIQUE"):
            feature = f"{kind} table constraint"
            raise UnsupportedFeatureError(
                self.name,
                feature,
                f"{self.name} does not support {feature}.",
            )

    # ------------------------------------------------------------------
    # ALTER TABLE constraint lifecycle.
    #
    # BigQuery's ALTER grammar has exactly two constraint statements, and they
    # are not the same kind:
    #
    #   ADD    -- foreign key only, and it is the *only* thing ADD can add
    #   DROP   -- by name, and therefore also foreign key only, because a
    #             foreign key is the only nameable constraint on this dialect
    #
    # Everything else a caller might reach for (rename, alter, validate,
    # not-valid, enable/disable, drop-by-kind) has no production at all.
    # ------------------------------------------------------------------

    def supports_add_constraint(self) -> bool:
        """True for the *operation* -- and it adds a FOREIGN KEY and nothing else.

        Official grammar, verbatim: the statement is headed
        ``ALTER TABLE ADD FOREIGN KEY statement`` and reads::

            ALTER TABLE [[project_name.]dataset_name.]fk_table_name
            ADD [CONSTRAINT [IF NOT EXISTS] constraint_name] FOREIGN KEY (fk_column_name[, ...])
            REFERENCES pk_table_name(pk_column_name[,...]) NOT ENFORCED
            [ADD...];

        The page's sentence under the heading is *"Adds a foreign key
        constraint to an existing table."*  There is no general ``ADD
        CONSTRAINT`` form on the page at all.

        **The honest answer to the question this switch asks is ``True``**: the
        operation exists, and BigQuery is the only backend in this group for
        which ``ALTER TABLE ADD <constraint>`` is genuinely available.  Setting
        it ``False`` would make the one statement BigQuery has unreachable.

        What ``True`` must not be read as claiming is that the four kinds are
        equally addable.  They are not, and the per-kind truth is recorded
        alongside:

        * :meth:`supports_table_add_foreign_key_constraint` -- ``True``
        * :meth:`supports_table_add_primary_key_constraint` -- ``False``
        * :meth:`supports_table_add_check_constraint` -- ``False``
        * :meth:`supports_table_add_unique_constraint` -- ``False``

        BigQuery is the only backend of the ten measured this session where
        ``ADD CONSTRAINT`` does not reach all four kinds; every other one
        either adds all four or (SQLite) adds none.

        A single boolean cannot carry "the operation exists" and "this kind can
        use it" at once, which is the argument for the per-kind split.

        文档（待云验）: grammar-only, not server-verified.
        """
        return True

    def supports_add_constraint_if_not_exists(self) -> bool:
        """True: ``[CONSTRAINT [IF NOT EXISTS] constraint_name]`` brackets it.

        Official grammar, on the ADD statement::

            ADD [CONSTRAINT [IF NOT EXISTS] constraint_name] FOREIGN KEY (...)

        The double bracket is the page's own notation for "this whole segment,
        including the keyword, is optional": a constraint may be added
        unnamed, named, or named-if-absent.

        Note what this switch is *not*: ``IF NOT EXISTS`` on the ``CONSTRAINT``
        keyword is the only idempotency guard BigQuery offers on this path.
        There is no ``ALTER TABLE IF NOT EXISTS`` form for the ADD itself, and
        the ``[ADD ...]`` tail of the production repeats the same statement
        rather than introducing a guard.

        文档（待云验）: grammar-only, not server-verified.
        """
        return True

    def supports_table_add_foreign_key_constraint(self) -> bool:
        """True: the foreign key is the one kind ``ALTER TABLE ADD`` can add.

        Official grammar: the ADD production's head is literally ``FOREIGN KEY
        (fk_column_name[, ...])`` and the statement's heading is
        ``ALTER TABLE ADD FOREIGN KEY statement``.

        So of the four ``constraint_definition`` kinds BigQuery knows at
        ``CREATE`` time, exactly one survives to ``ALTER`` time.  The other
        three are :meth:`supports_table_add_primary_key_constraint`,
        :meth:`supports_table_add_check_constraint` and
        :meth:`supports_table_add_unique_constraint` -- all ``False``.

        文档（待云验）: grammar-only, not server-verified.
        """
        return True

    def supports_table_add_primary_key_constraint(self) -> bool:
        """False: the ADD production's only head is ``FOREIGN KEY``.

        Official grammar::

            ADD [CONSTRAINT [IF NOT EXISTS] constraint_name] FOREIGN KEY (fk_column_name[, ...])
            REFERENCES pk_table_name(pk_column_name[,...]) NOT ENFORCED
            [ADD...];

        BigQuery *can* have a primary key -- ``CREATE TABLE`` accepts one, and
        BigQuery uses it for streaming best-effort row-ordering guarantees --
        but it can only be given to a table at creation.  This is a real
        ``False``, not "not implemented yet": there is no other statement on the
        page that adds one.

        文档（待云验）: grammar-only, not server-verified.
        """
        return False

    def supports_table_add_check_constraint(self) -> bool:
        """False: no ``CHECK`` to add, and no ADD form that would carry one.

        Official grammar: ``constraint_definition`` (quoted in
        :meth:`supports_table_check_constraint`) has no ``CHECK`` branch, and
        the ALTER page's only constraint statement heads ``FOREIGN KEY``.  Both
        ends are closed.

        文档（待云验）: grammar-only, not server-verified.
        """
        return False

    def supports_table_add_unique_constraint(self) -> bool:
        """False: no ``UNIQUE`` to add, and no ADD form that would carry one.

        Official grammar: same two closures as
        :meth:`supports_table_add_check_constraint` --
        ``constraint_definition`` has no ``UNIQUE`` branch and the ALTER
        statement heads ``FOREIGN KEY``.

        文档（待云验）: grammar-only, not server-verified.
        """
        return False

    def supports_drop_constraint(self) -> bool:
        """True for the operation -- and it can only ever name a foreign key.

        Official grammar, verbatim::

            ALTER TABLE [[project_name.]dataset_name.]table_name
            DROP CONSTRAINT [IF EXISTS] constraint_name;

        and the page's sentence above it: *"Drops a constraint from an existing
        table.  You can use this statement to drop foreign key constraints from
        a table."*

        The second sentence is the important one and it is the backend's
        narrowest fact: the statement is *described* as dropping constraints in
        general and then *specified* as dropping foreign keys.  Since a
        foreign key is the only nameable constraint BigQuery has
        (:meth:`supports_table_naming_foreign_key_constraint`), those two facts
        are consistent -- the reachable set is exactly the FKs.

        Consequence worth stating: a BigQuery primary key cannot be dropped by
        name, because it cannot be named.  Neither can anything else.

        文档（待云验）: grammar-only, not server-verified.
        """
        return True

    def supports_drop_constraint_if_exists(self) -> bool:
        """True: ``DROP CONSTRAINT [IF EXISTS] constraint_name`` -- the guard is available.

        Official grammar, verbatim::

            DROP CONSTRAINT [IF EXISTS] constraint_name;

        **Changed from core's ``DDLColumnMixin`` default of ``False``.**  That
        inherited ``False`` is the most consequential of the inherited answers
        for a backend whose *only* constraint lifecycle verb is this one: the
        default would have declined the idempotent drop and left BigQuery with
        no way to drop a constraint idempotently.

        The page's own text for the guard is worded in terms of primary keys
        (*"IF EXISTS: If no primary key exists in the def[ault dataset ...]"*),
        which is the page's copy-paste residue -- a primary key is not droppable
        on BigQuery at all.  The bracket is in the grammar, so the guard is
        available; the prose is not evidence about which constraints it covers.

        BigQuery therefore matches MariaDB, PostgreSQL, SQL Server and
        ClickHouse, and differs from MySQL (no ``DROP CONSTRAINT IF EXISTS`` at
        all) and from Firebird and SQLite.

        文档（待云验）: grammar-only, not server-verified.
        """
        return True

    def supports_table_drop_foreign_key_constraint(self) -> bool:
        """True: ``DROP CONSTRAINT`` reaches the foreign key and nothing else.

        Official grammar: *"You can use this statement to drop foreign key
        constraints from a table."* -- the statement's own description of its
        reach.

        The mirror of :meth:`supports_table_add_foreign_key_constraint`, and the
        reason :meth:`supports_drop_constraint` can be ``True`` without being
        misleading.

        文档（待云验）: grammar-only, not server-verified.
        """
        return True

    def supports_constraint_novalidate(self) -> bool:
        """False: no ``NOT VALID`` on BigQuery's ADD statement.

        Official grammar: the ADD production ends at the compulsory
        ``NOT ENFORCED`` followed by ``[ADD...]``.  There is no ``NOT VALID``,
        and the page does not mention the clause anywhere.

        Declared locally rather than left absent.  On this core no
        ``ConstraintMixin`` or ``DDLColumnMixin`` declares the probe at all --
        ``BigQueryDialect`` was reaching only the ``ConstraintSupport``
        Protocol stub, whose body is not an implementation -- so the
        ``UnsupportedFeatureError`` in ``_format_constraint_validation`` was
        resting on that stub rather than on a BigQuery statement.  Now it rests
        on the grammar.

        Nothing needs an unvalidated state here, which is a stronger reason
        than the absence of the token: a BigQuery constraint is unenforced from
        the moment it exists (:meth:`supports_constraint_enforced`), so there is
        no "add it but do not validate it yet" window to defer.

        文档（待云验）: grammar-only, not server-verified.
        """
        return False

    def supports_validate_constraint(self) -> bool:
        """False: there is no ``VALIDATE CONSTRAINT`` statement on the page.

        Official grammar: the page defines exactly two constraint operations
        under ``ALTER TABLE`` -- ``ADD ... FOREIGN KEY`` and ``DROP CONSTRAINT``
        (both quoted at :meth:`supports_add_constraint`).  Neither validates,
        and no third statement exists.

        Declared locally: core already answers ``False``; this is the pin.

        文档（待云验）: grammar-only, not server-verified.
        """
        return False

    def supports_table_rename_constraint(self) -> bool:
        """False: no ``RENAME CONSTRAINT ... TO ...``.

        Official grammar: the two ``ALTER TABLE`` constraint statements are
        quoted in full at :meth:`supports_add_constraint`; a rename is not one
        of them.

        Worth contrasting, because the two "absent spellings" are absent for
        different reasons elsewhere: PostgreSQL and Oracle have a real
        ``RENAME CONSTRAINT``; SQL Server reaches the same effect through the
        stored procedure ``sp_rename`` with its two-argument form.  BigQuery has
        neither the statement nor the escape hatch.

        Because a foreign key *is* nameable, a rename would be expressible if
        the statement existed -- the name is the only thing missing.  That is a
        real gap in BigQuery's DDL, not a gap in this backend.

        文档（待云验）: grammar-only, not server-verified.
        """
        return False

    def supports_table_alter_constraint(self) -> bool:
        """False: no ``ALTER CONSTRAINT`` statement on the page.

        Official grammar: see :meth:`supports_table_rename_constraint` -- the
        page's ``ALTER TABLE`` constraint vocabulary is ``ADD`` and ``DROP``,
        nothing else.

        This is the switch the flat
        :meth:`supports_alter_constraint_enforced`` answers alongside: a
        BigQuery constraint's only mutable property would be its enforcement
        state, and the statement that would change it does not exist.

        文档（待云验）: grammar-only, not server-verified.
        """
        return False

    # ------------------------------------------------------------------
    # The ``ON DELETE`` / ``ON UPDATE`` pair that lives on ``DDLColumnMixin``
    # rather than on ``ConstraintMixin``.
    #
    # These two *are* consulted by core's ``format_references_clause``, which
    # makes them the switches that actually stop a referential action from
    # being rendered.  Both default to ``True`` in core; both change to
    # ``False`` here.
    # ------------------------------------------------------------------

    def supports_foreign_key_on_delete(self) -> bool:
        """False -- and this is the probe that stops ``ON DELETE`` being rendered.

        Official grammar::

            foreign_reference :=
            REFERENCES primary_key_table(column_name[, ...]) NOT ENFORCED

        ``core.dialect.mixins.ddl_column.DDLColumnMixin.format_references_clause``
        consults ``supports_foreign_key_on_delete()`` and raises
        ``UnsupportedFeatureError(self.name, "FOREIGN KEY ON DELETE")`` when it
        declines.  ``DDLColumnMixin`` defaults it to ``True``, so the inherited
        value rendered `` ON DELETE CASCADE`` onto a BigQuery reference clause.

        Note the difference from the flat
        :meth:`supports_fk_on_delete` above, which states the same fact for the
        ``ConstraintMixin`` half of the same question: **this** one is the gate
        with teeth.  Both are declared so the two halves cannot drift.

        文档（待云验）: grammar-only, not server-verified.
        """
        return False

    def supports_foreign_key_on_update(self) -> bool:
        """False -- the gate that stops ``ON UPDATE`` being rendered.

        Official grammar::

            foreign_reference :=
            REFERENCES primary_key_table(column_name[, ...]) NOT ENFORCED

        Same production and same reasoning as
        :meth:`supports_foreign_key_on_delete`:
        ``DDLColumnMixin.format_references_clause`` raises on ``False``, and
        ``DDLColumnMixin`` defaults the switch to ``True``.

        文档（待云验）: grammar-only, not server-verified.
        """
        return False

    # ------------------------------------------------------------------
    # The render-path narrowing (S3): the public formatters core dispatches to.
    #
    # The probes above answer "does the clause exist" and take no kind.  The
    # kind is the branch class -- the only thing that can name it -- so the
    # per-kind answer is expressed here, in the two public formatters a
    # constraint clause reaches.  No private formatter is added (the ``_``
    # helpers are called from these), which is the seam the guide asks for.
    # ------------------------------------------------------------------

    def format_column_constraint(self, constraint: "ColumnConstraint") -> "Tuple[str, tuple]":
        """Render a column constraint, enforcing BigQuery's narrow marker rule.

        ``column_schema`` writes ``NOT ENFORCED`` into the two branches it
        has, so the dialect must accept the marker -- but it has no ``ENFORCED``
        token and no third kind to put it on.  Core consults no per-kind probe
        on this path (the S3 production-level trait renderer asks only
        ``supports_constraint_enforced``), so the narrowing is here, before the
        prefix and the branch are rendered: a request the grammar cannot spell
        is refused by name instead of being written into SQL the parser rejects.

        Delegation to :meth:`format_constraint_branch` / the core renderer is
        what a request the grammar *can* spell takes.

        Raises:
            UnsupportedFeatureError: ``enforced=True`` (no such token), or the
                marker on a branch that cannot carry it.
        """
        self._require_bigquery_enforcement(constraint)
        return super().format_column_constraint(constraint)

    def format_table_constraint(self, expr: "TableConstraint") -> "Tuple[str, tuple]":
        """Render a table constraint, refusing the kinds BigQuery has no production for.

        ``constraint_definition`` admits a bare primary key and a (possibly
        named) foreign key; ``CHECK`` and ``UNIQUE`` cannot be written at this
        level at all.  Core dispatches by branch and consults no per-kind
        probe here, so the refusal is this dialect's own -- and it happens
        before the ``CONSTRAINT <name>`` prefix, so a caller is told the kind
        is unavailable rather than handed a named constraint the server would
        reject.

        Raises:
            UnsupportedFeatureError: A table-level ``CHECK`` or ``UNIQUE``, or
                an enforcement-trait request the grammar cannot spell.
        """
        self._require_bigquery_table_kind(expr)
        self._require_bigquery_enforcement(expr)
        return super().format_table_constraint(expr)


__all__ = ["BigQueryConstraintMixin", "OFFICIAL_GRAMMAR_URL"]
