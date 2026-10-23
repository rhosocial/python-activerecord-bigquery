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
    IntrospectionTableInfo,
    IntrospectionViewInfo,
    TableType,
)

from rhosocial.activerecord.backend.impl.bigquery import cli as cli_package
from rhosocial.activerecord.backend.impl.bigquery.__main__ import main
from rhosocial.activerecord.backend.impl.bigquery.cli import introspect as cli_introspect


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
        "table",
        "columns",
        "datasets",
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


# ---------------------------------------------------------------------------
# The five subcommands, in each format
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


def test_schema_flag_overrides_the_dataset_flag(built, capsys):
    _run(
        [
            "tables",
            "--dataset",
            "my_dataset",
            "--schema",
            "other_dataset",
            "-o",
            "json",
        ]
    )
    capsys.readouterr()
    assert built[0].introspector.calls == [("list_tables", "other_dataset", False)]


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


def test_table_prints_columns_and_the_primary_key(built, capsys):
    _run(["table", "orders", "--dataset", "my_dataset", "-o", "json"])
    out = capsys.readouterr().out
    # Two displays: the columns, then the primary key. Each is a
    # pretty-printed JSON array, back to back, so decode them in order.
    decoder = json.JSONDecoder()
    columns, index = decoder.raw_decode(out.lstrip())
    rest = out.lstrip()[decoder.raw_decode(out.lstrip())[1] :].lstrip()
    indexes, _end = decoder.raw_decode(rest)
    assert [row["name"] for row in columns] == ["id"]
    assert [row["name"] for row in indexes] == ["pk_orders"]
    assert indexes[0]["is_primary"] is True
    assert indexes[0]["extra"] == {"constraint_type": "PRIMARY KEY"}
    assert built[0].introspector.calls == [("get_table_info", "orders", "my_dataset")]


def test_columns_lists_one_tables_columns_as_json(built, capsys):
    _run(["columns", "orders", "--dataset", "my_dataset", "-o", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert [row["name"] for row in payload] == ["id"]
    assert payload[0]["nullable"] == "NOT_NULL"
    assert built[0].introspector.calls == [("list_columns", "orders", "my_dataset")]


# ---------------------------------------------------------------------------
# Failure paths: each one a non-zero exit naming the reason
# ---------------------------------------------------------------------------


def test_table_without_a_name_exits_non_zero(capsys):
    with pytest.raises(SystemExit) as exc_info:
        _run(["table", "-o", "json"])
    # The positional name is required, so argparse refuses before the
    # handler runs -- a different refusal from a table that does not exist.
    assert exc_info.value.code == 2
    assert "required" in capsys.readouterr().err


def test_columns_without_a_name_exits_non_zero(capsys):
    with pytest.raises(SystemExit) as exc_info:
        _run(["columns", "-o", "json"])
    assert exc_info.value.code == 2
    assert "required" in capsys.readouterr().err


def test_an_unknown_table_exits_non_zero(built, capsys):
    with pytest.raises(SystemExit) as exc_info:
        _run(["table", "missing", "-o", "json"])
    assert exc_info.value.code == 1
    assert "not found" in capsys.readouterr().err


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
