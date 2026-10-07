# tests/rhosocial/activerecord_bigquery_test/feature/backend/ddl/test_identity_override_conformance.py
"""The BigQuery identity override must stay aligned with core's clause.

``BigQueryIdentityColumnMixin.format_identity_clause`` fully overrides core's
formatter -- it exists to keep the literal option parentheses -- and therefore
owns every per-option gate the clause needs.  Core's expressiveness round split
each two-spelling option into its own parameter pair (``cycle`` / ``no_cycle``,
``order`` / ``no_order``, ``cache`` / ``no_cache``); the override consumes the
pairs, and this file holds it to that.

This file does not list the options it knows about; it enumerates the option
fields from ``IdentityClause.__init__`` itself, so the next field core adds is
exercised without anyone remembering to edit a list here.  For every field the
override must do exactly one of two things:

* render the requested option -- the SQL must differ from the bare clause -- or
* refuse it with ``UnsupportedFeatureError`` naming the requested spelling:
  ``IDENTITY CYCLE`` / ``IDENTITY NO CYCLE`` (and likewise ``order`` /
  ``no_order``, ``cache`` / ``no_cache``).

Rendering the bare clause is the failure: the request was dropped.  The
outcome is also checked against the dialect's own probe (``True`` must render,
``False`` must refuse by name), which is the conformance rule core's own
identity tests state.  A negative field (``no_*``) is gated by its base
option's probe -- ``no_cycle`` by ``supports_identity_cycle`` -- because the
probe answers for the option, and the parameter says which spelling was asked
for.  A permanent sentinel feeds the check an ungated field, so a future drop
is caught rather than trusted.

The spelling half is checked too: option spelling must come from core's
``identity_*_keyword`` hooks, not from words hardcoded in the override.
BigQuery's probes decline cycle / order / cache, so those lines are
unreachable through the public dialect; a subclass that declares an option and
returns a deliberately implausible spelling exercises the delegation.  A
hardcoded ``CYCLE`` / ``NO CYCLE`` (or ``CACHE {n}``) cannot pass it.

``cache=0`` is no longer the spelling of NO CACHE (the sentinel is gone); it is
refused at construction, and that refusal is pinned here as its own state.

**Not server-verified.** No BigQuery instance exists in this repository and CI
has none; the emulator does not implement the Preview identity grammar. Every
assertion here is a render assertion.
"""

import inspect
import typing

import pytest

from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError
from rhosocial.activerecord.backend.expression.statements import IdentityClause
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect

#: ``__init__`` parameters that are not identity options. ``generation`` is
#: the clause mode, gated by ``supports_identity_generation_always`` and
#: covered by the identity tests; the option fields follow it.
_NON_OPTION_PARAMETERS = ("self", "dialect", "generation")

#: The negative spelling of an option is gated by the option's own probe; the
#: parameter picks the spelling, the probe answers for the option.
_PROBE_FOR_FIELD = {
    "no_cycle": "cycle",
    "no_order": "order",
    "no_cache": "cache",
}


def _option_fields(expression_cls=IdentityClause) -> tuple:
    """Every option field, read from the expression's own constructor.

    Enumerating from the signature -- instead of a list kept here -- is the
    point: a field core adds next round arrives in this test by itself.
    """
    parameters = inspect.signature(expression_cls.__init__).parameters
    return tuple(
        name
        for name, parameter in parameters.items()
        if name not in _NON_OPTION_PARAMETERS
        and parameter.kind
        not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
    )


def _annotation_kinds(annotation: object) -> tuple:
    """The non-``None`` types an annotation names (``Optional[int]`` -> ``(int,)``)."""
    if annotation is inspect.Parameter.empty:
        return ()
    arguments = typing.get_args(annotation) or (annotation,)
    return tuple(
        typing.get_origin(argument) or argument
        for argument in arguments
        if argument is not type(None)
    )


def _requested_values(field: str, parameter: inspect.Parameter) -> tuple:
    """Values that request this field's spelling.

    A bool option requests its spelling with ``True`` only: the negative
    spelling is now a parameter of its own, so ``cycle=False`` is the default
    and requests nothing.  An int option is requested with a positive count
    (``cache=0`` is refused at construction and pinned separately); a
    zero-length start / increment is a real request and is exercised too.
    """
    kinds = _annotation_kinds(parameter.annotation)
    if bool in kinds:
        return (True,)
    if int in kinds:
        return (10,) if field == "cache" else (10, 0)
    if str in kinds:
        return ("x",)
    return (True,)


def _check_option(dialect, expression_cls, field) -> None:
    """Assert one option field is rendered or refused by name, never dropped.

    Raises ``AssertionError`` with the field named in the message, so a
    failure points straight at the override that forgot the field.
    """
    bare_sql = expression_cls(dialect).to_sql()[0]

    probe_field = _PROBE_FOR_FIELD.get(field, field)
    probe = getattr(dialect, f"supports_identity_{probe_field}", None)
    assert probe is not None, (
        f"IdentityClause carries the option field {field!r} but the dialect "
        f"has no supports_identity_{probe_field}() probe to gate it; the "
        f"override cannot refuse what it cannot answer for."
    )
    declared = probe()
    parameter = inspect.signature(expression_cls.__init__).parameters[field]
    feature = f"IDENTITY {field.upper().replace('_', ' ')}"

    for value in _requested_values(field, parameter):
        clause = expression_cls(dialect, **{field: value})
        try:
            sql = clause.to_sql()[0]
        except UnsupportedFeatureError as exc:
            assert feature in str(exc), (
                f"{field}={value!r} was refused without naming the requested "
                f"spelling ({feature}): {exc}"
            )
            assert declared is False, (
                f"{field}={value!r} was refused although "
                f"supports_identity_{probe_field}() answers {declared!r}; a "
                f"declared option needs a renderer."
            )
            continue
        assert sql != bare_sql, (
            f"{field}={value!r} rendered the bare clause {sql!r}: the requested "
            f"option was silently dropped by the override. Render it or refuse "
            f"it by name."
        )
        assert declared is True, (
            f"{field}={value!r} rendered {sql!r} although "
            f"supports_identity_{probe_field}() answers {declared!r}; a non-True "
            f"answer must fail closed."
        )


