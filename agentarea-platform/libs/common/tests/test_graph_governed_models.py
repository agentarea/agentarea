"""The set of graph-governed models is read off the models, not kept by hand.

The reconcile script and ``WorkspaceScopedRepository.create`` both ask
``graph_governed_models()``, so marking a model governs it in both places at
once. A hand-kept list in either would drift, and drift here means rows that
exist in the product and not in the graph -- which is the failure this whole
mechanism exists to prevent.
"""

from __future__ import annotations

from agentarea_agents.domain.collection_models import SkillCollection
from agentarea_agents.domain.models import Agent
from agentarea_agents.domain.skill_models import Skill
from agentarea_common.base.models import WorkspaceScopedMixin
from agentarea_common.rebac.ownership import graph_governed_models
from agentarea_mcp.domain.client_models import Client
from agentarea_mcp.domain.models import MCPServer

# `Client` relates to MCPServerInstance and Skill by name, and imports both only
# under TYPE_CHECKING, so the mapper cannot configure unless something imports
# them for real. Left out, every later test in the process fails on a poisoned
# SQLAlchemy registry, not on anything it did itself.
from agentarea_mcp.domain.mpc_server_instance_model import (
    MCPServerInstance,
)
from agentarea_openapi.domain.models import OpenAPIConnection
from agentarea_triggers.infrastructure.orm import TriggerORM


def test_the_governed_models_are_the_ones_the_pdp_knows_about() -> None:
    """Everything a user creates and owns is a ``resource:<id>`` object.

    No new graph type is needed for any of these: ``OpenFGAPermissionService``
    treats anything outside ``_UNGOVERNED_RESOURCE_TYPES`` as ``resource``, so
    marking the model is the whole registration. Projects are the exception and
    are deliberately absent -- ``project`` is its own type in ``model.fga``, with
    ``workspace``/``parent``/``role_assignment``, so a DB project belongs there
    rather than under ``resource``.
    """
    assert set(graph_governed_models()) == {
        Agent,
        Client,
        MCPServer,
        MCPServerInstance,
        OpenAPIConnection,
        Skill,
        SkillCollection,
        TriggerORM,
    }


def test_every_governed_model_carries_a_workspace_and_a_creator() -> None:
    """Ownership is granted to ``created_by`` inside ``workspace_id``."""
    for model in graph_governed_models():
        assert issubclass(model, WorkspaceScopedMixin), model.__name__
