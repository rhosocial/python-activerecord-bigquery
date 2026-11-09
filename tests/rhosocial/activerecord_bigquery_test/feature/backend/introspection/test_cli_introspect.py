# tests/rhosocial/activerecord_bigquery_test/feature/backend/introspection/test_cli_introspect.py
"""CLI dispatch with a mocked backend: every subcommand, every format.

No connection. ``_build_backend`` -- the one place the CLI constructs a
real backend -- is replaced with a stand-in whose introspector answers
canned objects, so what these tests measure is the CLI's own work: parsing
the subcommand and its options, wiring them onto the introspector call,
serializing the result into each output format, and exiting non-zero on the
two ways a run can fail (a missing positional name, a table that does not
exist).

The dataset flag reaches the introspector as the ``schema`` argument --
BigQuery's dataset *is* the schema level, which is what the CLI says in its
help and what the dispatch must carry.
"""

import json

import pytest
from rhosocial.activerecord.backend.introspection.types import (
    ColumnNullable,
    IndexColumnInfo,
    IndexInfo,
    IndexType,
    IntrospectionColumnInfo,
    IntrospectionDatabaseInfo,
    IntrospectionTableInfo,
    IntrospectionViewInfo,
    TableType,
)

from rhosocial.activerecord.backend.impl.bigquery import cli as cli_package
from rhosocial.activerecord.backend.impl.bigquery.__main__ import main
from rhosocial.activerecord.backend.impl.bigquery.cli import introspect as cli_introspect
from rhosocial.activerecord.backend.impl.bigquery.introspection.types import (
    BigQueryPartitionInfo,
    BigQueryRoutineInfo,
)


class _FakeIntrospector:
    """Answers canned introspection results."""

    def __init__(self):
        self.calls = []

    def list_tables(self, schema=None, include_system=False):
        self.calls.append(("list_tables", schema, include_system))
        return self._tables_payload(schema)

    def _tables_payload(self, schema):
        """The two canned tables, so a subclass records the call itself."""
        return [
            IntrospectionTableInfo(
                name="orders",
                schema=schema,
                table_type=TableType.BASE_TABLE,
            ),
            IntrospectionTableInfo(
                name="recent_orders",
                schema=schema,
                table_type=TableType.VIEW,
            ),
        ]

    def list_views(self, schema=None):
        self.calls.append(("list_views", schema))
        return [
            IntrospectionViewInfo(
                name="recent_orders",
                schema=schema,
                definition="SELECT * FROM orders",
                check_option=None,
                extra={"use_standard_sql": True},
            )
        ]

    def get_table_info(self, table_name, schema=None):
        self.calls.append(("get_table_info", table_name, schema))
        if table_name != "orders":
            return None
        return IntrospectionTableInfo(
            name="orders",
            schema=schema,
            table_type=TableType.BASE_TABLE,
            columns=[
                IntrospectionColumnInfo(
                    name="id",
                    table_name="orders",
                    schema=schema,
                    ordinal_position=1,
                    data_type="INT64",
                    nullable=ColumnNullable.NOT_NULL,
                )
            ],
            indexes=[
                IndexInfo(
                    name="pk_orders",
                    table_name="orders",
                    schema=schema,
                    is_unique=True,
                    is_primary=True,
                    index_type=IndexType.UNKNOWN,
                    columns=[IndexColumnInfo(name="id", ordinal_position=1)],
                    extra={"constraint_type": "PRIMARY KEY"},
                )
            ],
        )

    def list_columns(self, table_name, schema=None):
        self.calls.append(("list_columns", table_name, schema))
        return [
            IntrospectionColumnInfo(
                name="id",
                table_name=table_name,
                schema=schema,
                ordinal_position=1,
                data_type="INT64",
                nullable=ColumnNullable.NOT_NULL,
                extra={"is_partitioning_column": False},
            )
        ]

    def list_datasets(self):
        self.calls.append(("list_datasets",))
        return [
            {
                "schema_name": "my_dataset",
                "catalog_name": "my-project",
                "location": "US",
            }
        ]

    def list_routines(self, schema=None):
        self.calls.append(("list_routines", schema))
        return [
            BigQueryRoutineInfo(
                routine_name="add_one",
                routine_type="FUNCTION",
                routine_schema=schema,
                data_type="INT64",
                is_deterministic=True,
            )
        ]

    def get_routine_info(self, routine_name, schema=None):
        self.calls.append(("get_routine_info", routine_name, schema))
        if routine_name != "add_one":
            return None
        return BigQueryRoutineInfo(
            routine_name="add_one",
            routine_type="FUNCTION",
            routine_schema=schema,
            data_type="INT64",
            is_deterministic=True,
        )

    def get_database_info(self):
        self.calls.append(("get_database_info",))
        return IntrospectionDatabaseInfo(
            name="my-project",
            version="3.0.0",
            version_tuple=(3, 0, 0),
            vendor="BigQuery",
            extra={
                "project": "my-project",
                "dataset": None,
                "location": None,
                "version_source": "backend feature level, not a server version",
            },
        )

    def list_partitions(self, table_name, schema=None):
        self.calls.append(("list_partitions", table_name, schema))
        return [
            BigQueryPartitionInfo(
                table_name=table_name,
                partition_id="20260101",
                table_catalog="my-project",
                table_schema=schema,
                total_rows=120,
                total_logical_bytes=2048,
                total_billable_bytes=4096,
                storage_tier="ACTIVE",
            )
        ]


