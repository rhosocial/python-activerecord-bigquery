# tests/rhosocial/activerecord_bigquery_test/feature/backend/test_bigquery_constraint_switches.py
"""BigQuery constraint capability switches, pinned to the official grammar.

**Evidence level: 文档（待云验） — official grammar only, not server-verified.**
Every value asserted here was transcribed from the official DDL reference's
``column_schema`` / ``constraint_definition`` / ``ALTER TABLE`` productions on
2026-10-12. Nothing was measured: there is no BigQuery instance reachable from
this repository's environment, and the CI emulator (``goccy/bigquery-emulator``
on ``localhost:9050``) does not implement either of the two ``ALTER TABLE``
constraint statements, so it cannot adjudicate them either. The grammar is
quoted in the docstrings of
``rhosocial.activerecord.backend.impl.bigquery.mixins.constraint``; this module
pins the values and checks that they are load-bearing.

Source of every quote:
  https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language

Five guards beyond the values themselves:

* **declared here, not inherited.** Before this change the backend declared
  **zero** constraint switches and took all of them from core, whose defaults
  answer ``True`` for ``CHECK``, ``UNIQUE``, ``MATCH``, ``DEFERRABLE`` and both
  referential actions — every one of which BigQuery's grammar rejects. That is
  the highest-risk inheritance position in the group, so each switch must be
  declared by a class in *this* package and a moved core default must not be
  able to move BigQuery's contract.
* **the probes take no argument.** A probe answers whether the capability family
  exists on this dialect, not which kind may use it; the per-kind answers are
  the render path's (see :class:`TestTheRenderPathNarrowsByKind`).
* **each docstring says it is not live-verified.** A ``待云验`` marker is this
  repository's standing convention for "a real BigQuery run must confirm this";
  asserted per switch so a later edit cannot quietly drop the caveat.
* **the one-notch finding, asserted as a whole.** BigQuery's CREATE side admits
  primary keys and foreign keys only, and its ALTER side admits foreign keys
  only. ``CHECK`` and ``UNIQUE`` are ``False`` at *both* levels, and only a
  table-level foreign key can be named.
* **``NOT ENFORCED`` is mandatory, so the enforcement switch is ``True``.**
  This reads backwards until you see the grammar: the token is inside the
  production, so a dialect that refused to spell it could not express a primary
  key or a foreign key at all. Asserted separately with the quoting, because it
  is the value a future reader is most likely to "fix" to ``False``.
"""

import inspect

import pytest
from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError
from rhosocial.activerecord.backend.expression.core import Column
from rhosocial.activerecord.backend.expression.objects import Table
from rhosocial.activerecord.backend.expression.predicates import ComparisonPredicate
from rhosocial.activerecord.backend.expression.statements.ddl_table import (
    ColumnCheckConstraint,
    ColumnConstraint,
    ColumnDefinition,
    ColumnForeignKeyConstraint,
    ColumnNotNullConstraint,
    ColumnPrimaryKeyConstraint,
    ColumnUniqueConstraint,
    ReferencesClause,
    TableCheckConstraint,
    TableConstraint,
    TableForeignKeyConstraint,
    TablePrimaryKeyConstraint,
    TableUniqueConstraint,
)
from rhosocial.activerecord.backend.expression.types import VarCharType

from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect
from rhosocial.activerecord.backend.impl.bigquery.mixins import constraint as constraint_module
from rhosocial.activerecord.backend.impl.bigquery.mixins.constraint import (
    OFFICIAL_GRAMMAR_URL,
    BigQueryConstraintMixin,
)

#: The mixin's **module** docstring, where the evidence level and the remaining
#: render-path gaps are recorded. Deliberately not ``__doc__`` on the class:
#: that resolves to the class docstring, which restates the level but is not
#: where the gaps live.
MODULE_DOC = constraint_module.__doc__ or ""

#: Every switch this backend relies on must come from this package. A switch
#: declared in core's ``ConstraintMixin`` / ``DDLColumnMixin`` is not an answer
#: for BigQuery; it is an accident waiting for a core default to move.
BACKEND_PACKAGE = "rhosocial.activerecord.backend.impl.bigquery."

#: The page every grammar quote in the mixin's docstrings was transcribed from.
#: Pinned here so the mixin and this module cannot drift onto different pages.
EXPECTED_GRAMMAR_URL = (
    "https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language"
)

