# tests/rhosocial/activerecord_bigquery_test/feature/query/test_operation_boundaries.py
"""The four string boundaries the 2026-10-09 ruling settled, plus the NULL-safe
comparison it added to the surface.

``operation-groups-matrix.md`` section F records the measurement: what the ten
backends answer for a negative count, an empty pad, a position below 1 and a
multi-character trim set, and which answer -- if any -- is common ground. This
file pins the outcome. Edges every backend agrees on render; the rest are
refused at construction instead of rendered into whatever the dialect happens
to do. ``is_distinct_from`` is here too: its spelling varies by backend, so it
is a dialect hook with a gate, and the gate refuses rather than substitutes a
different question. So are the function version floors SQLite records: they
used to be answerable through ``supports_functions()`` and ignorable at render
time, and now rendering a call the dialect's version predates refuses.
"""

import pytest

from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError
from rhosocial.activerecord.backend.expression.column_types import NumericColumn, StringColumn
from rhosocial.activerecord.backend.expression.core import FunctionCall, Literal
from rhosocial.activerecord.backend.impl.dummy.dialect import DummyDialect
from rhosocial.activerecord.backend.impl.sqlite.dialect import SQLiteDialect


@pytest.fixture
def sqlite_dialect():
    dialect = SQLiteDialect()
    dialect.version = (3, 46, 1)
    return dialect


@pytest.fixture
def name(sqlite_dialect):
    return StringColumn(sqlite_dialect, "name")


@pytest.fixture
def portable_name():
    """A column on the portable baseline, where the common spellings render."""
    return StringColumn(DummyDialect(), "name")


REFUSALS = [
    ("left", (-1,)),
    ("right", (-1,)),
    ("lpad", (-1,)),
    ("lpad", (5, "")),
    ("rpad", (-1,)),
    ("rpad", (5, "")),
    ("substr", (0,)),
    ("substr", (-2, 3)),
    ("substr", (1, -1)),
    ("trim", ("xy",)),
    ("trim", ("",)),
]


@pytest.mark.parametrize(
    "method,args",
    [("left", (-1,)), ("right", (-1,)), ("lpad", (-1,)), ("lpad", (5, "")),
     ("rpad", (-1,)), ("rpad", (5, "")), ("substr", (0,)), ("substr", (-2, 3)),
     ("substr", (1, -1)), ("trim", ("xy",)), ("trim", ("",))],
    ids=("left", "right", "lpad_negative", "lpad_empty_pad",
         "rpad_negative", "rpad_empty_pad", "substr_start0", "substr_negative_start",
         "substr_negative_length", "trim_two_chars", "trim_empty_set"),
)
def test_the_edge_where_the_backends_disagree_is_refused(name, method, args):
    """No two backends answer these the same way, so the answer is a refusal
    at construction rather than a silent coin flip at render time."""
    with pytest.raises(ValueError):
        getattr(name, method)(*args)


@pytest.mark.parametrize(
    "method,args,expected_sql,expected_params",
    [
        ("left", (0,), 'LEFT("name", ?)', (0,)),
        ("repeat", (0,), 'REPEAT("name", ?)', (0,)),
        ("substr", (1, 0), 'SUBSTRING("name", ?, ?)', (1, 0)),
    ],
)
def test_the_edge_every_backend_agrees_on_renders(portable_name, method, args, expected_sql, expected_params):
    """The inside of the contract: zero-length results, the empty substring,
    the whole-string over-length read and a one-character trim set behave the
    same on every backend, so they render. Asserted on the portable baseline
    because what is under test is the core spelling, not a dialect's."""
    sql, params = getattr(portable_name, method)(*args).to_sql()
    assert sql == expected_sql
    assert params == expected_params


@pytest.mark.parametrize(
    "direction,expected_sql,expected_params",
    [
        ("BOTH", 'TRIM("name", ?)', ("x",)),
        ("LEADING", 'LTRIM("name", ?)', ("x",)),
        ("TRAILING", 'RTRIM("name", ?)', ("x",)),
    ],
)
def test_sqlite_spells_trim_as_its_function_form(direction, expected_sql, expected_params):
    """SQLite parses no ``trim(<chars> from <string>)`` syntax, so the node
    renders as the function form there. Same node, dialect-chosen spelling --
    which is why the factory builds a TrimExpression and not a SQL string."""
    dialect = SQLiteDialect()
    dialect.version = (3, 46, 1)
    column = StringColumn(dialect, "name")
    sql, params = column.trim("x", direction).to_sql()
    assert sql == expected_sql
    assert params == expected_params


