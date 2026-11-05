# tests/rhosocial/activerecord_bigquery_test/feature/backend/introspection/test_introspect_families_cli.py
"""The nine families, as the BigQuery CLI asks for them.

No project and no credentials are needed here. What is checked is the wiring
the CLI owns: that each type reaches its introspector method, that NAME and
the type-specific flags arrive as arguments rather than being parsed and
dropped, that a family this project refuses is refused, and that a figure the
server will not answer stays "cannot be measured" instead of becoming an empty
row. Whether the answer is right is the introspector's question, and the live
tests carry it.

Six of the nine are gated, not answered: ``INFORMATION_SCHEMA`` describes
objects rather than a statistics collector, so ``unused-indexes``,
``table-stats``, ``runtime``, ``index-stats``, ``dependencies`` and ``ddl``
are refused at the capability question. Their branches are still asserted
here, by holding the gate open, because "the CLI can ask this and is told no"
and "the CLI cannot ask this" are different contracts and only one of them is
true.

Three answer, and the profile speaks for the one cost a reader has to know:
BigQuery bills bytes read, so a profile is a full scan. That sentence belongs
on stderr so stdout stays parseable, and each row's ``source`` says the
figures are exact counts rather than estimates.
"""

import argparse
import json
from typing import Optional

import pytest

from rhosocial.activerecord.backend.impl.bigquery.cli import introspect as introspect_cli
from rhosocial.activerecord.backend.impl.bigquery.dialect import BigQueryDialect
from rhosocial.activerecord.backend.introspection.types import (
    ColumnDataProfile,
    ColumnValueFrequency,
    DDLStatement,
    JoinCoverage,
)

#: The nine families this change wires, and the switch that gates each.
#: The dialect declares three of them; the rest it declines, and the refusal
#: is the answer this backend gives rather than an empty row.
NEW_FAMILIES = {
    "unused-indexes": "supports_unused_indexes_detection",
    "table-stats": "supports_table_stats",
    "runtime": "supports_runtime_stats",
    "index-stats": "supports_index_stats",
    "dependencies": "supports_object_dependencies",
    "ddl": "supports_ddl_extraction",
    "column-profiles": "supports_column_data_profile",
    "value-samples": "supports_column_value_sample",
    "join-coverage": "supports_join_coverage",
}

#: The families that answer for the whole dataset and take no NAME.
WHOLE_DATASET_FAMILIES = (
    "unused-indexes",
    "table-stats",
    "runtime",
    "index-stats",
)

#: The families that scan the rows, and so answer here.
ROW_FAMILIES = (
    "column-profiles",
    "value-samples",
    "join-coverage",
)


class _RecordingIntrospector:
    """Records each introspection call, and returns what the test declared.

    ``__getattr__`` is the whole implementation: a test names the method once,
    in the assertion, and a branch that reaches a different one fails on the
    recorded name rather than on an attribute error that would hide the typo.
    """

    def __init__(self, results: Optional[dict] = None) -> None:
        self.results = results or {}
        self.calls = []

    def __getattr__(self, name: str):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self.results.get(name)

        return call


class _AsyncRecordingIntrospector(_RecordingIntrospector):
    """The async shape of the same recorder: methods are awaited, calls are not."""

    def __getattr__(self, name: str):
        async def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self.results.get(name)

        return call


def _args(command: str, name: Optional[str] = None, **overrides) -> argparse.Namespace:
    """The attributes a parsed invocation carries, with sane defaults."""
    values = dict(
        output="json",
        rich_ascii=False,
        command=command,
        name=name,
        dataset="my_dataset",
        use_async=False,
        include_system=False,
        column=None,
        right_table=None,
        right_column=None,
    )
    values.update(overrides)
    return argparse.Namespace(**values)


class _BackendStub:
    """A backend that connects, answers from the recorder and records nothing else.

    ``dialect`` is the real one so a capability switch answers the way it does
    against a project; ``_client`` is the sentinel the runner uses to decide
    whether there is anything to disconnect.
    """

    dialect = BigQueryDialect()
    _client = object()

    def __init__(self, introspector) -> None:
        self.introspector = introspector
        self.disconnected = False

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        self.disconnected = True


class _AsyncBackendStub(_BackendStub):
    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        self.disconnected = True


def _run_sync(monkeypatch, introspector, args, gate_open: bool = False) -> None:
    backend = _BackendStub(introspector)
    monkeypatch.setattr(introspect_cli, "_build_backend", lambda _args: backend)
    if gate_open:
        # The branch is asserted without the project's answer: the gate is
        # what refuses these families, and it is tested on its own below.
        monkeypatch.setattr(introspect_cli, "_require_capability", lambda *a: None)
    introspect_cli.handle(args)