#: (switch name, grammar value) pairs. The value is hard-coded on purpose:
#: reading it back from the dialect would make the test unable to see a moved
#: default.
#:
#: Grouped the way the grammar groups them, because that grouping *is* the
#: finding: the column level (``column_schema``) carries two kinds, neither
#: nameable; the table level (``constraint_definition``) carries the same two,
#: but only the foreign key may be named; the ALTER side carries foreign keys
#: only.
GRAMMAR_SWITCHES = (
    # -- column level: column_schema ----------------------------------------
    ("supports_column_primary_key_constraint", True),
    ("supports_column_foreign_key_constraint", True),
    # CHECK and UNIQUE are in none of column_schema's four optional groups.
    ("supports_column_check_constraint", False),
    ("supports_column_unique_constraint", False),
    # ``column_schema``'s first group has no CONSTRAINT keyword at all, so no
    # column-level constraint on BigQuery can be named.
    ("supports_column_naming_primary_key_constraint", False),
    ("supports_column_naming_foreign_key_constraint", False),
    # NOT ENFORCED is inside the production -> mandatory, so "can this dialect
    # spell an enforcement marker" is True; the two kinds that do not exist
    # cannot carry one.
    ("supports_column_enforced_primary_key_constraint", True),
    ("supports_column_enforced_foreign_key_constraint", True),
    ("supports_column_enforced_check_constraint", False),
    ("supports_column_enforced_unique_constraint", False),
    # -- table level: constraint_definition ---------------------------------
    ("supports_table_primary_key_constraint", True),
    ("supports_table_foreign_key_constraint", True),
    ("supports_table_check_constraint", False),
    ("supports_table_unique_constraint", False),
    # ``[primary_key]`` is bare; ``[[CONSTRAINT constraint_name] foreign_key, ...]``
    # is not. A BigQuery table primary key cannot be named.
    ("supports_table_naming_primary_key_constraint", False),
    ("supports_table_naming_foreign_key_constraint", True),
    ("supports_table_enforced_primary_key_constraint", True),
    ("supports_table_enforced_foreign_key_constraint", True),
    ("supports_table_enforced_check_constraint", False),
    ("supports_table_enforced_unique_constraint", False),
    # -- flat kind switches core's renderers consult ------------------------
    ("supports_primary_key_constraint", True),
    ("supports_foreign_key_constraint", True),
    ("supports_check_constraint", False),
    ("supports_unique_constraint", False),
    ("supports_not_null_constraint", True),
    ("supports_exclude_constraint", False),
    # -- clauses the reference clause does not have ------------------------
    # ``foreign_reference ::= REFERENCES primary_key_table ( column_name[, ...] )
    # NOT ENFORCED`` -- four tokens, nothing else.
    ("supports_fk_on_delete", False),
    ("supports_fk_on_update", False),
    ("supports_fk_match", False),
    ("supports_deferrable_constraint", False),
    # The ``DDLColumnMixin`` pair, which is what actually stops ``ON DELETE`` /
    # ``ON UPDATE`` being rendered by ``format_references_clause``.
    ("supports_foreign_key_on_delete", False),
    ("supports_foreign_key_on_update", False),
    # -- enforcement control -------------------------------------------------
    # NOT ENFORCED is mandatory on the CREATE and ADD paths -> True. There is no
    # ALTER CONSTRAINT statement at all -> False.
    ("supports_constraint_enforced", True),
    ("supports_alter_constraint_enforced", False),
    # -- ALTER TABLE lifecycle ----------------------------------------------
    # The operation exists (it adds a foreign key); the three other kinds cannot
    # be added by any statement.
    ("supports_add_constraint", True),
    ("supports_add_constraint_if_not_exists", True),
    ("supports_table_add_foreign_key_constraint", True),
    ("supports_table_add_primary_key_constraint", False),
    ("supports_table_add_check_constraint", False),
    ("supports_table_add_unique_constraint", False),
    # ``DROP CONSTRAINT [IF EXISTS] constraint_name`` -- and a foreign key is the
    # only nameable constraint, so that is the only kind it reaches.
    ("supports_drop_constraint", True),
    ("supports_drop_constraint_if_exists", True),
    ("supports_table_drop_foreign_key_constraint", True),
    # Everything else in the lifecycle vocabulary has no production.
    ("supports_constraint_novalidate", False),
    ("supports_validate_constraint", False),
    ("supports_table_rename_constraint", False),
    ("supports_table_alter_constraint", False),
)


def _dialect():
    return BigQueryDialect()


def _declaring_class(switch_name):
    """The first class in the dialect's MRO that declares ``switch_name``."""
    for cls in BigQueryDialect.__mro__:
        if switch_name in cls.__dict__:
            return cls
    raise AssertionError(f"no class in the MRO declares {switch_name}()")