def test_the_default_spelling_is_the_standard_form():
    """A dialect that speaks the standard form renders it, unchanged from what
    the raw SQL used to produce."""
    column = StringColumn(DummyDialect(), "name")
    assert column.trim().to_sql() == ('TRIM(BOTH FROM "name")', ())
    assert column.trim("x").to_sql() == ('TRIM(BOTH ? FROM "name")', ("x",))


def test_lpad_defaults_to_a_space_and_passes_it_explicitly(portable_name):
    """MySQL raises 1582 without a pad and MariaDB supplies one, so the core
    always spells it out instead of letting the backend choose."""
    sql, params = portable_name.lpad(3).to_sql()
    assert sql == 'LPAD("name", ?, ?)'
    assert params == (3, " ")


def test_a_negative_repeat_is_the_empty_string(name):
    """PostgreSQL, MySQL, MariaDB and ClickHouse all answer ``''`` for a
    negative count; SQL Server answers NULL and Oracle, Firebird and SQLite
    lack the function, so the core answers once instead of four times."""
    expr = name.repeat(-1)
    assert "REPEAT" not in expr.to_sql()[0]
    assert expr.to_sql() == ("?", ("",))


def test_is_distinct_from_renders_the_null_safe_comparison():
    """The default rendering is the standard spelling; backends that spell it
    differently override the hook instead of every call site writing dialect
    SQL."""
    column = StringColumn(DummyDialect(), "age")
    assert column.is_distinct_from(0).to_sql() == ('"age" IS DISTINCT FROM ?', (0,))
    assert column.is_not_distinct_from(0).to_sql() == ('"age" IS NOT DISTINCT FROM ?', (0,))


@pytest.mark.parametrize("version,expected", [((3, 39, 0), True), ((3, 38, 0), False)])
def test_sqlite_gates_the_spelling_on_its_version(version, expected):
    dialect = SQLiteDialect()
    dialect.version = version
    assert dialect.supports_distinct_from() is expected


def test_sqlite_below_the_gate_refuses_rather_than_substituting():
    dialect = SQLiteDialect()
    dialect.version = (3, 38, 0)
    column = StringColumn(dialect, "age")
    with pytest.raises(UnsupportedFeatureError):
        column.is_distinct_from(0).to_sql()


# ---------------------------------------------------------------------------
# A recorded function version floor is a gate, not a footnote
# ---------------------------------------------------------------------------


SQLITE_FUNCTION_FLOORS = [
    ("iif", (3, 32, 0)),
    ("pow", (3, 35, 0)),
    # json_extract is deliberately absent: the JSON1 functions predate their
    # 3.38.0 promotion into core (they exist since 3.9.0 behind a compile-time
    # option), so availability depends on how SQLite was built, not on the
    # version -- CI's own 3.35.0 server executes json_extract. A recorded floor
    # there would refuse SQL the server accepts.
    ("unhex", (3, 45, 0)),
    ("json_array_insert", (3, 53, 0)),
    ("jsonb_array_insert", (3, 53, 0)),
]


def _gated_call(dialect, func_name):
    """One call to *func_name*, as the renderer meets it: the name the caller
    handed over, spelled upper-case in the SQL."""
    return FunctionCall(dialect, func_name, Literal(dialect, "x"))


def _one_patch_below(floor):
    """The release before *floor*: same major and minor, one patch short."""
    return (floor[0], floor[1], floor[2] - 1)


@pytest.mark.parametrize(
    "func_name,floor",
    SQLITE_FUNCTION_FLOORS,
    ids=[func_name for func_name, _floor in SQLITE_FUNCTION_FLOORS],
)
def test_a_floor_the_dialect_is_below_refuses_instead_of_rendering(func_name, floor):
    """SQLite records when each function arrived. Rendering one anyway emits
    SQL this SQLite will reject, so the floor is a refusal at render time
    rather than an observation in a table nobody reads."""
    dialect = SQLiteDialect()
    dialect.version = _one_patch_below(floor)
    with pytest.raises(UnsupportedFeatureError):
        _gated_call(dialect, func_name).to_sql()


