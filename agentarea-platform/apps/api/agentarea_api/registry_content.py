"""Store a mirror-mode skills registry's content as it syncs (ADR-0044).

The registry library stores no packages itself; the sync is handed this mirror
by whoever builds the service. A platform registry's packages go to the shared
catalog area, a workspace registry's to that workspace's own, and a private
GitHub source is read with the token the registry's credentials resolve to.
"""

from agentarea_agents.application.skill_packages import CatalogMirror
from agentarea_agents.infrastructure.github_skill_importer import GitHubSkillImporter
from agentarea_agents.infrastructure.skill_storage_service import SkillStorageService
from agentarea_registry.application.service import ContentMirror, ItemContentMirror
from agentarea_registry.domain.models import Registry


def registry_content_mirror(storage: SkillStorageService | None = None) -> ContentMirror:
    store = storage or SkillStorageService()

    def open_mirror(registry: Registry, token: str | None) -> ItemContentMirror:
        return CatalogMirror(
            store,
            GitHubSkillImporter(github_token=token),
            workspace_id=registry.workspace_id if registry.scope == "workspace" else None,
        )

    return open_mirror