def _predicate(d):
    return ComparisonPredicate(d, "=", Column(d, "a"), Column(d, "b"))


def _references(d):
    return Table(d, "p")


class TestGrammarSwitchValues:
    @pytest.mark.parametrize(
        "switch_name,expected",
        GRAMMAR_SWITCHES,
        ids=[s for s, _ in GRAMMAR_SWITCHES],
    )
    def test_matches_the_official_grammar(self, switch_name, expected):
        dialect = _dialect()
        assert getattr(dialect, switch_name)() is expected, (
            f"{switch_name}() no longer matches the official grammar "
            f"transcription; see the docstring in mixins/constraint.py for the "
            f"production that decided it."
        )

    @pytest.mark.parametrize(
        "switch_name,_expected",
        GRAMMAR_SWITCHES,
        ids=[s for s, _ in GRAMMAR_SWITCHES],
    )
    def test_declared_by_this_backend(self, switch_name, _expected):
        """A moved core default must not move BigQuery's contract silently.

        This backend used to declare none of these and take every answer from
        core's ``ConstraintMixin`` / ``DDLColumnMixin``, whose defaults are
        ``True`` for ``supports_check_constraint``,
        ``supports_unique_constraint``, ``supports_fk_match``,
        ``supports_deferrable_constraint``, ``supports_fk_on_delete``,
        ``supports_fk_on_update``, ``supports_foreign_key_on_delete`` and
        ``supports_foreign_key_on_update`` -- eight answers that are the exact
        opposite of what BigQuery's grammar says.
        """
        declaring = _declaring_class(switch_name)
        assert declaring.__module__.startswith(BACKEND_PACKAGE), (
            f"{switch_name} is inherited from {declaring.__module__}; declare it "
            f"in this backend's mixins so the grammar answer is explicit."
        )

    @pytest.mark.parametrize(
        "switch_name,_expected",
        GRAMMAR_SWITCHES,
        ids=[s for s, _ in GRAMMAR_SWITCHES],
    )
    def test_probes_take_no_argument(self, switch_name, _expected):
        """``(self)`` and nothing else -- the round's probe protocol.

        A probe answers one question ("does this clause family exist here") and
        the kind is not part of it. A parameterised probe has two call shapes
        depending on its own signature, which is exactly how the draft this
        change replaces ended up carrying a kind the formatter had to guess at.
        Checked on the bound method, so a defaulted parameter cannot slip back
        in behind an ``= None``.
        """
        bound = getattr(_dialect(), switch_name)
        params = inspect.signature(bound).parameters
        assert list(params) == [], (
            f"{switch_name} must take only (self); it declares {list(params)}. "
            f"The per-kind narrowing lives on the render path, in this "
            f"dialect's own formatters."
        )


class TestEvidenceIsMarkedGrammarOnly:
    """A reader must not mistake a transcription for a measurement.

    The ``文档（待云验）`` marker is this repository's standing convention for
    "a real BigQuery run must confirm this before a caller relies on it". It is
    asserted per switch so a later edit cannot quietly drop the caveat, and the
    module docstring is checked for the plain-English restatement so the
    finding is legible to someone who does not read the Chinese marker.
    """

    @pytest.mark.parametrize(
        "switch_name", [s for s, _ in GRAMMAR_SWITCHES], ids=[s for s, _ in GRAMMAR_SWITCHES]
    )
    def test_each_docstring_marks_itself_not_live_verified(self, switch_name):
        doc = inspect.getdoc(getattr(BigQueryConstraintMixin, switch_name)) or ""
        assert "待云验" in doc, (
            f"{switch_name}'s docstring must carry the 文档（待云验） marker. Every "
            f"value here is read off the official grammar and none of it was "
            f"measured: no BigQuery instance is reachable from this environment "
            f"and the CI emulator implements neither ALTER TABLE constraint "
            f"statement."
        )

    def test_the_module_says_plainly_that_nothing_was_measured(self):
        assert "文档（待云验）" in MODULE_DOC
        assert "Nothing here was measured" in MODULE_DOC
        assert "localhost:9050" in MODULE_DOC, (
            "The module must name the emulator and say why it cannot adjudicate "
            "these switches -- otherwise a reader may assume the emulator was "
            "used as evidence."
        )
        assert "official-grammar-only" in MODULE_DOC

    def test_the_grammar_url_is_pinned_in_one_place(self):
        assert OFFICIAL_GRAMMAR_URL == EXPECTED_GRAMMAR_URL


