# src/rhosocial/activerecord/backend/impl/bigquery/expression/objects/__init__.py
"""Expression namespace: objects.

Every public name from the modules in this namespace is re-exported so
callers can keep importing it from this package. Each name and its defining
module are declared below; the module is imported only when that name is first
asked for.
"""

import importlib

_EXPORTS = {
    "BigQueryPartitionDecoratedTable": "table",
}
__all__ = tuple(_EXPORTS)


def __getattr__(name):
    """Resolve a public name from this namespace lazily (no import cycles)."""
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return vars(importlib.import_module(f".{module_name}", __name__))[name]
