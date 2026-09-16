"""How a platform-supplied provider and model get their database ids.

These are not an internal detail. A platform model's instance id is what an agent
stores when it selects the model, and what billing meters against — rate cards are
keyed on it, and those rows live in a different service with its own database,
written by hand. A random id would have to be read out of this database and copied
into that one per environment, after every fresh install.

Derived from (provider_key, model_name) instead, so the same model has the same id
in staging, in production, and in a database created this morning. Rate cards can
name it in a migration, and the writer converges rather than accumulating even
against an empty database.

The writer is ``agentarea-operator``, which reconciles ``LLMProviderConfig`` custom
resources into rows; it keeps its own copy of this recipe for the same reason it
keeps its own copy of the platform identities, and the pinned test beside this
module is what keeps the two from drifting.

Freeze both the namespace and the name format. Changing either stays deterministic
and still produces stable ids — just different ones, matching no rate card, with
models running on our provider credit and charging nobody. Nothing would error.
"""

from __future__ import annotations

from uuid import UUID, uuid5

# A fixed, arbitrary UUID; its only job is to keep these names from colliding with
# anything else's uuid5 in the same table.
PLATFORM_ID_NAMESPACE = UUID("8f3d4b2a-6c1e-5a7f-9d0b-2e4a6c8f1d3b")


def platform_config_id(provider_key: str) -> UUID:
    """The id of the provider configuration the deployment supplies keys for."""
    return uuid5(PLATFORM_ID_NAMESPACE, f"provider_config:{provider_key}")


def platform_instance_id(provider_key: str, model_name: str) -> UUID:
    """The id of one offered model. This is the value billing's rate cards name."""
    return uuid5(PLATFORM_ID_NAMESPACE, f"model_instance:{provider_key}:{model_name}")
