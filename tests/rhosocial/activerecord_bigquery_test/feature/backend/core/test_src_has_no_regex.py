# tests/rhosocial/activerecord_bigquery_test/feature/backend/core/test_src_has_no_regex.py
"""``src`` may not import ``re``: the text scans are the whole point.

Two readings in this backend recognise text a caller wrote -- a declared
column type (introspection) and a declared partition/cluster spelling (DDL).
Both were regular expressions, and both are now character scans in
``_scan.py``.  What remains of ``re`` here is nothing, and a guard keeps it
that way: the rule is about the source tree, which a test can read.

Two checks, because a regex use has two shapes:

* the AST of every module is walked for ``import re`` / ``from re import``,
  which catches an alias such as ``import re as regex`` too;
* every module is tokenised and a ``re`` name followed by ``.`` is refused,
  which catches the expression used without a fresh import.  Tests may keep
  the expression they already had for asserting generated SQL; ``src`` may
  not.

Neither check needs ``re`` itself: the token walk is ``tokenize``, for the
same reason the code it guards is a character scan.  Both checks are also
given fabricated sources below, because a guard that never flags anything is
indistinguishable from one that cannot.
"""

import ast
import io
import tokenize
from pathlib import Path

import pytest


def _repository_root() -> Path:
    """The directory holding ``pyproject.toml`` and ``src`` above this file."""
    for directory in Path(__file__).resolve().parents:
        if (directory / "pyproject.toml").is_file() and (directory / "src").is_dir():
            return directory
    raise RuntimeError("cannot locate the repository root above this test file")


_ROOT = _repository_root()
_SRC = _ROOT / "src"
_MODULES = sorted(_SRC.rglob("*.py"))


def _regex_imports(source: str, filename: str = "<memory>") -> "list[str]":
    """Every import of the ``re`` module in *source*, aliases included."""
    tree = ast.parse(source, filename=filename)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "re" or alias.name.startswith("re."):
                    found.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module == "re":
            found.append("from re import ...")
    return found


def _regex_attribute_lines(source: str, filename: str = "<memory>") -> "list[int]":
    """The lines where a ``re`` name token is followed directly by a ``.``.

    Tokenising rather than searching the text is what keeps a docstring or a
    comment that *mentions* ``re.compile`` out of the answer: prose is one
    ``STRING`` or ``COMMENT`` token, not a name and a dot.
    """
    found = []
    tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    for current, following in zip(tokens, tokens[1:], strict=False):
        if (
            current.type == tokenize.NAME
            and current.string == "re"
            and following.type == tokenize.OP
            and following.string == "."
        ):
            found.append(current.start[0])
    return found


def test_the_guard_has_a_source_tree_to_walk():
    """A guard over nothing passes for the wrong reason."""
    assert _MODULES, f"no Python modules found under {_SRC}"


@pytest.mark.parametrize(
    "module", _MODULES, ids=lambda path: str(path.relative_to(_SRC))
)
def test_no_module_imports_the_regex_module(module):
    """No import, however it is spelled, may reach the ``re`` module."""
    imported = _regex_imports(
        module.read_text(encoding="utf-8"), filename=str(module)
    )
    assert not imported, f"{module.relative_to(_ROOT)} imports re: {imported}"


def test_no_module_uses_the_regex_attribute():
    """No module uses ``re.<something>``, with or without a fresh import."""
    offenders = []
    for module in _MODULES:
        text = module.read_text(encoding="utf-8")
        lines = _regex_attribute_lines(text, filename=str(module))
        for number in lines:
            offenders.append(
                f"{module.relative_to(_ROOT)}:{number}: {text.splitlines()[number - 1].strip()}"
            )
    assert not offenders, "src uses the re module by attribute: " + "; ".join(offenders)


@pytest.mark.parametrize(
    "source,expected",
    (
        ("import re\n", "import re"),
        ("import re as regex\n", "import re"),
        ("import re.compile\n", "import re.compile"),
        ("from re import compile\n", "from re import ..."),
        ("from re import compile as pattern\n", "from re import ..."),
    ),
    ids=(
        "plain-import",
        "aliased-import",
        "submodule-import",
        "from-import",
        "from-import-aliased",
    ),
)
def test_the_import_scanner_flags_fabricated_violations(source, expected):
    """The AST check answers for the violations it is meant to catch."""
    assert expected in _regex_imports(source, filename="fabricated.py")


def test_the_import_scanner_passes_a_clean_fabricated_source():
    """A source that does not import the module is not flagged."""
    assert not _regex_imports("import os\n", filename="fabricated.py")


@pytest.mark.parametrize(
    "source,line",
    (
        ("pattern = re.compile('x')\n", 1),
        ("import os\n\nvalue = re.fullmatch('x', 'y')\n", 3),
        ("re.Pattern\n", 1),
    ),
    ids=("module-call", "call-on-a-later-line", "module-attribute"),
)
def test_the_attribute_scanner_flags_fabricated_violations(source, line):
    """The token check answers for the violations it is meant to catch."""
    assert _regex_attribute_lines(source, filename="fabricated.py") == [line]


def test_the_attribute_scanner_ignores_prose_and_other_names():
    """A mention of ``re.`` in prose, and a name that merely ends in ``re``."""
    source = (
        "# re.compile appears in this comment only\n"
        'doc = "``re.compile`` is prose, not a call"\n'
        "require.match('x')\n"
        "core.split('x')\n"
    )
    assert _regex_attribute_lines(source, filename="fabricated.py") == []