class TestConstraintCapabilityIsOneNotch:
    """BigQuery has primary keys and foreign keys, and nothing else.

    ``CREATE TABLE`` admits exactly two kinds; ``ALTER TABLE`` admits exactly
    one. This is the finding the whole matrix hangs on, so it is asserted on
    its own rather than only through the per-switch parametrization.
    """

    def test_create_side_admits_exactly_primary_key_and_foreign_key(self):
        dialect = _dialect()
        advertised = {
            name: getattr(dialect, name)()
            for name in (
                "supports_column_primary_key_constraint",
                "supports_column_foreign_key_constraint",
                "supports_column_check_constraint",
                "supports_column_unique_constraint",
            )
        }
        assert advertised == {
            "supports_column_primary_key_constraint": True,
            "supports_column_foreign_key_constraint": True,
            "supports_column_check_constraint": False,
            "supports_column_unique_constraint": False,
        }

    def test_check_and_unique_are_false_at_both_levels(self):
        """The one pair a reader is most likely to expect to differ.

        ClickHouse's equivalent pair is ``False`` at column level and ``True``
        at table level. BigQuery has no ``CHECK`` at either level: neither
        ``column_schema``'s four optional groups nor ``constraint_definition``'s
        two branches mentions it. The asymmetry between the two backends is the
        engines', not a transcription slip.
        """
        dialect = _dialect()
        assert dialect.supports_check_constraint() is False
        assert dialect.supports_table_check_constraint() is False
        assert dialect.supports_unique_constraint() is False
        assert dialect.supports_table_unique_constraint() is False

    def test_only_a_table_level_foreign_key_can_be_named(self):
        """``[primary_key]`` is bare; ``[[CONSTRAINT n] foreign_key, ...]`` is not.

        Official grammar, verbatim::

            constraint_definition :=
            [primary_key]
            | [[CONSTRAINT constraint_name] foreign_key, ...]

        So a BigQuery table's primary key cannot be named -- which is also why
        ``DROP CONSTRAINT`` cannot reach it.
        """
        dialect = _dialect()
        assert dialect.supports_table_naming_foreign_key_constraint() is True
        assert dialect.supports_table_naming_primary_key_constraint() is False
        assert dialect.supports_column_naming_foreign_key_constraint() is False
        assert dialect.supports_column_naming_primary_key_constraint() is False

    def test_alter_table_adds_a_foreign_key_and_nothing_else(self):
        """``ALTER TABLE ADD FOREIGN KEY statement`` -- that is the whole heading.

        Of the four kinds BigQuery knows at ``CREATE`` time, exactly one
        survives to ``ALTER`` time. Every other backend measured this session
        either adds all four kinds (MySQL, MariaDB, PostgreSQL, SQL Server,
        Oracle, Snowflake, Firebird) or none (SQLite); BigQuery is the only one
        in between.
        """
        dialect = _dialect()
        assert dialect.supports_table_add_foreign_key_constraint() is True
        assert dialect.supports_table_add_primary_key_constraint() is False
        assert dialect.supports_table_add_check_constraint() is False
        assert dialect.supports_table_add_unique_constraint() is False

    def test_drop_reaches_the_foreign_key_and_nothing_else(self):
        dialect = _dialect()
        assert dialect.supports_drop_constraint() is True
        assert dialect.supports_table_drop_foreign_key_constraint() is True
        # The lifecycle verbs BigQuery's grammar simply does not contain.
        assert dialect.supports_table_rename_constraint() is False
        assert dialect.supports_table_alter_constraint() is False
        assert dialect.supports_validate_constraint() is False
        assert dialect.supports_constraint_novalidate() is False


