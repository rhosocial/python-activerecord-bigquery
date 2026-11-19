# tests/rhosocial/activerecord_bigquery_test/feature/query/column_helpers.py
"""Test-side helpers for the column-class selection path, and its canonical list.

The production path is ``base/field_proxy.py``: ``Model.c.<field>`` asks the
model for the field's column-type declaration (dialect-free), then
``FieldAccessor`` selects the class the model's backend answers. This module
mirrors that selection step for a bare annotation, so a test can build a column
without declaring a model.

``COMMON_TYPES`` is the test-side name for the framework-modelled Python types
every backend must answer for. The list itself now lives in the framework
(``base/framework_types.FRAMEWORK_PYTHON_TYPES``) because two dialect tables --
the column-class table and the suggested storage-type table -- are keyed by it,
and stating it twice is how the two would drift. The tests hold each backend to
the framework's list, not to a second copy of it.

Deliberately **not** a fallback: an annotation the selection cannot classify
raises :class:`ColumnTypeResolutionError` exactly as ``Model.c.<field>``
would, so a test that builds a column from a bad annotation fails here for the
same reason the model would, and the two cannot drift apart.
"""

from typing import Any, Optional, Tuple, Type

from rhosocial.activerecord.backend.expression.column_types import ColumnBase
from rhosocial.activerecord.backend.expression.core import Column
from rhosocial.activerecord.base.framework_types import FRAMEWORK_PYTHON_TYPES
from rhosocial.activerecord.base.field_proxy import (
    ColumnTypeResolutionError,
    FieldAccessor,
)

#: The framework-modelled Python types, in declared reading order. The order
#: matters where a subclass walk meets an ambiguous annotation: ``bool`` ahead
#: of ``int``, and ``enum.Enum`` tested before the walk (a ``(int, Enum)`` stays
#: an enum). The list lives in the framework because both dialect tables are
#: keyed by it; this name is the test-side alias.
COMMON_TYPES: Tuple[Any, ...] = FRAMEWORK_PYTHON_TYPES


def resolve_column_class(dialect: Any, annotation: Any, declared: Any = None) -> Type[ColumnBase]:
    """The class *dialect* selects for *annotation*.

    The field accessor's own selection step, invoked without a model. *declared*
    is the field's column-type declaration when a test exercises one; ``None``
    asks the backend's tables.
    """
    return FieldAccessor._select_column_class(dialect, annotation, declared)


def build_column(
    dialect: Any,
    column_name: str,
    annotation: Any,
    table: Optional[str] = None,
    schema_name: Optional[str] = None,
    column_type: Any = None,
) -> ColumnBase:
    """Build the column expression *dialect* selects for *annotation*.

    Args:
        dialect: The dialect to select through. Selection is per-backend by
            design, so a test that wants a specific column class must say which
            backend's answer it is asking for.
        column_name: The SQL name to render.
        annotation: The Python annotation, ``Annotated`` / ``Optional`` included.
        table: Optional table qualifier.
        schema_name: Optional schema qualifier.
        column_type: A ``UseColumnType`` when the test is exercising an explicit
            declaration; ``None`` asks the backend's tables.

    Returns:
        The constructed column expression.

    Raises:
        ColumnTypeResolutionError: The backend's tables have no column class for
            *annotation*, or answered ``None`` for its entry.
    """
    column_class = resolve_column_class(dialect, annotation, column_type)
    if column_class is Column:
        # The untyped column keeps its own narrower constructor and can only
        # arrive by being declared explicitly, so this is a shape difference
        # rather than a fallback.
        return Column(dialect, column_name, table=table, schema_name=schema_name)
    return column_class(dialect, column_name, table=table, schema_name=schema_name)


__all__ = [
    "COMMON_TYPES",
    "ColumnTypeResolutionError",
    "build_column",
    "resolve_column_class",
]
