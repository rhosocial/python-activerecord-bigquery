# tests/rhosocial/activerecord_bigquery_test/feature/query/basic/test_placeholder_conversion.py
"""Unit tests for convert_qmark_placeholder utility function."""

import pytest
from unittest.mock import MagicMock

from rhosocial.activerecord.query.utils import convert_qmark_placeholder


@pytest.fixture
def sqlite_dialect():
    """Create a mock SQLite dialect that uses '?' as placeholder."""
    dialect = MagicMock()
    dialect.get_parameter_placeholder.return_value = "?"
    return dialect


@pytest.fixture
def mysql_dialect():
    """Create a mock MySQL dialect that uses '%s' as placeholder."""
    dialect = MagicMock()
    dialect.get_parameter_placeholder.return_value = "%s"
    return dialect


@pytest.fixture
def postgres_dialect():
    """Create a mock PostgreSQL dialect that uses '%s' as placeholder."""
    dialect = MagicMock()
    dialect.get_parameter_placeholder.return_value = "%s"
    return dialect


class TestSQLiteDialect:
    """Tests for SQLite dialect ('?' placeholder — no conversion needed)."""

    def test_no_conversion_needed(self, sqlite_dialect):
        """SQLite uses '?' natively, so '?' should remain unchanged."""
        sql = "SELECT * FROM users WHERE name = ? AND age > ?"
        assert convert_qmark_placeholder(sqlite_dialect, sql) == sql

    def test_escape_reduces_to_literal(self, sqlite_dialect):
        """Escaped \\? should be reduced to literal ? for SQLite."""
        sql = r"col \? 'key'"
        assert convert_qmark_placeholder(sqlite_dialect, sql) == "col ? 'key'"

    def test_double_backslash_reduces_to_single(self, sqlite_dialect):
        """Escaped \\\\ should be reduced to literal \\ for SQLite."""
        sql = r"path \\?"
        assert convert_qmark_placeholder(sqlite_dialect, sql) == "path \\?"

    def test_no_placeholders(self, sqlite_dialect):
        """SQL without placeholders should pass through unchanged."""
        sql = "SELECT * FROM users"
        assert convert_qmark_placeholder(sqlite_dialect, sql) == sql


class TestMySQLDialect:
    """Tests for MySQL dialect ('%s' placeholder)."""

    def test_single_placeholder(self, mysql_dialect):
        """Single '?' should be converted to '%s'."""
        sql = "SELECT * FROM users WHERE name = ?"
        assert convert_qmark_placeholder(mysql_dialect, sql) == "SELECT * FROM users WHERE name = %s"

    def test_multiple_placeholders(self, mysql_dialect):
        """Multiple '?' should all be converted to '%s'."""
        sql = "SELECT * FROM users WHERE name = ? AND age > ?"
        expected = "SELECT * FROM users WHERE name = %s AND age > %s"
        assert convert_qmark_placeholder(mysql_dialect, sql) == expected

    def test_no_placeholders(self, mysql_dialect):
        """SQL without placeholders should pass through unchanged."""
        sql = "SELECT * FROM users"
        assert convert_qmark_placeholder(mysql_dialect, sql) == sql

    def test_escape_produces_literal_qmark(self, mysql_dialect):
        """Escaped \\? should produce literal ? (not %s)."""
        sql = r"col \? 'key'"
        assert convert_qmark_placeholder(mysql_dialect, sql) == "col ? 'key'"