class _FakeBackend:
    """A backend whose introspector is canned and whose client is a sentinel."""

    def __init__(self, connection_config=None):
        self.introspector = _FakeIntrospector()
        self._client = object()
        self.connected = False
        self.disconnected = False

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.disconnected = True


@pytest.fixture
def built(monkeypatch):
    """Patch the CLI's one construction site to the fake backend."""
    constructed = []

    def _fake_build_backend(args):
        backend = _FakeBackend()
        constructed.append(backend)
        return backend

    monkeypatch.setattr(cli_introspect, "_build_backend", _fake_build_backend)
    return constructed


def _run(argv):
    """Run the CLI entry point with *argv*, as a subprocess would."""
    import sys

    old_argv = sys.argv
    sys.argv = ["rhosocial-activerecord-bigquery"] + argv
    try:
        main()
    finally:
        sys.argv = old_argv


# ---------------------------------------------------------------------------
# Registration and dispatch
# ---------------------------------------------------------------------------


def test_every_subcommand_is_registered():
    from rhosocial.activerecord.backend.impl.bigquery.cli import COMMAND_NAMES

    assert set(COMMAND_NAMES) == {
        "tables",
        "views",
        "routines",
        "columns",
        "datasets",
        "database",
        "partitions",
        "unused-indexes",
        "table-stats",
        "runtime",
        "index-stats",
        "dependencies",
        "column-profiles",
        "value-samples",
        "join-coverage",
    }


def test_get_handler_routes_each_introspection_command():
    for name in cli_package.COMMAND_NAMES:
        assert cli_package.get_handler(name) is cli_introspect.handle


def test_get_handler_refuses_an_unknown_command():
    with pytest.raises(SystemExit) as exc_info:
        cli_package.get_handler("nope")
    assert exc_info.value.code == 1


def test_no_command_exits_non_zero():
    import sys

    old_argv = sys.argv
    sys.argv = ["rhosocial-activerecord-bigquery"]
    try:
        with pytest.raises(SystemExit) as exc_info:
            main()
    finally:
        sys.argv = old_argv
    assert exc_info.value.code == 1


def test_an_unknown_command_exits_non_zero():
    with pytest.raises(SystemExit) as exc_info:
        _run(["nope"])
    # argparse refuses an unregistered subcommand before the handler runs.
    assert exc_info.value.code == 2


def test_ddl_is_not_an_advertised_command():
    """``ddl`` is not offered: its capability is permanently false here.

    ``supports_ddl_extraction()`` answers ``False`` and no extraction
    statement exists, so argparse rejects the name as an invalid choice
    (exit 2) rather than the CLI advertising it and refusing it later.
    """
    with pytest.raises(SystemExit) as exc_info:
        _run(["ddl", "orders"])
    assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# The subcommands, in each format
# ---------------------------------------------------------------------------