def _run_async(monkeypatch, introspector, args, gate_open: bool = False) -> None:
    backend = _AsyncBackendStub(introspector)
    monkeypatch.setattr(introspect_cli, "_build_backend", lambda _args: backend)
    if gate_open:
        monkeypatch.setattr(introspect_cli, "_require_capability", lambda *a: None)
    introspect_cli.handle(args)


class TestTheDatasetWideFamilies:
    """The counters and listings describe the dataset, so NAME is refused."""

    @pytest.mark.parametrize(
        "command, method",
        [
            ("unused-indexes", "list_unused_indexes"),
            ("table-stats", "list_table_usage_stats"),
            ("runtime", "list_runtime_metrics"),
            ("index-stats", "list_index_usage_stats"),
        ],
    )
    def test_the_family_asks_its_method_for_the_whole_dataset(self, command, method, monkeypatch):
        introspector = _RecordingIntrospector({method: []})

        # The gate open because these four are refused by this backend;
        # what is asserted is the branch behind the refusal.
        _run_sync(monkeypatch, introspector, _args(command), gate_open=True)

        assert introspector.calls == [(method, (), {"schema": "my_dataset"})]

    @pytest.mark.parametrize("command", WHOLE_DATASET_FAMILIES)
    def test_a_name_is_refused(self, command, capsys):
        with pytest.raises(SystemExit) as excinfo:
            introspect_cli._refuse_name(_args(command, "orders"))

        assert excinfo.value.code == 2
        assert "does not take an object name" in capsys.readouterr().err


class TestTheDdlBranch:
    """The schema object, not a name, is what a caller parses."""

    def _statement(self) -> DDLStatement:
        return DDLStatement(
            schema=None,
            object_type="TABLE",
            object_name="orders",
            ddl="CREATE TABLE orders (id INT64)",
            native=True,
        )

    def test_the_table_is_asked_for_by_name(self, monkeypatch):
        introspector = _RecordingIntrospector({"get_ddl_statement": self._statement()})

        _run_sync(monkeypatch, introspector, _args("ddl", "orders"), gate_open=True)

        assert introspector.calls == [
            ("get_ddl_statement", ("orders",), {"object_type": None, "schema": "my_dataset"})
        ]

    def test_a_missing_name_is_an_incomplete_invocation(self, monkeypatch, capsys):
        """A missing required NAME exits 1, like a missing ``--dataset``.

        ``ddl`` is refused by this backend's gate, so the gate is held open
        to reach the branch's own check: the exit code is the difference
        between "you did not finish the invocation" (1) and "this project
        will not answer that" (2), and only one of them is a defect in the
        request.
        """
        with pytest.raises(SystemExit) as excinfo:
            _run_sync(monkeypatch, _RecordingIntrospector({}), _args("ddl"), gate_open=True)

        assert excinfo.value.code == 1
        assert "required" in capsys.readouterr().err

    def test_no_ddl_is_an_error_not_an_empty_listing(self, monkeypatch, capsys):
        introspector = _RecordingIntrospector({"get_ddl_statement": None})

        with pytest.raises(SystemExit) as excinfo:
            _run_sync(monkeypatch, introspector, _args("ddl", "orders"), gate_open=True)

        assert excinfo.value.code == 1
        assert "no DDL available" in capsys.readouterr().err


class TestTheColumnProfilesBranch:
    """One scan, billed, and the cost said before the rows."""

    def _profile(self) -> ColumnDataProfile:
        return ColumnDataProfile(
            schema="my_dataset",
            table_name="orders",
            column_name="status",
            null_fraction=0.0,
            distinct_count=3,
            min_value="a",
            max_value="c",
            row_count=100,
            source="aggregate",
        )

    def test_the_table_is_asked_for_by_name(self, monkeypatch):
        introspector = _RecordingIntrospector({"list_column_data_profiles": [self._profile()]})

        _run_sync(monkeypatch, introspector, _args("column-profiles", "orders"))

        assert introspector.calls == [
            ("list_column_data_profiles", ("orders",), {"schema": "my_dataset"})
        ]

    def test_the_billed_scan_is_stated_to_the_reader(self, monkeypatch, capsys):
        introspector = _RecordingIntrospector({"list_column_data_profiles": [self._profile()]})

        _run_sync(monkeypatch, introspector, _args("column-profiles", "orders"))

        err = capsys.readouterr().err
        assert "scan" in err
        assert "bills by bytes read" in err

    def test_the_cost_note_does_not_break_stdout(self, monkeypatch, capsys):
        introspector = _RecordingIntrospector({"list_column_data_profiles": [self._profile()]})

        _run_sync(monkeypatch, introspector, _args("column-profiles", "orders"))

        out = capsys.readouterr().out
        assert out.lstrip().startswith("[")

    def test_the_figures_say_they_are_exact_counts(self, monkeypatch, capsys):
        """``source`` is a column, not a footnote: the numbers are counts."""
        introspector = _RecordingIntrospector({"list_column_data_profiles": [self._profile()]})

        _run_sync(monkeypatch, introspector, _args("column-profiles", "orders"))

        row = json.loads(capsys.readouterr().out)[0]
        assert row["source"] == "aggregate"
        assert row["distinct_count"] == 3
        assert row["row_count"] == 100


