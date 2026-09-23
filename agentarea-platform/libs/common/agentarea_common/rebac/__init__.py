"""ReBAC relationship-tuple clients and models.

Low-level access to Zanzibar-style read/write APIs that back the access
explorer. Higher-level orchestration (graph assembly, tuple sync) lives in the
API app.
"""

from .keto_client import KetoClient, KetoError, KetoUnavailableError
from .models import (
    CheckResult,
    ExpandNode,
    RelationQuery,
    RelationTuple,
    SubjectSet,
)
from .openfga_bootstrap import bootstrap_openfga
from .openfga_client import OpenFGAClient, OpenFGAError, OpenFGAUnavailableError
from .ownership import (
    OWNER_RELATIONS,
    ResourceOwnershipError,
    grant_resource_owner,
    resolve_graph_client,
    root_project_id,
    write_tuple_idempotent,
)

__all__ = [
    "OWNER_RELATIONS",
    "CheckResult",
    "ExpandNode",
    "KetoClient",
    "KetoError",
    "KetoUnavailableError",
    "OpenFGAClient",
    "OpenFGAError",
    "OpenFGAUnavailableError",
    "RelationQuery",
    "RelationTuple",
    "ResourceOwnershipError",
    "SubjectSet",
    "bootstrap_openfga",
    "grant_resource_owner",
    "resolve_graph_client",
    "root_project_id",
    "write_tuple_idempotent",
]
