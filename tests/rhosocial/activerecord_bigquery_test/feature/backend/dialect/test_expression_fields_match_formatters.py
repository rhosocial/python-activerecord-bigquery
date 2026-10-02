# tests/rhosocial/activerecord_sqlserver_test/feature/backend/dialect/test_expression_fields_match_formatters.py
"""A formatter may not read a field its statement does not carry.

A statement formatter that reads ``expr.schema_name`` needs the expression to
have that attribute. When the formatter was changed to qualify names and the
expression was not given the field, the result is not wrong SQL -- it is an
``AttributeError`` on a statement that can never be built, which is how
SQLServerColumnstoreIndexExpression reached CI.

These are source scans rather than runtime tests because the failure needs the
right dialect, the right statement options and a live server to reach; a scan
fails the build the moment the shape reappears, wherever it appears.
"""
import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
SRC = REPO_ROOT / "src" / "rhosocial" / "activerecord"

#: Statement fields a formatter may read that the core expression classes carry
#: under a different name. Reading these by their own name is the defect.
KNOWN_ALIASES = {
    # TruncateExpression and the PostgreSQL vacuum/statistics expressions name
    # the field `schema`; the DDL statements name it `schema_name`.
    "schema": {"TruncateExpression"},
}


def _python_files():
    return sorted(
        p
        for p in SRC.rglob("*.py")
        if "__pycache__" not in p.parts
    )


def _class_fields(tree):
    """Map class name -> (own field names, base class names, has **kwargs)."""
    out = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        fields = {
            sub.attr
            for sub in ast.walk(node)
            if isinstance(sub, ast.Attribute)
            and isinstance(sub.value, ast.Name)
            and sub.value.id == "self"
        }
        bases = [b.id for b in node.bases if isinstance(b, ast.Name)]
        takes_kwargs = any(
            isinstance(a, ast.arg) and a.arg == "kwargs" for a in ast.walk(node)
        )
        out[node.name] = (fields, bases, takes_kwargs)
    return out


def _has_field(name, field, table, seen=None):
    seen = set() if seen is None else seen
    if name in seen or name not in table:
        return False
    seen.add(name)
    fields, bases, takes_kwargs = table[name]
    if field in fields or takes_kwargs:
        return True
    return any(_has_field(b, field, table, seen) for b in bases)


class TestFormattersOnlyReadRealFields:
    def _table(self):
        table = {}
        for path in _python_files():
            try:
                table.update(_class_fields(ast.parse(path.read_text(encoding="utf-8"))))
            except SyntaxError:  # pragma: no cover - syntax errors fail elsewhere
                continue
        return table

    def test_no_formatter_reads_an_absent_schema_field(self):
        """Every expr.<field> a formatter reads must exist on its statement."""
        table = self._table()
        offenders = []
        for path in _python_files():
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover
                continue
            source = path.read_text(encoding="utf-8")
            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef):
                    continue
                if not node.name.startswith("format_"):
                    continue
                segment = ast.get_source_segment(source, node) or ""
                if "expr.schema_name" not in segment:
                    continue
                import re

                for cls in set(re.findall(r"\b(\w+Expression)\b", segment)):
                    if cls not in table:
                        continue
                    if _has_field(cls, "schema_name", table):
                        continue
                    if cls in KNOWN_ALIASES.get("schema", set()):
                        continue
                    offenders.append(
                        f"{path.relative_to(REPO_ROOT)}:{node.lineno} "
                        f"{node.name} -> {cls}"
                    )
        assert not offenders, (
            "These formatters read expr.schema_name but the statement has no "
            "such field, so building that statement raises AttributeError "
            "rather than producing SQL. Give the expression the field, or read "
            "the one it actually has:\n  " + "\n  ".join(offenders)
        )