class TestTheValueSamplesBranch:
    """A table and a column, and the flag that names it."""

    def test_the_table_and_column_reach_the_introspector(self, monkeypatch):
        introspector = _RecordingIntrospector(
            {"sample_column_values": [ColumnValueFrequency(value="a", count=7)]}
        )

        _run_sync(
            monkeypatch,
            introspector,
            _args("value-samples", "orders", column="status"),
        )

        assert introspector.calls == [
            ("sample_column_values", ("orders", "status"), {"schema": "my_dataset"})
        ]

    def test_a_missing_table_is_an_incomplete_invocation(self, monkeypatch, capsys):
        with pytest.raises(SystemExit) as excinfo:
            _run_sync(monkeypatch, _RecordingIntrospector({}), _args("value-samples"))

        assert excinfo.value.code == 1
        assert "table name is required" in capsys.readouterr().err

    def test_a_missing_column_is_an_incomplete_invocation(self, monkeypatch, capsys):
        introspect_cli._refuse_unused_arguments(_args("value-samples", "orders"))

        with pytest.raises(SystemExit) as excinfo:
            _run_sync(monkeypatch, _RecordingIntrospector({}), _args("value-samples", "orders"))

        assert excinfo.value.code == 1
        assert "--column is required" in capsys.readouterr().err

    def test_the_most_frequent_values_are_printed(self, monkeypatch, capsys):
        introspector = _RecordingIntrospector(
            {"sample_column_values": [ColumnValueFrequency(value="a", count=7)]}
        )

        _run_sync(
            monkeypatch,
            introspector,
            _args("value-samples", "orders", column="status"),
        )

        payload = json.loads(capsys.readouterr().out)
        assert payload[0]["value"] == "a"
        assert payload[0]["count"] == 7

    def test_no_measurement_is_an_error(self, monkeypatch, capsys):
        introspector = _RecordingIntrospector({"sample_column_values": None})

        with pytest.raises(SystemExit) as excinfo:
            _run_sync(
                monkeypatch,
                introspector,
                _args("value-samples", "orders", column="status"),
            )

        assert excinfo.value.code == 1
        assert "could not measure" in capsys.readouterr().err


class TestTheJoinCoverageBranch:
    """Four names, both sides of the measurement, in the order they are asked."""

    def _coverage(self) -> JoinCoverage:
        return JoinCoverage(
            left_table="orders",
            left_column="buyer_id",
            right_table="users",
            right_column="id",
            left_coverage=1.0,
            right_coverage=0.75,
        )

    def test_the_four_names_reach_the_introspector(self, monkeypatch):
        introspector = _RecordingIntrospector({"estimate_join_coverage": self._coverage()})

        _run_sync(
            monkeypatch,
            introspector,
            _args(
                "join-coverage",
                "orders",
                column="buyer_id",
                right_table="users",
                right_column="id",
            ),
        )

        assert introspector.calls == [
            (
                "estimate_join_coverage",
                ("orders", "buyer_id", "users", "id"),
                {"schema": "my_dataset"},
            )
        ]

    def test_both_fractions_are_reported(self, monkeypatch, capsys):
        introspector = _RecordingIntrospector({"estimate_join_coverage": self._coverage()})

        _run_sync(
            monkeypatch,
            introspector,
            _args(
                "join-coverage",
                "orders",
                column="buyer_id",
                right_table="users",
                right_column="id",
            ),
        )

        payload = json.loads(capsys.readouterr().out)
        assert payload == [
            {
                "left_schema": None,
                "left_table": "orders",
                "left_column": "buyer_id",
                "right_schema": None,
                "right_table": "users",
                "right_column": "id",
                "left_coverage": 1.0,
                "right_coverage": 0.75,
                "extra": {},
            }
        ]

    def test_a_missing_right_table_is_an_incomplete_invocation(self, monkeypatch, capsys):
        with pytest.raises(SystemExit) as excinfo:
            _run_sync(
                monkeypatch,
                _RecordingIntrospector({}),
                _args("join-coverage", "orders", column="buyer_id"),
            )

        assert excinfo.value.code == 1
        err = capsys.readouterr().err
        assert "--right-table" in err
        assert "--right-column" in err

    def test_an_unmeasurable_pair_is_an_error(self, monkeypatch, capsys):
        """``None`` is "not measured", which is not a zero-overlap answer."""
        introspector = _RecordingIntrospector({"estimate_join_coverage": None})

        with pytest.raises(SystemExit) as excinfo:
            _run_sync(
                monkeypatch,
                introspector,
                _args(
                    "join-coverage",
                    "orders",
                    column="buyer_id",
                    right_table="users",
                    right_column="id",
                ),
            )

        assert excinfo.value.code == 1
        assert "could not measure" in capsys.readouterr().err