def test_identity_option_enumeration_is_not_empty():
    """Guard: the general test below must have subjects, not vacuous success."""
    fields = _option_fields()
    assert fields, (
        "IdentityClause.__init__ exposes no option fields; the enumeration "
        "this file relies on no longer works (did core change the constructor "
        "shape?), so the per-option test would pass vacuously."
    )


@pytest.mark.parametrize("field", _option_fields())
def test_every_identity_option_is_rendered_or_refused_by_name(field):
    """Requested option -> rendered, or refused by name. Never dropped.

    The field is one of ``IdentityClause``'s own constructor parameters; the
    failure messages name it, so a future field points straight at the
    override that forgot it.
    """
    _check_option(BigQueryDialect(), IdentityClause, field)


def test_cache_zero_is_refused_at_construction():
    """The old ``cache=0`` sentinel is gone; the negative spelling has a name."""
    with pytest.raises(ValueError, match="cache must be a positive integer"):
        IdentityClause(BigQueryDialect(), cache=0)


class _FutureIdentityClause(IdentityClause):
    """A stand-in for the next option field core adds: ungated everywhere."""

    def __init__(self, dialect, generation=None, *, foo=None, **kwargs):
        super().__init__(dialect, generation, **kwargs)
        self.foo = foo


class _FutureDialect(BigQueryDialect):
    """The dialect side of a future field: the probe exists and answers ``False``."""

    def supports_identity_foo(self) -> bool:
        return False


def test_the_check_catches_a_future_ungated_field():
    """Sentinel: the check rejects a drop, so a future field cannot slip by.

    ``_FutureIdentityClause`` / ``_FutureDialect`` are what the next core
    option looks like from this dialect's side: a new field plus its
    fail-closed probe, with no gate added to the override. The enumeration
    sees the field and the render-or-refuse check rejects the bare clause the
    override produces. If this sentinel ever stops failing, the general test
    above has gone vacuous.
    """
    assert "foo" in _option_fields(_FutureIdentityClause), (
        "the enumerator did not see the added field"
    )
    with pytest.raises(AssertionError, match="silently dropped"):
        _check_option(_FutureDialect(), _FutureIdentityClause, "foo")


#: One hook-gated spelling -> the constructor kwargs that request it, the hook
#: that owns its spelling, and a spelling a hardcoded SQL-standard word cannot
#: accidentally match.
def _cycle_hook(self, value):
    return "HOOK-CYCLE" if value else "HOOK-NO-CYCLE"


def _order_hook(self, value):
    return "HOOK-ORDER" if value else "HOOK-NO-ORDER"


def _cache_hook(self, value):
    return f"HOOK-CACHE-{value}"


def _no_cache_hook(self):
    return "HOOK-NO-CACHE"


_HOOK_CASES = (
    ({"cycle": True}, "supports_identity_cycle", "identity_cycle_keyword", _cycle_hook, "HOOK-CYCLE"),
    ({"no_cycle": True}, "supports_identity_cycle", "identity_cycle_keyword", _cycle_hook, "HOOK-NO-CYCLE"),
    ({"order": True}, "supports_identity_order", "identity_order_keyword", _order_hook, "HOOK-ORDER"),
    ({"no_order": True}, "supports_identity_order", "identity_order_keyword", _order_hook, "HOOK-NO-ORDER"),
    ({"cache": 10}, "supports_identity_cache", "identity_cache_keyword", _cache_hook, "HOOK-CACHE-10"),
    ({"no_cache": True}, "supports_identity_cache", "identity_no_cache_keyword", _no_cache_hook, "HOOK-NO-CACHE"),
)


@pytest.mark.parametrize(
    "kwargs,probe_name,hook,impl,spelling",
    _HOOK_CASES,
    ids=("cycle", "no-cycle", "order", "no-order", "cache-10", "no-cache"),
)
def test_option_spelling_comes_from_the_hook(kwargs, probe_name, hook, impl, spelling):
    """The override delegates option spelling to core's ``identity_*_keyword`` hooks.

    BigQuery's probes decline all three options, so the override's spelling
    lines are unreachable through the public dialect. A subclass that declares
    the option and returns a spelling no hardcoded SQL-standard word can match
    proves the line calls the hook: reverting it to a hardcoded
    ``"CYCLE" if ... else "NO CYCLE"`` (or ``CACHE {n}``) fails here.
    """
    dialect = type(
        f"BigQueryWithHooked{next(iter(kwargs)).title()}",
        (BigQueryDialect,),
        {probe_name: lambda self: True, hook: impl},
    )()

    sql = IdentityClause(dialect, **kwargs).to_sql()[0]
    assert sql.endswith(f"({spelling})"), sql
