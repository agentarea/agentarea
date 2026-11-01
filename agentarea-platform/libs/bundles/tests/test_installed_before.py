"""A bundle finds its own entities by the ids its last install recorded, never by name."""

from types import SimpleNamespace
from uuid import uuid4

from agentarea_bundles.application.analyzer import BundleAnalyzer, parse_bundle
from agentarea_bundles.application.service import BundleService
from agentarea_bundles.schemas.preview import EntityStatus

BUNDLE = """
schema_version: "0.1.0"
name: seo
agents: [{key: lead, name: Lead, model: gpt-4o}]
skills: [{key: sk, name: Audit, source_type: content, content: "# a"}]
automations:
  - {key: daily, type: cron, cron: "0 9 * * *", agent: lead, prompt: go}
"""


class _Repo:
    def __init__(self, *entities):
        self._by_id = {entity.id: entity for entity in entities}

    async def get(self, entity_id):
        return self._by_id.get(entity_id)

    async def list_all(self):
        return list(self._by_id.values())


def _service(install_result, *, agents=(), skills=(), triggers=()) -> BundleService:
    service = BundleService.__new__(BundleService)
    record = SimpleNamespace(install_result=install_result)

    async def get_by_name(_name):
        return record

    service._bundle_repository = SimpleNamespace(get_by_name=get_by_name)
    service._agent_repository = _Repo(*agents)
    service._skill_repository = _Repo(*skills)
    service._trigger_repository = _Repo(*triggers)
    service._mcp_instance_service = _Repo()
    return service


async def test_the_preview_counts_only_what_the_last_install_recorded():
    agent = SimpleNamespace(id=uuid4(), status="active")
    namesake_skill = SimpleNamespace(id=uuid4())
    trigger = SimpleNamespace(id=uuid4(), name="seo:daily", agent_id=agent.id)
    recorded = {
        "entities": [
            {"kind": "agent", "key": "lead", "action": "reused", "id": str(agent.id)},
            {"kind": "skill", "key": "sk", "action": "skipped", "id": str(namesake_skill.id)},
        ]
    }
    service = _service(recorded, agents=[agent], skills=[namesake_skill], triggers=[trigger])

    preview = await service.analyze_bundle(parse_bundle(BUNDLE))

    statuses = {(e.kind, e.key): e.status for e in preview.entities}
    assert statuses[("agent", "lead")] == EntityStatus.ALREADY_EXISTS
    assert statuses[("skill", "sk")] == EntityStatus.WILL_CREATE
    assert statuses[("automation", "daily")] == EntityStatus.ALREADY_EXISTS


async def test_a_trigger_under_the_bundle_name_for_another_agent_is_not_the_bundles():
    agent = SimpleNamespace(id=uuid4(), status="active")
    squatter = SimpleNamespace(id=uuid4(), name="seo:daily", agent_id=uuid4())
    recorded = {"entities": [{"kind": "agent", "key": "lead", "action": "created", "id": str(agent.id)}]}
    service = _service(recorded, agents=[agent], triggers=[squatter])

    preview = await service.analyze_bundle(parse_bundle(BUNDLE))

    statuses = {(e.kind, e.key): e.status for e in preview.entities}
    assert statuses[("automation", "daily")] == EntityStatus.WILL_CREATE


async def test_nothing_recorded_means_everything_is_created():
    preview = await _service(None).analyze_bundle(parse_bundle(BUNDLE))

    assert {e.status for e in preview.entities if e.kind != "policy"} == {EntityStatus.WILL_CREATE}
    assert preview == await BundleAnalyzer().analyze(parse_bundle(BUNDLE))
