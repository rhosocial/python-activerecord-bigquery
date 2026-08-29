# tests/providers/_reset.py
"""Shared helpers for BigQuery test-provider table resets.

BigQuery Standard SQL requires a WHERE clause on every DELETE, so the bare
``DELETE FROM t`` used by other backends' providers is a syntax error here
(the goccy/bigquery-emulator rejects it with "DELETE must have a WHERE
clause"). These helpers emit a ``TRUNCATE TABLE`` (preferred) or a portable
``DELETE ... WHERE TRUE`` fallback, selected through the dialect's
``TruncateSupport`` capability, so each test starts from a clean table.

The goccy/bigquery-emulator also degrades as DDL metadata accumulates in its
backing sqlite store: DROP+CREATE-per-test drives per-statement latency from
~0.3s to several seconds. The testsuite fixtures are function-scoped, so each
test would otherwise CREATE + clear + DROP the same tables. To avoid that we
(a) create each table at most once per pytest process (tracked below) and
(b) never DROP in per-test cleanup, relying on the clear step instead.
"""

from typing import Any, Callable, Dict, Iterator, Tuple

# (dataset, table_name) -> DDL text of the table as it exists in the emulator
# during this pytest process. Keyed by DDL so a schema change forces a
# recreate rather than silently reusing a stale layout.
_SESSION_TABLES: Dict[Tuple[str, str], str] = {}


def ensure_table_created(exec_ddl: Callable[[str], None], dataset, table_name: str, ddl: str) -> str:
    """Idempotently create ``table`` once per pytest process (sync).

    ``exec_ddl(sql)`` runs a single DDL statement synchronously. Returns the
    dataset-qualified table reference.

    The first call for a ``(dataset, table)`` pair issues ``CREATE TABLE IF
    NOT EXISTS``; later calls with the *same* DDL are skipped so the emulator
    does not accumulate per-test DDL metadata. If the same table name is later
    requested with a *different* DDL (e.g. the query fixtures' single-PK vs
    composite-PK ``order_items``), the table is dropped and recreated with the
    new layout. A degraded emulator may surface "duplicate: table already
    created" even for ``IF NOT EXISTS``, which is treated as "table exists,
    proceed".
    """
    key = (dataset, table_name)
    qualified = f"`{dataset}`.`{table_name}`" if dataset else f"`{table_name}`"
    existing = _SESSION_TABLES.get(key)
    if existing == ddl:
        return qualified
    if existing is None:
        safe_ddl = ddl.replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS", 1)
        try:
            exec_ddl(safe_ddl)
        except Exception:
            pass
    else:
        # Same table name but a different schema than we last created: force
        # a clean recreate so the model sees the columns it expects.
        try:
            exec_ddl(f"DROP TABLE IF EXISTS {qualified}")
        except Exception:
            pass
        exec_ddl(ddl)
    _SESSION_TABLES[key] = ddl
    return qualified


async def ensure_table_created_async(aexec_ddl: Callable[[str], Any], dataset, table_name: str, ddl: str) -> str:
    """Async mirror of :func:`ensure_table_created`.

    ``aexec_ddl(sql)`` runs a single DDL statement asynchronously (an
    awaitable).
    """
    key = (dataset, table_name)
    qualified = f"`{dataset}`.`{table_name}`" if dataset else f"`{table_name}`"
    existing = _SESSION_TABLES.get(key)
    if existing == ddl:
        return qualified
    if existing is None:
        safe_ddl = ddl.replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS", 1)
        try:
            await aexec_ddl(safe_ddl)
        except Exception:
            pass
    else:
        try:
            await aexec_ddl(f"DROP TABLE IF EXISTS {qualified}")
        except Exception:
            pass
        await aexec_ddl(ddl)
    _SESSION_TABLES[key] = ddl
    return qualified


def clear_table_candidates(dialect, qualified: str) -> Iterator[str]:
    """Yield ordered SQL statements to empty ``qualified`` without dropping it.

    The caller executes them in order (via its own ``_execute_ddl`` /
    ``backend.execute``) and stops at the first that succeeds; the remaining
    candidates and the DROP+CREATE last resort are only reached if an earlier
    one raised.
    """
    if dialect.supports_truncate():
        yield f"TRUNCATE TABLE {qualified}"
    yield f"DELETE FROM {qualified} WHERE TRUE"
