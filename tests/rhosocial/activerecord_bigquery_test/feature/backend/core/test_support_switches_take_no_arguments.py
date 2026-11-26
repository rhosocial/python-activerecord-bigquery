# tests/rhosocial/activerecord_bigquery_test/feature/backend/core/test_support_switches_take_no_arguments.py
"""``supports_*`` is a support switch: no arguments, one bool.

A capability flag answers "does this dialect configuration have capability k",
so its only input is the dialect instance.  Anything that needs a name or a
kind is either a separate switch (closed vocabulary) or a format-time
validation (open vocabulary) -- never an argument to ``supports_*``.

This guard walks this repository's ``src`` tree with ``ast`` and fails on any
``supports_*`` method with a required positional or keyword parameter.  The
fabricated sources at the bottom prove the scan actually flags one: a guard
that never fires is indistinguishable from one that cannot.

The scan is over this backend's own modules, not core's, because a backend can
declare a violation core's guard never sees -- ``supports_json_function(name)``
lived here until the parameterless-switch round deleted it.
"""

import ast
from pathlib import Path

import pytest


def _repository_root() -> Path:
    """The directory holding ``pyproject.toml`` and ``src`` above this file."""
    for directory in Path(__file__).resolve().parents:
        if (directory / "pyproject.toml").is_file() and (directory / "src").is_dir():
            return directory
    raise RuntimeError("cannot locate the repository root above this test file")


_SRC = _repository_root() / "src"
_MODULES = sorted(
    path for path in _SRC.rglob("*.py") if "__pycache__" not in path.parts
)


def _required_arguments(func: ast.FunctionDef):
    """Parameters that must be passed, excluding ``self``.

    A defaulted parameter is not *required*, but a ``supports_*`` that accepts
    one still invites a caller to pass a name, so only the required ones are
    reported: that is the shape that makes the call impossible without an
    argument.
    """
    args = func.args
    positional = list(args.args)
    required = positional[1 : len(positional) - len(args.defaults)]
    for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=False):
        if default is None:
            required.append(arg)
    return [a.arg for a in required]


def _offenders(tree, label: str):
    """``supports_*`` methods in *tree* that cannot be called without an argument."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if not isinstance(item, ast.FunctionDef):
                continue
            if not item.name.startswith("supports_"):
                continue
            missing = _required_arguments(item)
            if missing:
                found.append(f"{label}:{item.lineno} {item.name}({', '.join(missing)})")
    return found


def test_the_guard_has_a_source_tree_to_walk():
    """A guard over nothing passes for the wrong reason."""
    assert _MODULES, f"no Python modules found under {_SRC}"


@pytest.mark.parametrize(
    "module", _MODULES, ids=lambda path: str(path.relative_to(_SRC))
)
def test_support_switch_takes_no_required_argument(module):
    """Every ``supports_*`` in this backend is a parameterless bool switch."""
    tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
    offenders = _offenders(tree, str(module.relative_to(_SRC)))
    assert not offenders, "supports_* needs an argument: " + "; ".join(offenders)


@pytest.mark.parametrize(
    "source",
    (
        "class P:\n"
        "    def supports_thing(self, name):\n"
        "        return False\n",
        "class P:\n"
        "    def supports_thing(self, *, kind):\n"
        "        return False\n",
        "class P:\n"
        "    def supports_thing(self, name=None, kind='x', *, other):\n"
        "        return False\n",
    ),
    ids=("positional", "keyword-only", "mixed"),
)
def test_the_scan_flags_a_planted_violation(tmp_path: Path, source: str):
    """A fabricated source with a required argument must be reported."""
    probe = tmp_path / "_probe.py"
    probe.write_text(source, encoding="utf-8")
    tree = ast.parse(probe.read_text(encoding="utf-8"), filename=str(probe))
    offenders = _offenders(tree, probe.name)
    assert offenders, f"the scan did not flag:\n{source}"
    assert "supports_thing" in offenders[0]


def test_the_scan_accepts_a_defaulted_parameter(tmp_path: Path):
    """A defaulted parameter is not required, so it is not reported."""
    probe = tmp_path / "_probe.py"
    probe.write_text(
        "class P:\n"
        "    def supports_thing(self, name=None):\n"
        "        return False\n",
        encoding="utf-8",
    )
    tree = ast.parse(probe.read_text(encoding="utf-8"), filename=str(probe))
    assert not _offenders(tree, probe.name)


def test_the_scan_ignores_functions_outside_a_class(tmp_path: Path):
    """A module-level helper is not a support switch."""
    probe = tmp_path / "_probe.py"
    probe.write_text(
        "def supports_thing(name):\n"
        "    return False\n",
        encoding="utf-8",
    )
    tree = ast.parse(probe.read_text(encoding="utf-8"), filename=str(probe))
    assert not _offenders(tree, probe.name)
