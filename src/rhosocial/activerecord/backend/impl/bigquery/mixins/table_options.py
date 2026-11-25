# src/rhosocial/activerecord/backend/impl/bigquery/mixins/table_options.py
"""BigQuery ``ALTER TABLE`` option formatters.

This mixin owns every decision the two option statements make: which option
names exist, which value shapes each accepts, which capability answers reach a
caller, and which requests are refused. The nodes in ``..expression.table_options``
only collect parameters, so nothing here has to discover a half-built SQL
fragment or a value that was silently quoted somewhere else.

Reference (fetched 2026-11-25):
https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language#alter_table_set_options_statement
"""
import math
from typing import Any, List, Tuple, TYPE_CHECKING

from rhosocial.activerecord.backend.dialect.exceptions import UnsupportedFeatureError
from rhosocial.activerecord.backend.expression.objects import Table

from ..table_option_catalog import (
    BigQueryTableOption,
    BigQueryTableOptionValueKind,
    DEFAULT_ROUNDING_MODES,
    FILE_FORMATS,
    INTERVAL_PARTS,
    TABLE_FORMATS,
    resolve_table_option,
)

if TYPE_CHECKING:  # pragma: no cover
    from ..expression.table_options import (
        BigQueryAlterTableSetOptionsStatement,
        BigQueryAlterTableUnsetOptionsStatement,
    )


