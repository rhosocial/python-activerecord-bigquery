# src/rhosocial/activerecord/backend/impl/bigquery/examples/introspection_datasets.py
"""Print a project's datasets, their tables and one table's columns, then
show the introspection cache at work.

Run it::

    python -m rhosocial.activerecord.backend.impl.bigquery.examples.introspection_datasets

Configuration comes from the environment -- the same variables the CLI
reads, mapping one-to-one onto ``BigQueryConnectionConfig``:

===============================  =========================================
Variable                         Config field
===============================  =========================================
``BIGQUERY_PROJECT``            ``project`` (falls back to the Google
                                client's own ``GOOGLE_CLOUD_PROJECT``)
``BIGQUERY_DATASET``            ``dataset`` (**required**: the questions are
                                dataset-scoped)
``BIGQUERY_LOCATION``           ``location``
``BIGQUERY_CREDENTIALS_PATH``   ``credentials_path`` (falls back to Google's
                                ``GOOGLE_APPLICATION_CREDENTIALS``)
``BIGQUERY_CREDENTIALS_JSON``   ``credentials_json``
``BIGQUERY_API_ENDPOINT``       ``api_endpoint`` (point it at the emulator)
===============================  =========================================

``BIGQUERY_DATASET`` plus one credentials source (a path or inline JSON)
plus a project -- or ``GOOGLE_APPLICATION_CREDENTIALS`` for the
credentials -- are what a run needs. With them missing the script prints
exactly those variables and exits 2; it never connects to nothing and
never fabricates a row.

What the cache demonstration shows: the introspector answers each question
once and keeps the answer, so the *cold* pass -- first time each question
is asked -- issues a query per question, and the *warm* pass -- the same
questions again -- issues none. The executor counts its questions; the
numbers below are that count.
"""

import os
import sys
from typing import Any, Dict, List, Tuple

REQUIRED_DATASET_ENV = "BIGQUERY_DATASET"

#: The variables a caller can set, in the order the script checks them.
#: Printed verbatim when one is missing -- a caller should not have to
#: guess which name to export.
ENV_VARS = (
    "BIGQUERY_PROJECT",
    "BIGQUERY_CREDENTIALS_PATH",
    "BIGQUERY_DATASET",
    "BIGQUERY_LOCATION",
    "BIGQUERY_CREDENTIALS_JSON",
    "BIGQUERY_API_ENDPOINT",
)

_ENV_HELP = """\
No dataset to introspect. Set the environment variables this example reads:

  BIGQUERY_PROJECT           the Google Cloud project, e.g. my-project
                             (falls back to GOOGLE_CLOUD_PROJECT)
  BIGQUERY_CREDENTIALS_PATH  a service-account JSON key file, e.g.
                             /home/me/key.json -- or GOOGLE_APPLICATION_CREDENTIALS
  BIGQUERY_DATASET           the dataset to introspect, e.g. my_dataset

Optional:

  BIGQUERY_LOCATION          dataset location, e.g. US or eu
  BIGQUERY_CREDENTIALS_JSON  the key file's contents as JSON
  BIGQUERY_API_ENDPOINT      a BigQuery endpoint override, e.g.
                             http://localhost:9050 for the emulator

Example:

  export BIGQUERY_PROJECT=my-project
  export BIGQUERY_DATASET=my_dataset
  export BIGQUERY_CREDENTIALS_PATH=$HOME/bigquery-key.json
  python -m rhosocial.activerecord.backend.impl.bigquery.examples.introspection_datasets
"""


def _env(name: str) -> Any:
    value = os.getenv(name)
    return value.strip() if value else None


def _resolve_credentials() -> Tuple[Any, Any]:
    """The credentials source the config fields carry, from the environment.

    Returns:
        ``(path, parsed_json)``: exactly one is not ``None`` when a source
        is configured, and neither is when there is none.
    """
    path = _env("BIGQUERY_CREDENTIALS_PATH") or _env("GOOGLE_APPLICATION_CREDENTIALS")
    raw_json = _env("BIGQUERY_CREDENTIALS_JSON")
    if raw_json:
        import json

        try:
            return None, json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"BIGQUERY_CREDENTIALS_JSON is not valid JSON: {exc}") from exc
    return path, None


class CountingExecutor:
    """The introspector's executor, counting the questions it is asked.

    A delegating wrapper rather than a subclass, because what this example
    demonstrates is a property of the *executor* boundary: the introspector
    asks once per question when nothing is cached, and never again
    afterwards. Counting at that boundary is the measurement.
    """

    def __init__(self, inner) -> None:
        self._inner = inner
        self.questions: List[Tuple[str, tuple]] = []

    def execute(self, sql: str, params: Tuple = ()) -> List[Dict[str, Any]]:
        """Run one question through the wrapped executor, counting it."""
        self.questions.append((sql, params))
        return self._inner.execute(sql, params)