class TestTheDependenciesBranch:
    """One optional NAME narrows the graph; omitting it asks for all of it."""

    def test_a_named_object_is_asked_for_by_name(self, monkeypatch):
        introspector = _RecordingIntrospector({"list_object_dependencies": []})

        _run_sync(
            monkeypatch,
            introspector,
            _args("dependencies", "orders"),
            gate_open=True,
        )

        assert introspector.calls == [
            ("list_object_dependencies", (), {"object_name": "orders", "schema": "my_dataset"})
        ]

    def test_an_unnamed_run_asks_for_the_whole_graph(self, monkeypatch):
        introspector = _RecordingIntrospector({"list_object_dependencies": []})

        _run_sync(monkeypatch, introspector, _args("dependencies"), gate_open=True)

        assert introspector.calls == [
            ("list_object_dependencies", (), {"object_name": None, "schema": "my_dataset"})
        ]


class TestTheArgumentRules:
    def test_a_flag_the_type_does_not_read_is_refused(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            introspect_cli._refuse_unused_arguments(_args("tables", column="status"))

        assert excinfo.value.code == 2
        assert "does not take --column" in capsys.readouterr().err

    def test_the_right_hand_flags_belong_to_join_coverage_only(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            introspect_cli._refuse_unused_arguments(
                _args("value-samples", "orders", column="status", right_table="users")
            )

        assert excinfo.value.code == 2
        assert "--right-table" in capsys.readouterr().err

    def test_both_families_that_read_a_column_may_be_given_one(self):
        for command in ("value-samples", "join-coverage"):
            introspect_cli._refuse_unused_arguments(_args(command, column="status"))

    def test_a_required_name_is_required_for_the_new_families(self, monkeypatch, capsys):
        for command in ("ddl", "column-profiles", "value-samples"):
            with pytest.raises(SystemExit) as excinfo:
                _run_sync(
                    monkeypatch,
                    _RecordingIntrospector({}),
                    _args(command),
                    gate_open=True,
                )
            assert excinfo.value.code == 1


class TestTheCapabilityGate:
    @pytest.mark.parametrize("command, switch", list(NEW_FAMILIES.items()))
    def test_a_family_the_project_refuses_exits_two(self, command, switch, capsys):
        """The gate, not a failed statement, is what answers for a refusal."""

        class _Dialect:
            pass

        setattr(_Dialect, switch, staticmethod(lambda: False))

        class _Backend:
            dialect = _Dialect()

        with pytest.raises(SystemExit) as excinfo:
            introspect_cli._require_capability(_Backend(), _args(command))

        assert excinfo.value.code == 2
        assert "not supported by this server" in capsys.readouterr().err

    @pytest.mark.parametrize("command", ROW_FAMILIES)
    def test_the_row_families_are_not_refused(self, command):
        """These three answer True, so the gate must not refuse them."""
        introspect_cli._require_capability(_BackendStub(_RecordingIntrospector()), _args(command))

    def test_a_stub_without_a_dialect_is_not_refused(self):
        introspect_cli._require_capability(object(), _args("tables"))

    def test_the_declined_families_are_refused_by_this_dialect(self, capsys):
        """BigQuery has no statistics collector, and says so at the question."""
        for command in (
            "unused-indexes",
            "table-stats",
            "runtime",
            "index-stats",
            "dependencies",
            "ddl",
        ):
            with pytest.raises(SystemExit) as excinfo:
                introspect_cli._require_capability(
                    _BackendStub(_RecordingIntrospector()), _args(command)
                )
            assert excinfo.value.code == 2
            assert "not supported by this server" in capsys.readouterr().err


class TestTheAsyncPath:
    """The second dispatch chain must ask the same question the first one does."""

    @pytest.mark.parametrize(
        "command, method, args_kwargs, result, expected",
        [
            ("unused-indexes", "list_unused_indexes", {}, [], ((), {"schema": "my_dataset"})),
            ("table-stats", "list_table_usage_stats", {}, [], ((), {"schema": "my_dataset"})),
            ("runtime", "list_runtime_metrics", {}, [], ((), {"schema": "my_dataset"})),
            ("index-stats", "list_index_usage_stats", {}, [], ((), {"schema": "my_dataset"})),
            (
                "ddl",
                "get_ddl_statement",
                {"name": "orders"},
                DDLStatement(
                    object_type="TABLE",
                    object_name="orders",
                    ddl="CREATE TABLE orders (id INT64)",
                    native=True,
                ),
                (("orders",), {"object_type": None, "schema": "my_dataset"}),
            ),
            (
                "column-profiles",
                "list_column_data_profiles",
                {"name": "orders"},
                [],
                (("orders",), {"schema": "my_dataset"}),
            ),
            (
                "value-samples",
                "sample_column_values",
                {"name": "orders", "column": "status"},
                [],
                (("orders", "status"), {"schema": "my_dataset"}),
            ),
            (
                "join-coverage",
                "estimate_join_coverage",
                {
                    "name": "orders",
                    "column": "buyer_id",
                    "right_table": "users",
                    "right_column": "id",
                },
                JoinCoverage(
                    left_table="orders",
                    left_column="buyer_id",
                    right_table="users",
                    right_column="id",
                    left_coverage=1.0,
                    right_coverage=0.75,
                ),
                (("orders", "buyer_id", "users", "id"), {"schema": "my_dataset"}),
            ),
            (
                "dependencies",
                "list_object_dependencies",
                {"name": "orders"},
                [],
                ((), {"object_name": "orders", "schema": "my_dataset"}),
            ),
        ],
    )
    def test_the_async_branch_calls_the_same_method_with_the_same_arguments(
        self, command, method, args_kwargs, result, expected, monkeypatch
    ):
        # ``result`` is not ``[]`` everywhere: ``ddl`` answers ``None`` for
        # "no statement", and a stub that returned an empty list there would
        # send the branch down the display path instead of the call it is
        # being asked to reach.
        introspector = _AsyncRecordingIntrospector({method: result})

        _run_async(
            monkeypatch,
            introspector,
            _args(command, **args_kwargs, use_async=True),
            gate_open=True,
        )

        assert introspector.calls == [(method, expected[0], expected[1])]

    def test_the_async_profile_says_the_scan_is_billed(self, monkeypatch, capsys):
        profile = ColumnDataProfile(
            table_name="orders",
            column_name="status",
            row_count=100,
            source="aggregate",
        )
        introspector = _AsyncRecordingIntrospector({"list_column_data_profiles": [profile]})

        _run_async(monkeypatch, introspector, _args("column-profiles", "orders", use_async=True))

        assert "bills by bytes read" in capsys.readouterr().err


class TestTheTypeSurfaceExtension:
    def test_the_type_list_is_the_capability_table(self):
        assert list(introspect_cli._TYPE_CAPABILITIES) == list(
            introspect_cli.INTROSPECT_SUBCOMMANDS
        )

    def test_each_new_family_has_an_entry_naming_a_probe(self):
        for command, switch in NEW_FAMILIES.items():
            assert introspect_cli._TYPE_CAPABILITIES[command] == switch
            assert hasattr(BigQueryDialect, switch), command

    def test_every_type_has_a_branch_in_both_paths(self):
        """A type with no branch prints nothing and exits 0 -- the worst shape."""
        # Both runners read the same question table, so the question map is
        # where a missing branch would show up: an unlisted command falls
        # through to a KeyError rather than a silently empty run.
        questions = introspect_cli._questions(_args("tables"))
        for name in introspect_cli.INTROSPECT_SUBCOMMANDS:
            assert name in questions, name

    def test_every_type_is_registered_as_a_command(self):
        from rhosocial.activerecord.backend.impl.bigquery.cli import COMMAND_NAMES

        assert list(COMMAND_NAMES) == list(introspect_cli.INTROSPECT_SUBCOMMANDS)
        for name in introspect_cli.INTROSPECT_SUBCOMMANDS:
            assert introspect_cli.get_handler(name) is introspect_cli.handle

    def test_help_lists_every_type(self, capsys):
        root = argparse.ArgumentParser()
        introspect_cli.create_parser(root.add_subparsers())
        with pytest.raises(SystemExit):
            root.parse_args(["--help"])
        out = capsys.readouterr().out
        for name in introspect_cli.INTROSPECT_SUBCOMMANDS:
            assert name in out
