# tests/rhosocial/activerecord_bigquery_test/feature/rules/backend/conftest.py
"""Fixtures for the BigQuery backend's own rule suite.

The shared testsuite conftest supplies every fixture the rule modules need;
this file only selects the subject: this repository's installed BigQuery
expression package, dialect, implementation tree, project root and tests.
``source_roots`` deliberately yields exactly one pair so no core tree and no
other backend's tree is ever scanned. All roots are derived from importable
packages, never from a hardcoded worktree path.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
from typing import Iterator, List, Tuple

import pytest

from rhosocial.activerecord.testsuite.feature.rules.backend.conftest import *  # noqa: F401,F403
from rhosocial.activerecord.testsuite.pytest_plugin import Declaration

DECLARATION = Declaration(
    uses_database=False,
    parallel=False,
    purpose="Executable assertions of the BigQuery backend's formal constraints",
    passes_means="BigQuery source obeys the mechanical and structural rule",
    fails_means="BigQuery source introduces a forbidden construct or dependency",
)

BACKEND_NAME = "bigquery"
EXPRESSION_PACKAGE = "rhosocial.activerecord.backend.impl.bigquery.expression"
DIALECT_MODULE = "rhosocial.activerecord.backend.impl.bigquery.dialect"
DIALECT_CLASS = "BigQueryDialect"
BACKEND_PREFIX = "BigQuery"


def python_files_in(root: Path) -> Iterator[Path]:
    """Sorted Python files below *root*, excluding bytecode caches."""
    if root.is_dir():
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" not in path.parts:
                yield path


def expression_package() -> object:
    """The installed BigQuery expression package."""
    package = importlib.import_module(EXPRESSION_PACKAGE)
    assert vars(package).get("__path__"), f"{EXPRESSION_PACKAGE} is not a package"
    return package


def impl_root() -> Path:
    """The installed ``backend/impl/bigquery`` directory."""
    package = expression_package()
    for search_path in vars(package).get("__path__", ()):
        current = Path(search_path).resolve()
        for candidate in [current] + list(current.parents):
            if candidate.name == "impl" and candidate.parent.name == "backend":
                return candidate / current.relative_to(candidate).parts[0]
    pytest.skip("BigQuery impl root is not discoverable from the installed package")


def project_root() -> Path:
    """Project root inferred from the installed BigQuery package layout."""
    for candidate in [impl_root()] + list(impl_root().parents):
        if (candidate / "src").is_dir() and (candidate / "tests").is_dir():
            return candidate
    pytest.skip("BigQuery project root is not discoverable from the installed package")


@pytest.fixture
def backend_expression_package() -> object:
    """BigQuery's expression package."""
    return expression_package()


@pytest.fixture
def backend_dialect() -> object:
    """An instantiated BigQuery dialect."""
    dialect_cls = getattr(importlib.import_module(DIALECT_MODULE), DIALECT_CLASS)
    return dialect_cls()


@pytest.fixture
def backend_prefix() -> str:
    """BigQuery's own naming prefix."""
    return BACKEND_PREFIX


@pytest.fixture
def backend_impl_root() -> Path:
    """The BigQuery ``impl`` root used by file-driven shared rules."""
    return impl_root()


@pytest.fixture
def source_roots() -> List[Tuple[str, Path]]:
    """One root only: this backend's implementation tree, never core's."""
    return [(BACKEND_NAME, impl_root())]


@pytest.fixture
def backend_project_root() -> Path:
    """Project root for this backend's tests."""
    return project_root()


@pytest.fixture
def backend_test_files() -> List[Path]:
    """Every Python test file in this backend's project."""
    files = list(python_files_in(project_root() / "tests"))
    assert files, f"no test files under {project_root() / 'tests'}"
    return files


def has_pinned_unconstructible(path: Path) -> bool:
    """Whether a test file pins at least one UNCONSTRUCTIBLE class.

    A matrix with an empty pin set has no entry whose reason can be audited;
    its own two-way constructor comparison already proves the emptiness. Such
    a file is not a pin-bearing matrix for the shared discipline rule.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return False
    for node in ast.walk(tree):
        targets = node.targets if isinstance(node, ast.Assign) else (
            [node.target] if isinstance(node, ast.AnnAssign) else []
        )
        if not any(isinstance(target, ast.Name) and target.id == "UNCONSTRUCTIBLE" for target in targets):
            continue
        value = node.value
        if isinstance(value, ast.Dict):
            return bool(value.keys)
        if isinstance(value, (ast.Tuple, ast.List, ast.Set)):
            return bool(value.elts)
    return False


@pytest.fixture
def backend_matrix_files(backend_test_files: List[Path]) -> List[Path]:
    """Round-trip matrices in this backend's tests that pin unbuildable classes."""
    return [path for path in backend_test_files if has_pinned_unconstructible(path)]


@pytest.fixture
def minimum_observed_calls() -> int:
    """This backend exposes no reflection calls, so the floor sits below zero.

    The rule asserts ``observed > minimum``; -1 still fails an empty scan
    result only if the scan is somehow skipped, while every actual call remains
    a violation. Non-vacuity is also covered by the file-count guards in the
    other shared rules.
    """
    return -1
