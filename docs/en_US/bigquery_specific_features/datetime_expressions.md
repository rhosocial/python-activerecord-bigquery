# docs/en_US/bigquery_specific_features/datetime_expressions.md

# BigQuery Temporal Expressions: `seconds_between`

> This page covers the backend-specific half of the core
> `seconds_between(start, end)` node: how BigQuery spells the elapsed time, why
> the arguments are in the opposite order to the generic call, what precision
> the answer keeps, and which operand types the spelling accepts.
>
> The core node, its `TimestampColumn.seconds_between(...)` surface, and the
> `format_seconds_between_expression` contract every backend implements are
> documented in the core library
> ([`docs/en_US/backend/expression/functions.md`][core-functions]).

[core-functions]: https://github.com/rhosocial/python-activerecord/tree/main/docs/en_US/backend/expression/functions.md

## What the node asks for

`seconds_between(start, end)` is `end - start` counted in seconds:

- **signed** — an end earlier than the start is negative, equal instants are
  exactly zero;
- **fractional** — a span with a sub-second part keeps it;
- **end-first** — the direction is part of the value, not an afterthought.

The core layer refuses to render this on its own because engines disagree about
how a duration is written. BigQuery's answer is a difference in a named unit.

## The spelling

```python
from rhosocial.activerecord.backend.expression import TimestampColumn, seconds_between
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect

dialect = BigQueryDialect()
started = TimestampColumn(dialect, "started_at")
ended = TimestampColumn(dialect, "ended_at")

sql, params = seconds_between(dialect, started, ended).to_sql()
# sql == "TIMESTAMP_DIFF(`ended_at`, `started_at`, MILLISECOND) / 1000.0"
# params == ()
```

The pieces:

| Piece | Why |
|---|---|
| `TIMESTAMP_DIFF(end, start, MILLISECOND)` | BigQuery counts a span in a named unit and keeps the direction in the result's sign. |
| `MILLISECOND` | The finest unit this formatter uses; it is what keeps a fraction rather than a whole-second count. |
| `/ 1000.0` | Turns the millisecond count into seconds. The decimal denominator keeps the division in floating point. |
| `ended_at` written first | `TIMESTAMP_DIFF` takes the **end** instant first; a generic `start, end` pair has to be swapped or the sign is wrong. |

The same expression with bind parameters puts the end's parameter first, because
the formatter collects parameters in the order the SQL writes them:

```python
seconds_between(dialect, Literal(dialect, start_dt), Literal(dialect, end_dt)).to_sql()
# ("TIMESTAMP_DIFF(?, ?, MILLISECOND) / 1000.0", (end_value, start_value))
```

An alias lands after the whole scalar, not inside the function:

```python
seconds_between(dialect, started, ended).as_("elapsed").to_sql()[0]
# "TIMESTAMP_DIFF(`ended_at`, `started_at`, MILLISECOND) / 1000.0 AS `elapsed`"
```

## Precision: one millisecond

`TIMESTAMP_DIFF` returns a whole number of its named unit. Counting in
milliseconds therefore keeps three decimal places of a second and drops anything
smaller: a span of 500 microseconds has no complete millisecond to count and
becomes `0.0` seconds from this node. GoogleSQL also supports `MICROSECOND`, but
the framework contract for this node is the millisecond spelling; a caller that
needs the exact microsecond must ask the server for it directly.

The limit is **documented, not hidden**: the node itself does not round a value
it cannot represent, and no implicit `ROUND` is added to the SQL. The result is
the count the server gives, divided by `1000.0`.

The sign is exact: `TIMESTAMP_DIFF` counts toward the end and returns a negative
count when the end is earlier, and the division carries that sign through.

## Operands must be `TIMESTAMP`

`TIMESTAMP_DIFF` takes `TIMESTAMP` arguments. BigQuery also has a zoneless
`DATETIME` type and a separate `DATETIME_DIFF` for it; this node expresses an
elapsed span between two instants, so it writes the instant form. Passing a
`DATETIME`-typed operand without a cast is a type error the server reports — it
is not silently reinterpreted in the session's time zone.

This is the deliberate difference from `date_diff`, which renders
`DATE_DIFF(end, start, part)`: `DATE_DIFF` works on dates and answers in whole
calendar or fixed units, while `seconds_between` is the fractional instant
span.

## How this page was verified

The SQL fragments were rendered locally with `BigQueryDialect()` and the core
`feature/extract-epoch` build; no server was involved:

```
PYTHONPATH=<core-worktree>/src:src .venv3.14/Scripts/python -m pytest \
  tests/rhosocial/activerecord_bigquery_test/feature/backend/expression/test_seconds_between.py
```

The live cases live in
`tests/rhosocial/activerecord_bigquery_test/feature/backend/test_seconds_between_live.py`.
They run only when a scenario is configured and an endpoint answers; the
`goccy/bigquery-emulator` used by CI is the only endpoint this repository can
reach. When the endpoint cannot evaluate `TIMESTAMP_DIFF` — the emulator
implements a subset of GoogleSQL — the case skips with the server's own reason
rather than reporting a formatter failure. At the time this page was written no
emulator was running, so the live cases reported **skipped: no reachable
BigQuery endpoint**; the rendering and bind-order cases above are the verified
half.