class TestNotEnforcedIsMandatory:
    """The value that reads backwards until you see the grammar.

    ``NOT ENFORCED`` is written into the production, not into a ``[NOT]``
    optional group, so a dialect that refused to spell it could not express a
    primary key or a foreign key at all. ``False`` would be the wrong fix.
    """

    def test_the_marker_is_inside_every_production_that_has_one(self):
        doc = inspect.getdoc(BigQueryConstraintMixin.supports_constraint_enforced) or ""
        for production in (
            "[PRIMARY KEY NOT ENFORCED",
            "REFERENCES table_name(column_name) NOT ENFORCED",
            "primary_key := PRIMARY KEY (column_name[, ...]) NOT ENFORCED",
            "REFERENCES pk_table_name(pk_column_name[,...]) NOT ENFORCED",
        ):
            assert production in doc, (
                f"the docstring must quote {production!r} verbatim so the True "
                f"reads as 'mandatory' rather than 'optional'"
            )

    def test_the_switch_is_true_for_exactly_the_kinds_that_exist(self):
        dialect = _dialect()
        assert dialect.supports_column_enforced_primary_key_constraint() is True
        assert dialect.supports_column_enforced_foreign_key_constraint() is True
        assert dialect.supports_table_enforced_primary_key_constraint() is True
        assert dialect.supports_table_enforced_foreign_key_constraint() is True
        # The other two cannot carry a marker because they do not exist.
        assert dialect.supports_column_enforced_check_constraint() is False
        assert dialect.supports_column_enforced_unique_constraint() is False
        assert dialect.supports_table_enforced_check_constraint() is False
        assert dialect.supports_table_enforced_unique_constraint() is False

    def test_alter_constraint_enforcement_is_unreachable_not_refused(self):
        """``NOT ENFORCED`` is compulsory on ADD and unreachable on ALTER.

        The grammar's two ``ALTER TABLE`` statements are ``ADD ...
        FOREIGN KEY ... NOT ENFORCED`` (a creation-time statement that carries
        the marker in its own production) and ``DROP CONSTRAINT``. There is no
        ``ALTER CONSTRAINT``, so a BigQuery constraint's enforcement state
        cannot be changed after the fact -- which is a different answer from
        "the clause is refused", and the two switches therefore differ.
        """
        dialect = _dialect()
        assert dialect.supports_constraint_enforced() is True
        assert dialect.supports_alter_constraint_enforced() is False


class TestTheRenderPathNarrowsByKind:
    """The per-kind half of the enforcement answer, and where it is enforced.

    Nothing in the switch table selects a kind; a probe answers whether the
    clause family exists. Which constraints may carry the clause is a property
    of the branch class, so the narrowing is this dialect's own -- in the two
    public formatters a constraint clause dispatches to, and nowhere else. The
    request the grammar can spell renders; the request it cannot is refused by
    name.
    """

    def test_primary_key_takes_the_mandatory_marker(self):
        """The kind BigQuery must be able to spell -- and now can.

        On the core this change replaces, ``format_primary_key_constraint``
        raised ``ValueError`` for any kind but CHECK / FOREIGN KEY before the
        probe was reached, so a BigQuery primary key could not carry its
        compulsory ``NOT ENFORCED`` at all. S3 moved the trait to the
        production, so the same request now renders.
        """
        d = _dialect()
        sql, params = d.format_column_constraint(
            ColumnConstraint(
                d,
                branch=ColumnPrimaryKeyConstraint(d),
                not_enforced=True,
            )
        )
        assert sql == " PRIMARY KEY NOT ENFORCED", sql
        assert params == ()

    def test_foreign_key_takes_the_mandatory_marker(self):
        d = _dialect()
        sql, _ = d.format_column_constraint(
            ColumnConstraint(
                d,
                branch=ColumnForeignKeyConstraint(d, (_references(d), ["id"])),
                not_enforced=True,
            )
        )
        assert sql == " REFERENCES `p`(`id`) NOT ENFORCED", sql

    def test_the_bare_enforced_token_is_refused_on_every_kind(self):
        """BigQuery has no ``ENFORCED`` spelling, so asking for one is refused.

        Asserted on both levels and on all four kinds that exist here, because
        the same fact decides all of them and a reader is most likely to
        "fix" the switch to ``False`` rather than the render path.
        """
        d = _dialect()
        column_cases = (
            ColumnPrimaryKeyConstraint(d),
            ColumnForeignKeyConstraint(d, (_references(d), ["id"])),
        )
        for branch in column_cases:
            with pytest.raises(UnsupportedFeatureError) as exc:
                d.format_column_constraint(ColumnConstraint(d, branch=branch, enforced=True))
            assert "ENFORCED" in exc.value.feature_name
            assert "NOT ENFORCED" not in exc.value.feature_name

        table_cases = (
            TablePrimaryKeyConstraint(d, ["a"]),
            TableForeignKeyConstraint(d, ["a"], (_references(d), ["id"])),
        )
        for branch in table_cases:
            with pytest.raises(UnsupportedFeatureError) as exc:
                d.format_table_constraint(TableConstraint(d, branch=branch, enforced=True))
            assert "ENFORCED" in exc.value.feature_name
            assert "NOT ENFORCED" not in exc.value.feature_name

    def test_the_table_level_check_and_unique_are_refused_by_name(self):
        """Core gates no per-kind table switch, so the refusal is this dialect's.

        ``constraint_definition`` has two branches and neither is CHECK or
        UNIQUE. Core's ``format_table_constraint`` dispatches by branch without
        consulting a probe (only EXCLUDE is gated there), so the honest
        ``False`` values in the switch table would not by themselves stop
        ``CREATE TABLE ... (CONSTRAINT ck CHECK (...))`` from rendering. The
        dialect's own formatter is what refuses it.
        """
        d = _dialect()
        with pytest.raises(UnsupportedFeatureError) as exc:
            d.format_table_constraint(
                TableConstraint(d, branch=TableCheckConstraint(d, _predicate(d)), name="ck")
            )
        assert exc.value.feature_name == "CHECK table constraint"

        with pytest.raises(UnsupportedFeatureError) as exc:
            d.format_table_constraint(
                TableConstraint(d, branch=TableUniqueConstraint(d, ["a"]), name="uq")
            )
        assert exc.value.feature_name == "UNIQUE table constraint"

    def test_the_refusal_wins_over_the_name_prefix(self):
        """A named CHECK is refused for its kind, not rendered as a constraint.

        The ordering matters: checking the kind after the prefix would make the
        message depend on whether a name happened to be attached.
        """
        d = _dialect()
        with pytest.raises(UnsupportedFeatureError) as exc:
            d.format_table_constraint(
                TableConstraint(
                    d,
                    branch=TableCheckConstraint(d, _predicate(d)),
                    name="named_check",
                )
            )
        assert exc.value.feature_name == "CHECK table constraint"

    def test_the_marker_is_refused_on_a_check_branch_that_cannot_exist(self):
        """``NOT ENFORCED`` on a column CHECK: the kind is gone before the marker.

        The column CHECK is refused by :meth:`supports_check_constraint` inside
        core's branch formatter, so the marker never gets a chance -- which is
        the right outcome and is asserted so the two refusals do not get
        accidentally reordered.
        """
        d = _dialect()
        with pytest.raises(UnsupportedFeatureError):
            d.format_column_constraint(
                ColumnConstraint(
                    d,
                    branch=ColumnCheckConstraint(d, _predicate(d)),
                    not_enforced=True,
                )
            )

    def test_a_subclass_that_widens_the_probe_does_not_gain_a_marker(self):
        """The narrowing is the formatter's, not the probe's.

        ``supports_constraint_enforced`` is ``True`` here already; the reason a
        wrong marker is refused is the render path. A subclass that flips the
        probe cannot therefore make ``enforced=True`` render -- only the
        dialect's own formatter can decide that, and it refuses.
        """

        class _NoEnforcement(BigQueryDialect):
            def supports_constraint_enforced(self) -> bool:
                return False

        d = _NoEnforcement()
        assert d.supports_constraint_enforced() is False
        # The refusal is the dialect's own formatter, which runs first.
        with pytest.raises(UnsupportedFeatureError) as exc:
            d.format_column_constraint(
                ColumnConstraint(
                    d,
                    branch=ColumnPrimaryKeyConstraint(d),
                    enforced=True,
                )
            )
        assert "PRIMARY KEY ENFORCED" == exc.value.feature_name