class TestPostgreSQLDialect:
    """Tests for PostgreSQL dialect ('%s' placeholder, same as MySQL)."""

    def test_single_placeholder(self, postgres_dialect):
        """Single '?' should be converted to '%s'."""
        sql = "SELECT * FROM users WHERE name = ?"
        assert convert_qmark_placeholder(postgres_dialect, sql) == "SELECT * FROM users WHERE name = %s"

    def test_multiple_placeholders(self, postgres_dialect):
        """Multiple '?' should all be converted to '%s'."""
        sql = "INSERT INTO users (name, age) VALUES (?, ?)"
        expected = "INSERT INTO users (name, age) VALUES (%s, %s)"
        assert convert_qmark_placeholder(postgres_dialect, sql) == expected

    def test_escape_hstore_operator(self, postgres_dialect):
        """Escaped \\? should produce literal ? for PostgreSQL hstore/jsonb operators."""
        sql = r"hstore_col \? 'key'"
        assert convert_qmark_placeholder(postgres_dialect, sql) == "hstore_col ? 'key'"

    def test_escape_pipe_operator(self, postgres_dialect):
        """Escaped \\? before | should preserve ?| operator."""
        sql = r"hstore_col \?| array['x']"
        assert convert_qmark_placeholder(postgres_dialect, sql) == "hstore_col ?| array['x']"

    def test_escape_ampersand_operator(self, postgres_dialect):
        """Escaped \\? before & should preserve ?& operator."""
        sql = r"hstore_col \?& array['x', 'y']"
        assert convert_qmark_placeholder(postgres_dialect, sql) == "hstore_col ?& array['x', 'y']"

    def test_mixed_placeholders_and_operators(self, postgres_dialect):
        """Mix of placeholders and escaped operators should convert correctly."""
        sql = r"SELECT * FROM t WHERE a = ? AND h \?| array['x']"
        expected = "SELECT * FROM t WHERE a = %s AND h ?| array['x']"
        assert convert_qmark_placeholder(postgres_dialect, sql) == expected

    def test_unescaped_qmark_pipe_is_converted(self, postgres_dialect):
        """Unescaped ?| should have ? converted to %s (no special handling)."""
        sql = "hstore_col ?| array['x']"
        # ? is converted to %s, | stays
        assert convert_qmark_placeholder(postgres_dialect, sql) == "hstore_col %s| array['x']"


class TestEdgeCases:
    """Edge case tests."""

    def test_empty_string(self, mysql_dialect):
        """Empty string should return empty string."""
        assert convert_qmark_placeholder(mysql_dialect, "") == ""

    def test_only_placeholder(self, mysql_dialect):
        """String with only '?' should become '%s'."""
        assert convert_qmark_placeholder(mysql_dialect, "?") == "%s"

    def test_only_escaped(self, mysql_dialect):
        """String with only '\\?' should become '?'."""
        assert convert_qmark_placeholder(mysql_dialect, "\\?") == "?"

    def test_consecutive_placeholders(self, mysql_dialect):
        """Consecutive '?' should all be converted."""
        assert convert_qmark_placeholder(mysql_dialect, "??") == "%s%s"

    def test_escape_at_end(self, mysql_dialect):
        """\\ at end of string without following ? should be preserved."""
        assert convert_qmark_placeholder(mysql_dialect, "test\\") == "test\\"

    def test_double_escape(self, mysql_dialect):
        """\\\\? should produce literal \\ followed by placeholder %s."""
        # In Python raw string: r"\\?" = two chars: \, ?
        # But in regular string: "\\\\?" = three chars: \, \, ?
        # The scanner sees \\ → \, then ? → %s
        result = convert_qmark_placeholder(mysql_dialect, "\\\\?")
        assert result == "\\%s"

    def test_double_backslash_then_escaped_qmark(self, mysql_dialect):
        """\\\\\\? should produce literal \\ followed by literal ?."""
        # Scanner: \\ → \, \? → ?
        result = convert_qmark_placeholder(mysql_dialect, "\\\\\\?")
        assert result == "\\?"

    def test_placeholder_in_string_literal(self, mysql_dialect):
        """The function does NOT parse SQL semantics — ? inside quotes is also converted.
        This is by design: users must escape literal ? characters."""
        sql = "SELECT * FROM t WHERE col = '?'"
        assert convert_qmark_placeholder(mysql_dialect, sql) == "SELECT * FROM t WHERE col = '%s'"