@pytest.mark.parametrize(
    "func_name,floor",
    SQLITE_FUNCTION_FLOORS,
    ids=[func_name for func_name, _floor in SQLITE_FUNCTION_FLOORS],
)
def test_a_floor_the_dialect_meets_renders(func_name, floor):
    """The gate is a floor, not a ban: at the recorded version the same call
    renders exactly as it does on a newer one -- the version changes what is
    refused, never what is spelled."""
    dialect = SQLiteDialect()
    dialect.version = floor
    assert _gated_call(dialect, func_name).to_sql() == (f"{func_name.upper()}(?)", ("x",))


def test_the_refusal_names_the_function_the_floor_and_the_version():
    """A refusal the caller cannot act on is only a different way of failing,
    so the message says which function, which version it arrived in and which
    one is in force: the choice is between a newer server and another
    spelling."""
    dialect = SQLiteDialect()
    dialect.version = (3, 52, 0)
    call = FunctionCall(
        dialect,
        "json_array_insert",
        Literal(dialect, "[]"),
        Literal(dialect, "$[0]"),
        Literal(dialect, 1),
    )
    with pytest.raises(UnsupportedFeatureError) as excinfo:
        call.to_sql()
    message = str(excinfo.value)
    assert "JSON_ARRAY_INSERT" in message
    assert "3.53.0" in message
    assert "3.52.0" in message


def test_the_query_surface_and_the_gate_answer_the_same_thing():
    """``supports_functions`` keeps its shape and stays the query surface; what
    changed is that a False in it is no longer advisory. Below the floor both
    answer no, at it both answer yes."""
    for version, expected in ((3, 52, 0), False), ((3, 53, 0), True):
        dialect = SQLiteDialect()
        dialect.version = version
        assert dialect.supports_functions()["json_array_insert"] is expected
        call = _gated_call(dialect, "json_array_insert")
        if expected:
            assert call.to_sql() == ("JSON_ARRAY_INSERT(?)", ("x",))
        else:
            with pytest.raises(UnsupportedFeatureError):
                call.to_sql()


def test_a_name_no_floor_is_recorded_for_renders_on_the_oldest_dialect():
    """No floor is not a floor of zero. A name nobody has measured is not
    gated here, so it renders on a dialect that predates every gate in the
    table -- the gate only ever refuses what a backend declared."""
    dialect = SQLiteDialect()
    dialect.version = (3, 8, 0)
    assert dialect.function_version_floor("lower") is None
    column = StringColumn(dialect, "name")
    assert column.lower().to_sql() == ('LOWER("name")', ())
    assert dialect.function_version_floor("pow") == (3, 35, 0)


# ---------------------------------------------------------------------------
# The per-dialect spellings, and the emulations behind them
# ---------------------------------------------------------------------------


SQLITE_SPELLINGS = [
    ("left", (2,), 'SUBSTR("name", ?, ?)', (1, 2)),
    ("right", (2,), 'SUBSTR("name", MAX(LENGTH("name") - ? + ?, ?), ?)', (2, 1, 1, 2)),
    (
        "lpad",
        (4, "xy"),
        'CASE WHEN ? <= LENGTH("name") THEN SUBSTR("name", ?, ?) '
        'ELSE SUBSTR(REPLACE(HEX(ZEROBLOB(?)), ?, ?) || "name", - ?) END',
        (4, 1, 4, 4, "00", "xy", 4),
    ),
    (
        "rpad",
        (4, "-"),
        'SUBSTR("name" || REPLACE(HEX(ZEROBLOB(?)), ?, ?), ?, ?)',
        (4, "00", "-", 1, 4),
    ),
    ("repeat", (3,), 'REPLACE(HEX(ZEROBLOB(?)), ?, "name")', (3, "00")),
    ("ascii", (), 'UNICODE("name")', ()),
    ("strpos", ("cd",), 'INSTR("name", ?)', ("cd",)),
    ("position", ("cd",), 'INSTR("name", ?)', ("cd",)),
]


@pytest.mark.parametrize("method,args,expected_sql,expected_params", SQLITE_SPELLINGS)
def test_sqlite_spells_what_it_lacks(sqlite_dialect, method, args, expected_sql, expected_params):
    """SQLite has none of these functions and no ``trim(... from ...)`` syntax,
    so each is either renamed, reordered, or emulated out of ordinary nodes --
    measured 2026-10-09 and verified against a real database below. Nothing
    here is assembled as a SQL string."""
    column = StringColumn(sqlite_dialect, "name")
    sql, params = getattr(column, method)(*args).to_sql()
    assert sql == expected_sql
    assert params == expected_params