def test_tables_lists_tables_and_views_as_json(built, capsys):
    _run(["tables", "-o", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert [row["name"] for row in payload] == ["orders", "recent_orders"]
    assert payload[0]["table_type"] == "BASE_TABLE"
    assert payload[1]["table_type"] == "VIEW"
    backend = built[0]
    assert backend.connected is True
    assert backend.disconnected is True
    assert backend.introspector.calls == [("list_tables", None, False)]


def test_tables_scopes_to_the_dataset_given(built, capsys):
    _run(["tables", "--dataset", "my_dataset", "-o", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["schema"] == "my_dataset"
    # The dataset reaches the introspector as the schema argument.
    assert built[0].introspector.calls == [("list_tables", "my_dataset", False)]


def test_one_flag_names_the_dataset(built, capsys):
    """``--dataset`` is the only namespace flag, and it is the scope.

    BigQuery has no schema under a dataset, so there is one level to name
    and one flag to name it with. An earlier version also accepted
    ``--schema`` and made it override this one, which spelled the same
    level under a word BigQuery does not use and made the precedence the
    thing a reader had to work out.
    """
    _run(["tables", "--dataset", "my_dataset", "-o", "json"])
    capsys.readouterr()
    assert built[0].introspector.calls == [("list_tables", "my_dataset", False)]


def test_the_second_spelling_is_not_accepted(built, capsys):
    """``--schema`` is gone, not aliased.

    An alias would let a caller keep naming a level that does not exist
    here, which is the confusion the single flag removes.
    """
    with pytest.raises(SystemExit):
        _run(["tables", "--dataset", "my_dataset", "--schema", "other"])


def test_tables_as_csv(built, capsys):
    _run(["tables", "--dataset", "my_dataset", "-o", "csv"])
    out = capsys.readouterr().out
    assert "name,schema,table_type" in out
    assert "orders,my_dataset,BASE_TABLE" in out


def test_tables_as_tsv(built, capsys):
    _run(["tables", "--dataset", "my_dataset", "-o", "tsv"])
    out = capsys.readouterr().out
    assert "name\tschema\ttable_type" in out
    assert "orders\tmy_dataset\tBASE_TABLE" in out


def test_tables_as_table(built, capsys):
    """``table`` is the default format; without rich it degrades to json."""
    _run(["tables"])
    out = capsys.readouterr().out
    assert "orders" in out


def test_views_lists_views_as_json(built, capsys):
    _run(["views", "--dataset", "my_dataset", "-o", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert [row["name"] for row in payload] == ["recent_orders"]
    assert payload[0]["definition"] == "SELECT * FROM orders"
    assert payload[0]["extra"] == {"use_standard_sql": True}
    assert built[0].introspector.calls == [("list_views", "my_dataset")]


def test_datasets_lists_datasets_as_json(built, capsys):
    _run(["datasets", "-o", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert [row["schema_name"] for row in payload] == ["my_dataset"]
    assert payload[0]["catalog_name"] == "my-project"
    assert built[0].introspector.calls == [("list_datasets",)]


def test_routines_lists_the_dataset_routines_as_json(built, capsys):
    _run(["routines", "--dataset", "my_dataset", "-o", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert [row["routine_name"] for row in payload] == ["add_one"]
    assert payload[0]["routine_type"] == "FUNCTION"
    assert payload[0]["is_deterministic"] is True
    assert built[0].introspector.calls == [("list_routines", "my_dataset")]


def test_a_named_routine_is_one_record_as_json(built, capsys):
    _run(["routines", "add_one", "--dataset", "my_dataset", "-o", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload == [
        {
            "routine_name": "add_one",
            "routine_type": "FUNCTION",
            "specific_catalog": None,
            "specific_schema": None,
            "specific_name": None,
            "routine_catalog": None,
            "routine_schema": "my_dataset",
            "data_type": "INT64",
            "routine_body": None,
            "routine_definition": None,
            "external_language": None,
            "is_deterministic": True,
            "security_type": None,
            "created": None,
            "last_altered": None,
            "connection": None,
            "ddl": None,
        }
    ]
    assert built[0].introspector.calls == [("get_routine_info", "add_one", "my_dataset")]


def test_a_missing_routine_exits_non_zero(built, capsys):
    with pytest.raises(SystemExit) as exc_info:
        _run(["routines", "missing", "--dataset", "my_dataset", "-o", "json"])
    assert exc_info.value.code == 1
    assert "no routine named 'missing'" in capsys.readouterr().err


def test_columns_lists_one_tables_columns_as_json(built, capsys):
    _run(["columns", "orders", "--dataset", "my_dataset", "-o", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert [row["name"] for row in payload] == ["id"]
    assert payload[0]["nullable"] == "NOT_NULL"
    assert built[0].introspector.calls == [("list_columns", "orders", "my_dataset")]


def test_database_reports_the_project_as_json(built, capsys):
    """The project-level question: one record, and no dataset in the question.

    The answer names the feature level as a feature level rather than a
    server release, which is what the ``extra`` the introspector fills
    carries -- a CLI that dropped it would present a number as a version.
    """
    _run(["database", "-o", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload == [
        {
            "name": "my-project",
            "version": "3.0.0",
            "version_tuple": [3, 0, 0],
            "vendor": "BigQuery",
            "encoding": None,
            "collation": None,
            "timezone": None,
            "size_bytes": None,
            "table_count": None,
            "extra": {
                "project": "my-project",
                "dataset": None,
                "location": None,
                "version_source": "backend feature level, not a server version",
            },
        }
    ]
    assert built[0].introspector.calls == [("get_database_info",)]


def test_partitions_lists_one_tables_partitions_as_json(built, capsys):
    _run(["partitions", "orders", "--dataset", "my_dataset", "-o", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["partition_id"] == "20260101"
    assert payload[0]["total_billable_bytes"] == 4096
    assert built[0].introspector.calls == [("list_partitions", "orders", "my_dataset")]


# ---------------------------------------------------------------------------
# Failure paths: each one a non-zero exit naming the reason
# ---------------------------------------------------------------------------



def test_columns_without_a_name_exits_non_zero(capsys):
    with pytest.raises(SystemExit) as exc_info:
        _run(["columns", "-o", "json"])
    assert exc_info.value.code == 2
    assert "required" in capsys.readouterr().err



def test_a_value_error_from_the_introspector_exits_non_zero(built, capsys, monkeypatch):
    """A missing dataset: the introspector raises with the instruction."""
    backend = _FakeBackend()

    def _exploding_list_tables(schema=None, include_system=False):
        raise ValueError(
            "BigQuery introspection needs a dataset: pass schema= (the "
            "dataset ID) or configure BigQueryConnectionConfig(dataset=...)."
        )

    backend.introspector.list_tables = _exploding_list_tables
    monkeypatch.setattr(cli_introspect, "_build_backend", lambda args: backend)

    with pytest.raises(SystemExit) as exc_info:
        _run(["tables", "-o", "json"])
    assert exc_info.value.code == 1
    assert "pass schema=" in capsys.readouterr().err


def test_an_unknown_output_format_is_refused_by_argparse():
    with pytest.raises(SystemExit) as exc_info:
        _run(["tables", "-o", "yaml"])
    assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# The async path runs the same questions through the same CLI
# ---------------------------------------------------------------------------


def test_tables_as_json_async(built, capsys, monkeypatch):
    """The async backend answers the same CLI through awaited questions."""

    class _AsyncIntrospector(_FakeIntrospector):
        async def list_tables(self, schema=None, include_system=False):
            self.calls.append(("list_tables", schema, include_system))
            return self._tables_payload(schema)

    class _AsyncFakeBackend(_FakeBackend):
        async def connect(self):
            self.connected = True

        async def disconnect(self):
            self.disconnected = True

    backend = _AsyncFakeBackend()
    backend.introspector = _AsyncIntrospector()
    monkeypatch.setattr(cli_introspect, "_build_backend", lambda args: backend)

    _run(["tables", "--use-async", "--dataset", "my_dataset", "-o", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert [row["name"] for row in payload] == ["orders", "recent_orders"]
    assert backend.connected is True
    assert backend.disconnected is True
    # One question, recorded once: the async method records its own call and
    # builds the same list without re-recording.
    assert backend.introspector.calls == [("list_tables", "my_dataset", False)]