def _print_rows(rows: List[Any], columns: List[str]) -> None:
    """Print dict rows as aligned text, with no third-party dependency."""
    if not rows:
        print("    (none)")
        return
    widths = [
        max(len(column), *(len(str(row.get(column, ""))) for row in rows)) for column in columns
    ]
    header = "  ".join(column.ljust(widths[i]) for i, column in enumerate(columns))
    print(f"    {header}")
    print(f"    {'  '.join('-' * width for width in widths)}")
    for row in rows:
        cells = [str(row.get(column, "")).ljust(widths[i]) for i, column in enumerate(columns)]
        print(f"    {'  '.join(cells)}")


def main() -> int:
    """Run the introspection walk; return the process exit code."""
    dataset = _env(REQUIRED_DATASET_ENV)
    project = _env("BIGQUERY_PROJECT") or _env("GOOGLE_CLOUD_PROJECT")
    credentials_path, credentials_json = _resolve_credentials()
    location = _env("BIGQUERY_LOCATION")
    api_endpoint = _env("BIGQUERY_API_ENDPOINT")

    if not dataset or (not project and not credentials_path and not credentials_json):
        # Exactly which variable to set, and nothing invented. Exits 2, the
        # conventional "misconfigured" status.
        print(_ENV_HELP, end="", file=sys.stderr)
        return 2

    from rhosocial.activerecord.backend.impl.bigquery.backend.backend import (
        BigQueryBackend,
    )
    from rhosocial.activerecord.backend.impl.bigquery.config import (
        BigQueryConnectionConfig,
    )
    from rhosocial.activerecord.backend.impl.bigquery.introspection import (
        SyncBigQueryIntrospector,
        SyncBigQueryIntrospectorExecutor,
    )

    backend = BigQueryBackend(
        connection_config=BigQueryConnectionConfig(
            project=project,
            dataset=dataset,
            location=location,
            credentials_path=credentials_path,
            credentials_json=credentials_json,
            api_endpoint=api_endpoint,
        )
    )

    # The introspector with the counting executor, set on the backend so
    # every question this run asks is measured.
    counting = CountingExecutor(SyncBigQueryIntrospectorExecutor(backend))
    backend.set_introspector(SyncBigQueryIntrospector(backend, counting))
    executor = counting

    print(
        "BigQuery introspection for project "
        f"{project or '(from credentials)'}, dataset {dataset}"
    )
    print("SQL for each question comes from the BigQuery dialect's format_* " "entries;")
    print("the executor counts the questions asked.\n")

    backend.connect()
    try:
        # -- Cold pass: each question is asked once ---------------------- #
        print("== Cold pass: every question issues one query ==")
        datasets = backend.introspector.list_datasets()
        _print_rows(
            [
                {
                    "dataset": d.schema_name,
                    "project": d.catalog_name,
                    "location": d.location,
                }
                for d in datasets
            ],
            ["dataset", "project", "location"],
        )

        tables = backend.introspector.list_tables(dataset)
        _print_rows(
            [{"table": t.name, "type": t.table_type.value} for t in tables],
            ["table", "type"],
        )

        columns = backend.introspector.list_columns(tables[0].name, dataset) if tables else []
        _print_rows(
            [
                {
                    "column": c.name,
                    "type": c.data_type,
                    "nullable": c.nullable.value,
                    "position": c.ordinal_position,
                }
                for c in columns
            ],
            ["column", "type", "nullable", "position"],
        )
        cold = len(executor.questions)
        print(f"\ncold pass: {cold} question(s) asked")

        # -- Warm pass: the same questions, all cached ------------------- #
        print("\n== Warm pass: the same questions, answered from the cache ==")
        backend.introspector.list_datasets()
        backend.introspector.list_tables(dataset)
        if tables:
            backend.introspector.list_columns(tables[0].name, dataset)
            storage = backend.introspector.get_table_storage_info(tables[0].name, dataset)
            print(
                f"storage of {storage.table_name}: "
                f"{len(storage.partitions)} partition row(s), "
                f"partitioning={storage.partitioning_columns}, "
                f"clustering={storage.clustering_columns}"
            )
        warm = len(executor.questions) - cold
        print(f"warm pass: {warm} question(s) asked (the answers were cached)")
    finally:
        if getattr(backend, "_client", None):
            backend.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