def test_sqlite_truncates_with_arithmetic_because_trunc_takes_one_argument(sqlite_dialect):
    """SQLite's ``TRUNC`` is unary, so a precision is carried by scaling,
    truncating toward zero, and scaling back -- exact for negatives, which
    rounding would not be."""
    column = NumericColumn(sqlite_dialect, "n")
    sql, params = column.truncate(2).to_sql()
    assert sql == 'TRUNC("n" * POW(?, ?)) / POW(?, ?)'
    assert params == (10, 2, 10, 2)
    assert column.truncate().to_sql() == ('TRUNC("n")', ())


def test_sqlite_takes_the_log_base_first(sqlite_dialect):
    """SQLite spells ``log(base, x)`` where the core order is ``log(x, base)``;
    the one-argument form is the natural logarithm on both."""
    column = NumericColumn(sqlite_dialect, "n")
    assert column.log(10).to_sql() == ("LOG(?, \"n\")", (10,))
    assert column.log().to_sql() == ('LOG("n")', ())


STRING_ROUNDTRIPS = [
    ("left(2)", lambda c: c.left(2), "abcdef", "ab"),
    ("left(0)", lambda c: c.left(0), "abcdef", ""),
    ("left(99)", lambda c: c.left(99), "abcdef", "abcdef"),
    ("right(2)", lambda c: c.right(2), "abcdef", "ef"),
    ("right(0)", lambda c: c.right(0), "abcdef", ""),
    ("right(99)", lambda c: c.right(99), "abcdef", "abcdef"),
    ("lpad(8, 'xy')", lambda c: c.lpad(8, "xy"), "abcdef", "xyabcdef"),
    ("lpad(3, 'xy')", lambda c: c.lpad(3, "xy"), "abcdef", "abc"),
    ("lpad(4)", lambda c: c.lpad(4), "ab", "  ab"),
    ("rpad(8, '-')", lambda c: c.rpad(8, "-"), "abcdef", "abcdef--"),
    ("rpad(3, '-')", lambda c: c.rpad(3, "-"), "abcdef", "abc"),
    ("repeat(3)", lambda c: c.repeat(3), "ab", "ababab"),
    ("repeat(0)", lambda c: c.repeat(0), "ab", ""),
    ("trim('f')", lambda c: c.trim("f"), "abcdef", "abcde"),
    ("trim()", lambda c: c.trim(), "  abc  ", "abc"),
]

NUMERIC_ROUNDTRIPS = [
    ("truncate(2)", lambda c: c.truncate(2), 3.14159, 3.14),
    ("truncate(2) negative", lambda c: c.truncate(2), -3.14159, -3.14),
    ("truncate(0)", lambda c: c.truncate(0), 3.7, 3.0),
    ("truncate()", lambda c: c.truncate(), -3.7, -3.0),
]


@pytest.mark.parametrize(
    "label,build,value,expected",
    STRING_ROUNDTRIPS,
    ids=[label for label, _build, _value, _expected in STRING_ROUNDTRIPS],
)
def test_the_sqlite_emulation_answers_what_the_function_answers(sqlite_dialect, label, build, value, expected):
    """The spelling checks above prove the SQL is *shaped* right; this proves it
    *means* right -- each expression is executed against a real SQLite and must
    produce the answer PostgreSQL, MySQL and ClickHouse give for the same call.
    A spelling that looks correct and answers something else is the failure this
    test exists for."""
    import sqlite3

    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE t (s TEXT)")
    connection.execute("INSERT INTO t VALUES (?)", (value,))
    column = StringColumn(sqlite_dialect, "s")
    sql, params = build(column).to_sql()
    got = connection.execute(f"SELECT {sql} FROM t", tuple(params)).fetchone()[0]
    assert got == expected, f"{label}: SQLite answered {got!r}, the function answers {expected!r}"


@pytest.mark.parametrize("label,build,value,expected", NUMERIC_ROUNDTRIPS)
def test_the_sqlite_numeric_emulation_answers_what_the_function_answers(
    sqlite_dialect, label, build, value, expected
):
    import sqlite3

    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE t (n REAL)")
    connection.execute("INSERT INTO t VALUES (?)", (value,))
    column = NumericColumn(sqlite_dialect, "n")
    sql, params = build(column).to_sql()
    got = connection.execute(f"SELECT {sql} FROM t", tuple(params)).fetchone()[0]
    assert got == expected, f"{label}: SQLite answered {got!r}, the function answers {expected!r}"