class BigQueryTableOptionsMixin:
    """Formatters and capability answers for BigQuery table options."""

    def supports_alter_table_options(self) -> bool:
        """Whether a table's options can be changed with ``ALTER TABLE``.

        ``True``: the official DDL reference documents
        ``ALTER TABLE [ IF EXISTS ] table_name SET OPTIONS (...)`` together
        with a closed ``table_set_options_list``. The statement is not
        supported for external tables, which is a property of the target, not
        of this capability answer.

        Evidence (fetched 2026-11-25):
        https://cloud.google.com/bigquery/docs/reference/standard-sql/data-definition-language#alter_table_set_options_statement
        """
        return True

    def supports_alter_table_unset_options(self) -> bool:
        """Whether ``ALTER TABLE ... UNSET OPTIONS(...)`` is available.

        ``True`` records the server syntax supplied with the migration task.
        Evidence level: **unverified**. The official DDL reference fetched
        2026-11-25 has no ``UNSET OPTIONS`` production for a table (or for any
        other object) and documents clearing an option as
        ``SET OPTIONS(option_name = NULL)``. The answer is kept here so the
        capability surface says the same thing as the node the task asked for;
        the gap is written out rather than presented as verified support.
        """
        return True

    # ------------------------------------------------------------------
    # ALTER TABLE ... SET OPTIONS
    # ------------------------------------------------------------------

    def format_bigquery_alter_table_set_options_statement(
        self, expr: "BigQueryAlterTableSetOptionsStatement"
    ) -> Tuple[str, tuple]:
        """Format ``ALTER TABLE [IF EXISTS] table_name SET OPTIONS(...)``.

        Raises:
            TypeError: ``expr.table`` is not a Table. A different object would
                render as a well-formed statement about the wrong kind of thing.
            UnsupportedFeatureError: the dialect declines table options.
            ValueError: an option name or value is outside the documented
                vocabulary, or the options are not a sequence of pairs.
        """
        if not self.supports_alter_table_options():
            raise UnsupportedFeatureError(self.name, "ALTER TABLE SET OPTIONS")
        name_sql = self._table_option_name_sql(expr)
        assignments = self._table_option_assignments(expr.options)
        parts = ["ALTER TABLE"]
        if expr.if_exists:
            parts.append("IF EXISTS")
        parts.append(name_sql)
        parts.append(f"SET OPTIONS({', '.join(assignments)})")
        return " ".join(parts), ()

    # ------------------------------------------------------------------
    # ALTER TABLE ... UNSET OPTIONS
    # ------------------------------------------------------------------

    def format_bigquery_alter_table_unset_options_statement(
        self, expr: "BigQueryAlterTableUnsetOptionsStatement"
    ) -> Tuple[str, tuple]:
        """Format ``ALTER TABLE [IF EXISTS] table_name UNSET OPTIONS(...)``.

        Raises:
            TypeError: ``expr.table`` is not a Table.
            UnsupportedFeatureError: the dialect declines the statement.
            ValueError: a name is not a documented table option, the list is
                empty, or it is not a sequence of names.
        """
        if not self.supports_alter_table_unset_options():
            raise UnsupportedFeatureError(self.name, "ALTER TABLE UNSET OPTIONS")
        name_sql = self._table_option_name_sql(expr)
        names = self._table_option_names(expr.option_names)
        parts = ["ALTER TABLE"]
        if expr.if_exists:
            parts.append("IF EXISTS")
        parts.append(name_sql)
        parts.append(f"UNSET OPTIONS({', '.join(names)})")
        return " ".join(parts), ()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _table_option_name_sql(expr: Any) -> str:
        """The one place a statement's table becomes SQL, checked by kind."""
        if not isinstance(expr.table, Table):
            raise TypeError(
                f"{type(expr).__name__}.table must be a Table, "
                f"got {type(expr.table).__name__}"
            )
        name_sql, _params = expr.table.to_sql()
        return name_sql

    def _table_option_assignments(self, options: Any) -> List[str]:
        """Validate every option and render it as ``name = literal``.

        A ``None`` value renders as ``NULL``, which the reference documents as
        the way to clear an option. Everything else must be a JSON scalar or
        one of the two documented compound shapes; an expression node, a dict
        or an arbitrary nested container is refused rather than stringified.
        """
        if isinstance(options, (str, bytes, dict)) or not isinstance(options, (list, tuple)):
            raise ValueError(
                "options must be a sequence of (name, value) pairs; DDL cannot "
                "carry bind parameters or a nested options object"
            )
        if not options:
            raise ValueError("SET OPTIONS requires at least one table option")

        assignments = []
        seen = set()
        for position, pair in enumerate(options):
            if (
                isinstance(pair, (str, bytes))
                or not isinstance(pair, (list, tuple))
                or len(pair) != 2
            ):
                raise ValueError(
                    f"options[{position}] must be a (name, value) pair, got {pair!r}"
                )
            name, value = pair
            option = resolve_table_option(name)
            if option is None:
                valid = ", ".join(item.value for item in BigQueryTableOption)
                raise ValueError(
                    f"options[{position}] names a table option BigQuery does not "
                    f"document: {name!r}. Valid options: {valid}"
                )
            if option in seen:
                raise ValueError(f"options repeats the table option {option.value!r}")
            seen.add(option)
            assignments.append(
                f"{option.value} = {self._table_option_value(option, value, position)}"
            )
        return assignments

    def _table_option_value(self, option: BigQueryTableOption, value: Any, position: int) -> str:
        """Render one documented value shape as an inline literal."""
        if value is None:
            return "NULL"
        kind = option.value_kind
        label = f"options[{position}] ({option.value})"

        if kind is BigQueryTableOptionValueKind.STRING:
            if not isinstance(value, str):
                raise ValueError(f"{label} needs a string value, got {type(value).__name__}")
            allowed = {
                BigQueryTableOption.DEFAULT_ROUNDING_MODE: DEFAULT_ROUNDING_MODES,
                BigQueryTableOption.FILE_FORMAT: FILE_FORMATS,
                BigQueryTableOption.TABLE_FORMAT: TABLE_FORMATS,
            }.get(option)
            if allowed is not None and value not in allowed:
                raise ValueError(
                    f"{label} has value {value!r}; BigQuery documents only "
                    f"{', '.join(sorted(allowed))}"
                )
            if not value.strip():
                raise ValueError(f"{label} must not be an empty string")
            return f"'{self.escape_sql_string(value)}'"

        if kind is BigQueryTableOptionValueKind.BOOLEAN:
            if type(value) is not bool:
                raise ValueError(f"{label} needs a bool value, got {type(value).__name__}")
            return "true" if value else "false"

        if kind is BigQueryTableOptionValueKind.NUMBER:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(
                    f"{label} needs an int or float value, got {type(value).__name__}"
                )
            if not math.isfinite(value):
                raise ValueError(f"{label} needs a finite number, got {value!r}")
            return str(value)

        if kind is BigQueryTableOptionValueKind.TIMESTAMP:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"{label} needs a non-empty timestamp string, got {value!r}"
                )
            return f"TIMESTAMP '{self.escape_sql_string(value)}'"

        if kind is BigQueryTableOptionValueKind.INTERVAL:
            if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
                raise ValueError(
                    f"{label} needs an (amount, qualifier) pair, got {value!r}"
                )
            if len(value) != 2 or not all(isinstance(part, str) for part in value):
                raise ValueError(
                    f"{label} needs an (amount, qualifier) pair of strings, got {value!r}"
                )
            amount, qualifier = value
            if not amount.strip():
                raise ValueError(f"{label} needs a non-empty interval amount")
            self._validate_interval_qualifier(qualifier, label)
            return f"INTERVAL '{self.escape_sql_string(amount)}' {qualifier}"

        if kind is BigQueryTableOptionValueKind.LABEL_ARRAY:
            if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
                raise ValueError(
                    f"{label} needs a sequence of (key, value) string pairs, got {value!r}"
                )
            pairs = []
            for index, pair in enumerate(value):
                if (
                    isinstance(pair, (str, bytes))
                    or not isinstance(pair, (list, tuple))
                    or len(pair) != 2
                    or not all(isinstance(item, str) for item in pair)
                ):
                    raise ValueError(
                        f"{label} item {index} must be a (key, value) pair of "
                        f"strings, got {pair!r}"
                    )
                key, item = pair
                pairs.append(
                    f"('{self.escape_sql_string(key)}', '{self.escape_sql_string(item)}')"
                )
            return f"[{', '.join(pairs)}]"

        raise ValueError(f"{label} has no documented value shape")

    @staticmethod
    def _validate_interval_qualifier(qualifier: str, label: str) -> None:
        """Accept only BigQuery date/time part names in an INTERVAL qualifier."""
        parts = qualifier.split(" TO ")
        if not parts or any(part not in INTERVAL_PARTS for part in parts):
            raise ValueError(
                f"{label} has interval qualifier {qualifier!r}; BigQuery documents "
                f"date/time parts from {', '.join(sorted(INTERVAL_PARTS))}"
            )

    @staticmethod
    def _table_option_names(names: Any) -> List[str]:
        """Validate the ``UNSET OPTIONS`` name list and return its spellings."""
        if isinstance(names, (str, bytes)) or not isinstance(names, (list, tuple)):
            raise ValueError("option_names must be a sequence of documented option names")
        if not names:
            raise ValueError("UNSET OPTIONS requires at least one option name")
        result = []
        seen = set()
        for position, name in enumerate(names):
            option = resolve_table_option(name)
            if option is None:
                valid = ", ".join(item.value for item in BigQueryTableOption)
                raise ValueError(
                    f"option_names[{position}] names a table option BigQuery does "
                    f"not document: {name!r}. Valid options: {valid}"
                )
            if option in seen:
                raise ValueError(f"option_names repeats the table option {option.value!r}")
            seen.add(option)
            result.append(option.value)
        return result


__all__ = ["BigQueryTableOptionsMixin"]
