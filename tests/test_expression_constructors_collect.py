# tests/test_expression_constructors_collect.py
"""An expression constructor collects; refusal belongs to the formatter."""
import ast
from pathlib import Path
from typing import List, Sequence, Union

import rhosocial.activerecord.backend.impl.bigquery as _pkg

_SRC = Path(next(iter(_pkg.__path__))) / "expression"
_Function = Union[ast.FunctionDef, ast.AsyncFunctionDef]


def _source_files() -> List[Path]:
    return [p for p in sorted(_SRC.rglob("*.py")) if "__pycache__" not in p.parts]


def _raises_unsupported(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Raise) or sub.exc is None:
            continue
        exc = sub.exc
        if isinstance(exc, ast.Call):
            exc = exc.func
        if isinstance(exc, ast.Name) and exc.id == "UnsupportedFeatureError":
            return True
        if isinstance(exc, ast.Attribute) and exc.attr == "UnsupportedFeatureError":
            return True
    return False


def _offenders(tree: ast.Module, label: str) -> List[str]:
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "__init__":
                if _raises_unsupported(item):
                    found.append(f"{label}:{item.lineno} {node.name}.__init__ refuses")
    return found


def _scan(paths: Sequence[Path]) -> List[str]:
    return [
        o for p in paths for o in _offenders(
            ast.parse(p.read_text(encoding="utf-8")), str(p.relative_to(_SRC))
        )
    ]


def test_no_expression_constructor_refuses_unsupported() -> None:
    files = _source_files()
    assert files, f"no source files found under {_SRC}"
    assert not _scan(files), "\n".join(_scan(files))


def test_the_scan_reaches_the_source_tree() -> None:
    assert len(_source_files()) >= 3