class TestRefusalsTheFalseValuesProduce:
    """What the corrections actually stop, reached the way a caller reaches it.

    Each of these was rendering BigQuery-rejected SQL before the declarations
    landed: ``CHECK (...)`` and ``UNIQUE`` in a column definition,
    ``MATCH FULL`` / ``ON DELETE`` / ``ON UPDATE`` / ``DEFERRABLE`` on a
    ``REFERENCES`` clause.
    """

    def test_column_check_is_refused_by_name(self):
        d = _dialect()
        branch = ColumnCheckConstraint(d, _predicate(d))
        with pytest.raises(UnsupportedFeatureError, match="CHECK column constraint"):
            d.format_column_check_constraint(branch)

    def test_column_check_is_refused_on_the_full_column_path(self):
        """The same refusal through the dispatcher a ``ColumnDefinition`` takes."""
        d = _dialect()
        constraint = ColumnConstraint(d, branch=ColumnCheckConstraint(d, _predicate(d)))
        with pytest.raises(UnsupportedFeatureError, match="CHECK column constraint"):
            d.format_column_constraint(constraint)

    def test_column_unique_is_refused_by_name(self):
        d = _dialect()
        with pytest.raises(UnsupportedFeatureError, match="UNIQUE column constraint"):
            d.format_column_constraint(
                ColumnConstraint(d, branch=ColumnUniqueConstraint(d))
            )

    def test_fk_match_is_refused_on_the_references_clause(self):
        d = _dialect()
        with pytest.raises(UnsupportedFeatureError, match="FOREIGN KEY MATCH"):
            d.format_references_clause(
                ReferencesClause(d, _references(d), ["id"], match_type="FULL")
            )

    def test_fk_on_delete_is_refused_on_the_references_clause(self):
        d = _dialect()
        with pytest.raises(UnsupportedFeatureError, match="FOREIGN KEY ON DELETE"):
            d.format_references_clause(
                ReferencesClause(d, _references(d), ["id"], on_delete="CASCADE")
            )

    def test_fk_on_update_is_refused_on_the_references_clause(self):
        d = _dialect()
        with pytest.raises(UnsupportedFeatureError, match="FOREIGN KEY ON UPDATE"):
            d.format_references_clause(
                ReferencesClause(d, _references(d), ["id"], on_update="CASCADE")
            )

    def test_deferrable_is_refused_on_the_references_clause(self):
        d = _dialect()
        with pytest.raises(UnsupportedFeatureError, match="DEFERRABLE"):
            d.format_references_clause(
                ReferencesClause(d, _references(d), ["id"], deferrable=True)
            )

    def test_exclude_is_refused_by_name_on_the_table_path(self):
        """The one kind whose absence core's ``format_table_constraint`` gates on."""
        from rhosocial.activerecord.backend.expression.statements.ddl_table import (
            TableExcludeConstraint,
        )

        d = _dialect()
        with pytest.raises(UnsupportedFeatureError):
            d.format_table_constraint(
                TableConstraint(d, branch=TableExcludeConstraint(d, ["a"]), name="ex")
            )


