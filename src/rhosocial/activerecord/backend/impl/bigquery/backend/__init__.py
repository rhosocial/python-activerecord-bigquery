# src/rhosocial/activerecord/backend/impl/bigquery/backend/__init__.py
"""Bigquery backend implementations.

Every backend keeps both classes in this package: the sync class in
``backend.py`` and the async class in ``async_backend.py``. So the sync class
is at ``impl.bigquery.backend.backend`` and the async class at
``impl.bigquery.backend.async_backend``.
"""

from .backend import BigQueryBackend
