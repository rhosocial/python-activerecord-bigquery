# tests/providers/registry.py
"""
Test Provider Registry (BigQuery backend).

Registers concrete implementations of the testsuite provider interfaces so
the backend-agnostic testsuite can run against the BigQuery emulator.

Mirrors the registration scheme of the MySQL backend
(``python-activerecord-mysql/tests/providers/registry.py``). The basic,
relation and query feature groups are implemented for now; testsuite groups
that require unregistered provider keys are skipped by the testsuite itself.
"""

from rhosocial.activerecord.testsuite.core.registry import ProviderRegistry

from .basic import BasicAsyncProvider, BasicSyncProvider
from .query import QueryAsyncProvider, QuerySyncProvider
from .relation import RelationAsyncProvider, RelationSyncProvider

# Create a single, global instance of the ProviderRegistry.
provider_registry = ProviderRegistry()

# Register the concrete `BasicSyncProvider` and `BasicAsyncProvider` as the
# implementations for the basic feature interfaces defined in the testsuite.
# When the testsuite needs to run a "basic" feature test, it will ask the
# registry for "feature.basic.IBasicSyncProvider" or
# "feature.basic.IBasicAsyncProvider".
provider_registry.register("feature.basic.IBasicProvider", BasicSyncProvider)
provider_registry.register("feature.basic.IBasicSyncProvider", BasicSyncProvider)
provider_registry.register("feature.basic.IBasicAsyncProvider", BasicAsyncProvider)

# Register the concrete `RelationSyncProvider` and `RelationAsyncProvider` as
# the implementations for the relation feature interfaces.
provider_registry.register("feature.relation.IRelationProvider", RelationSyncProvider)
provider_registry.register("feature.relation.IRelationSyncProvider", RelationSyncProvider)
provider_registry.register("feature.relation.IRelationAsyncProvider", RelationAsyncProvider)

# Register the concrete `QuerySyncProvider` and `QueryAsyncProvider` as the
# implementations for the query feature interfaces.
provider_registry.register("feature.query.IQueryProvider", QuerySyncProvider)
provider_registry.register("feature.query.IQuerySyncProvider", QuerySyncProvider)
provider_registry.register("feature.query.IQueryAsyncProvider", QueryAsyncProvider)
