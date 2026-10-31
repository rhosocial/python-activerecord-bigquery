# tests/plugins/expression_xdist.py
"""Default the expression test areas to parallel when one of them is the target.

The org rules (expression-dialect §12.1) make pytest-xdist parallel the default
configuration of the expression test area. The worker count, however, is read by
pytest-xdist before any conftest loads -- a conftest cannot inject ``-n`` -- so
the default lives in this repository-local plugin, registered from
``pyproject.toml`` with ``-p plugins.expression_xdist`` and therefore active for
every run in this repository.

The plugin is deliberately narrow in what it touches:

* **Availability**: with pytest-xdist not installed it enables nothing --
  installation is not this plugin's business, and the run proceeds serially the
  way it always has.
* **Scope**: only when every named target is a pure-render test location. This
  repository keeps them in two places rather than one: ``expression/`` and
  ``dialect/``, plus the top-level round-trip matrix, because the matrix spans
  both packages and cannot live inside either. A whole-repository run, a mixed
  run, or a run of any other directory keeps the serial default; the backend
  modules that start a client, and the emulator scenario loader, are not dragged
  into a worker pool they did not ask for.
* **Choice respected**: an explicit ``-n`` / ``--numprocesses`` is never
  overridden. An explicit ``--dist`` is never overridden either, except that
  ``loadscope`` and ``loadfile`` are refused outright (§12.1: they bind whole
  modules together and hide case-to-case dependencies). ``-n`` without
  ``--dist`` gets ``--dist=loadgroup`` appended, because loadgroup is the one
  scheduling the rules allow.
"""

from __future__ import annotations

import os
from pathlib import Path

#: The areas this plugin defaults to parallel, relative to the repository root
#: (where ``pyproject.toml`` -- and therefore this plugin's registration --
#: lives). Both hold construction -> render tests only: no case starts a client,
#: creates a dataset or reads a file, which is what makes the default sound.
_BACKEND_TEST_ROOT = os.path.join(
    "tests", "rhosocial", "activerecord_bigquery_test", "feature", "backend"
)
_EXPRESSION_AREAS = (
    os.path.join(_BACKEND_TEST_ROOT, "expression"),
    os.path.join(_BACKEND_TEST_ROOT, "dialect"),
)

#: Single files that are pure render too, and live above the two directories
#: because they span both packages. The round-trip matrix walks core's package
#: and this backend's, so no one subject directory could hold it.
_EXPRESSION_FILES = (os.path.join(_BACKEND_TEST_ROOT, "test_expression_roundtrip_all.py"),)

#: Options that take a separate value, so the value must not be mistaken for a
#: path argument when scoping the invocation. ``-p`` matters most: this plugin is
#: itself registered as ``-p plugins.expression_xdist``, and its own name must
#: not be read as a test target.
_VALUE_TAKING = frozenset(
    {
        "-p", "-k", "-m", "-o", "-r", "-W", "--tb", "--deselect", "--basetemp",
        "--maxfail", "--rootdir", "--import-mode", "--pdbcls", "--lf",
        "--lfnf", "--cov", "--cov-config", "--cov-report",
        "--capture", "--color", "--junitxml", "--result-log",
        "-n", "--numprocesses", "--dist",
    }
)

_FORBIDDEN_DISTS = ("loadscope", "loadfile")


def _looks_like_path(arg: str) -> bool:
    """Whether *arg* names a test target rather than an option or a value."""
    return not arg.startswith("-")


def _repository_root() -> Path:
    """This repository's root, two levels above ``tests/plugins``."""
    return Path(__file__).resolve().parent.parent.parent


def _pure_render_locations() -> tuple[Path, ...]:
    """The absolute directories and files the parallel default covers."""
    root = _repository_root()
    return tuple(root / area for area in _EXPRESSION_AREAS + _EXPRESSION_FILES)


def _is_pure_render_target(arg: str) -> bool:
    """Whether *arg* names exactly one of the pure-render locations or is inside one.

    Inside means below one of the two directories. A file argument may also name
    any .py test inside those directories, which is how a single case file is run.
    """
    path = Path(os.path.abspath(arg))
    for location in _pure_render_locations():
        if path == location or location in path.parents:
            return True
    return False


def pytest_load_initial_conftests(args, early_config, parser):
    """Append the parallel default when every target is a pure-render one."""
    if not _xdist_available():
        print(
            "[expression_xdist] pytest-xdist is not installed; the "
            "expression areas run serially (install it to get the "
            "parallel default the test rules ask for)"
        )
        return

    targets = []
    skip_next = False
    for arg in args:
        if skip_next:
            skip_next = False
            continue
        if arg in _VALUE_TAKING:
            skip_next = True
            continue
        if arg.startswith("--") and "=" in arg:
            continue
        if _looks_like_path(arg):
            targets.append(arg)

    if not targets or not all(_is_pure_render_target(t) for t in targets):
        return

    def _option_value(flag: str):
        for index, arg in enumerate(args):
            if arg == flag and index + 1 < len(args):
                return args[index + 1]
            if arg.startswith(flag + "="):
                return arg.split("=", 1)[1]
        return None

    if _option_value("--dist") in _FORBIDDEN_DISTS:
        raise SystemExit(
            "[expression_xdist] --dist=loadscope/loadfile are not allowed "
            "for the expression areas (expression-dialect §12.1: they bind "
            "whole modules together; use --dist=loadgroup)"
        )

    if _option_value("-n") is None and _option_value("--numprocesses") is None:
        args.extend(["-n", "auto"])
    if _option_value("--dist") is None:
        args.extend(["--dist", "loadgroup"])


def _xdist_available() -> bool:
    """The availability condition: the plugin enables nothing without xdist,
    and installing it is nobody's business but the environment's."""
    try:
        import xdist  # noqa: F401
    except ImportError:
        return False
    return True