class TestKnownRenderPathGapsAreRecordedNotPinned:
    """The values are right; a few generic renderers still do not act on them.

    These are **not** assertions of desired behaviour -- they are here so the
    gaps stay visible and named. Nothing below asserts that today's output is
    correct; each says what is still missing, so a future change to any of these
    renderers has a place to go.
    """

    def test_not_enforced_is_still_only_rendered_when_a_caller_asks(self):
        """The remaining gap, on the foreign-key path: no auto-emission.

        ``format_constraint_traits`` renders the marker only when
        ``constraint.not_enforced`` is set, so a caller who does not set it gets
        ``REFERENCES `p`(`id`)`` -- a shape BigQuery's grammar does not have.
        The *wrong* spelling is refused by this dialect (see
        :class:`TestTheRenderPathNarrowsByKind`); insisting on the right one is
        a core printing decision, out of this change's scope.
        """
        d = _dialect()
        silent = d.format_column_constraint(
            ColumnConstraint(
                d,
                branch=ColumnForeignKeyConstraint(d, (_references(d), ["id"])),
            )
        )
        explicit = d.format_column_constraint(
            ColumnConstraint(
                d,
                branch=ColumnForeignKeyConstraint(d, (_references(d), ["id"])),
                not_enforced=True,
            )
        )
        assert "NOT ENFORCED" not in silent[0]
        assert explicit[0].endswith("NOT ENFORCED")

    def test_the_primary_key_reaches_its_marker_but_not_by_default(self):
        """The sharp half of the same gap, now reachable on the primary-key path.

        S3 moved the trait to the production, so ``not_enforced=True`` on a
        BigQuery primary key renders (it used to be a ``ValueError``). What
        remains is that the marker is still opt-in: the dialect does not add it
        for a caller who omits it.
        """
        d = _dialect()
        sql, _ = d.format_column_constraint(
            ColumnConstraint(
                d,
                branch=ColumnPrimaryKeyConstraint(d),
                not_enforced=True,
            )
        )
        assert sql.endswith("NOT ENFORCED"), sql
        bare, _ = d.format_column_constraint(
            ColumnConstraint(d, branch=ColumnPrimaryKeyConstraint(d))
        )
        assert "NOT ENFORCED" not in bare

    def test_the_gaps_are_named_where_they_are_recorded(self):
        """Each of the gaps above must also be written down next to the switches.

        A gap that lives only in a test file is a comment; a gap recorded in the
        mixin's module docstring is a contract statement. Both are required.
        """
        for gap in (
            "Still gaps a switch cannot close",
            "``NOT ENFORCED`` is mandatory, and it is only emitted on request",
            "The explicit ``NULL`` column modifier is unguarded",
            "``ADD CONSTRAINT`` renders the wrong shape for a foreign key",
        ):
            assert gap in MODULE_DOC, f"the module docstring must record: {gap!r}"


class TestClauseOrderIsRecordedOnTheRenderPath:
    """``NOT NULL`` comes *after* ``DEFAULT`` on BigQuery -- the opposite of most.

    Official ``column_schema``::

        [PRIMARY KEY NOT ENFORCED | REFERENCES ... NOT ENFORCED]
        [ DEFAULT default_expression | embedding_generation | identity_column ]
        [NOT NULL]
        [OPTIONS(column_option_list)]

    Core renders a column definition as ``attributes`` then ``constraints`` in
    build order and does not sort, so the order is a property of the call site
    rather than of a formatter. The ordering therefore belongs in a **code
    comment on the render path** and not only in a docstring -- and it is
    recorded there, because a constraint mixin's docstring is not what someone
    reordering ``format_column_definition`` will read.
    """

    def test_the_render_path_carries_the_ordering_comment(self):
        from rhosocial.activerecord.backend.impl.bigquery.mixins import ddl as ddl_module

        source = inspect.getsource(ddl_module)
        assert "CLAUSE ORDER ON THE COLUMN RENDER PATH" in source, (
            "mixins/ddl.py is this backend's column render path; the fixed "
            "column_schema ordering must be a comment there, where someone "
            "changing the render order will read it."
        )
        for fragment in (
            "[ DEFAULT default_expression | embedding_generation | identity_column ]",
            "[NOT NULL]",
            "[OPTIONS(column_option_list)]",
        ):
            assert fragment in source, f"the ordering comment must quote {fragment!r}"

    def test_the_ordering_comment_says_the_opposite_of_the_other_backends(self):
        from rhosocial.activerecord.backend.impl.bigquery.mixins import ddl as ddl_module

        source = inspect.getsource(ddl_module)
        assert "comes AFTER the ``DEFAULT``" in source
        assert "does not sort" in source, (
            "the comment must say that nothing sorts the clauses, or a reader "
            "will assume the order is guaranteed by the formatter"
        )

    def test_the_constraint_mixin_names_the_order_too(self):
        """The fact has to be reachable from the switch a reader came for."""
        doc = inspect.getdoc(BigQueryConstraintMixin.supports_not_null_constraint) or ""
        assert "comes AFTER the ``DEFAULT``" in doc

    def test_the_generic_renderer_already_lands_on_the_grammar_order(self):
        """Why BigQuery needs no ``format_column_definition`` override.

        Core renders ``attributes``, then ``constraints`` in build order, then
        the comment clause -- which for a caller that supplies the clauses in
        ``column_schema`` order is ``REFERENCES`` group, then ``DEFAULT``, then
        ``NOT NULL``, then ``OPTIONS``.  Locked here because it is the only
        reason this backend has no column-definition override, and a silent
        reorder in core would quietly produce SQL BigQuery rejects.

        Asserted as an exact string, so a reorder fails loudly rather than
        shifting a clause past another unnoticed.
        """
        d = _dialect()
        column = ColumnDefinition(
            d,
            "id",
            VarCharType(d, 10),
            constraints=[
                ColumnConstraint(
                    d,
                    branch=ColumnForeignKeyConstraint(d, (_references(d), ["id"])),
                    not_enforced=True,
                ),
                ColumnConstraint(d, branch=_default_branch(d, "x")),
                ColumnConstraint(d, branch=ColumnNotNullConstraint(d)),
            ],
            comment=_comment(d, "a note"),
        )
        assert d.format_column_definition(column)[0] == (
            "`id` STRING(10) REFERENCES `p`(`id`) NOT ENFORCED DEFAULT 'x' "
            "NOT NULL OPTIONS(description='a note')"
        )

    def test_reordering_the_clauses_reorders_the_sql(self):
        """The order is the call site's, so the comment's claim is checkable.

        Core sorts nothing, so this is the mirror of the test above: feed the
        clauses in the *wrong* order and the SQL comes out in that wrong order.
        That is why the ordering lives in a comment at the call site rather than
        in a formatter override -- no override could have prevented it.
        """
        d = _dialect()
        column = ColumnDefinition(
            d,
            "id",
            VarCharType(d, 10),
            constraints=[
                ColumnConstraint(d, branch=ColumnNotNullConstraint(d)),
                ColumnConstraint(d, branch=_default_branch(d, "x")),
            ],
        )
        assert d.format_column_definition(column)[0] == ("`id` STRING(10) NOT NULL DEFAULT 'x'")


def _default_branch(d, value):
    from rhosocial.activerecord.backend.expression.statements.ddl_table import (
        ColumnDefaultConstraint,
    )

    return ColumnDefaultConstraint(d, value)


def _comment(d, text):
    from rhosocial.activerecord.backend.expression.statements.ddl_table import (
        ColumnCommentClause,
    )

    return ColumnCommentClause(d, text)
