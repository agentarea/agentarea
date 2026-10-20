"""GitHub import: a tree URL into a monorepo imports only that package.

Without a token the repository comes from its archive endpoint, not the REST API.

A direct import is an install from the unvetted public source (ADR-0044): the
install policy decides it as the ``registry:github`` pseudo-registry of trust
``community`` before anything is downloaded.
"""

import io
import zipfile
from unittest.mock import MagicMock, patch

import httpx
import pytest

from agentarea_agents.application.skill_service import SkillService
from agentarea_agents.domain.skill_models import SkillSourceType
from agentarea_agents.infrastructure.skill_storage_service import SkillStorageService
from agentarea_agents.schemas.skills_dto import SkillImportFromGithub
from agentarea_common.auth.context import UserContext
from agentarea_common.base.models import BaseModel
from agentarea_governance.application.catalog_install import CatalogInstallRefusedError
from agentarea_governance.domain.rules import PolicyEffect, PolicyRule, PolicySubjectType
from agentarea_governance.infrastructure.orm import PolicyRuleORM
from agentarea_governance.infrastructure.repository import PolicyRuleRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .test_catalog_skills import AllowInstalls, FakeFactory, FakeSkillRepo

CALLER = UserContext(user_id="u1", workspace_id="w1")
URL = "https://github.com/coreyhaines31/marketingskills/tree/main/skills/seo-audit"

SKILL_MD = "---\nname: seo-audit\ndescription: Audit a site for SEO\n---\n# SEO audit\n"
ZIPBALL_URL = "https://codeload.github.com/coreyhaines31/marketingskills/zip/main"


def _repo_zipball() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("coreyhaines31-marketingskills-abc123/README.md", "# Marketing skills")
        zf.writestr("coreyhaines31-marketingskills-abc123/skills/seo-audit/SKILL.md", SKILL_MD)
        zf.writestr(
            "coreyhaines31-marketingskills-abc123/skills/seo-audit/references/x.md", "# Ref"
        )
        zf.writestr(
            "coreyhaines31-marketingskills-abc123/skills/copywriting/SKILL.md",
            "---\nname: copywriting\n---\n",
        )
    return buffer.getvalue()


@pytest.fixture
def github_serves_zipball(monkeypatch):
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, content=_repo_zipball())

    def client(_destination, **kwargs):
        kwargs.pop("transport", None)
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(
        "agentarea_agents.infrastructure.github_skill_importer.outbound_client", client
    )
    return requested


@pytest.fixture
def s3_client():
    client = MagicMock()
    settings = MagicMock()
    settings.ARTIFACTS_BUCKET_NAME = "test-bucket"
    with (
        patch(
            "agentarea_agents.infrastructure.skill_storage_service.get_s3_client",
            return_value=client,
        ),
        patch(
            "agentarea_agents.infrastructure.skill_storage_service.get_aws_settings",
            return_value=settings,
        ),
    ):
        yield client


def _service(policy_session: AsyncSession | None = None) -> SkillService:
    repo = FakeSkillRepo()
    factory = FakeFactory(repo, CALLER)
    if policy_session is not None:
        factory.session = policy_session
    svc = SkillService(
        factory,
        CALLER,
        storage_service=SkillStorageService(),
        install_guard=None if policy_session is not None else AllowInstalls(),
    )
    svc._get_repository = lambda: repo
    return svc


@pytest.fixture
async def policy_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: BaseModel.metadata.create_all(c, tables=[PolicyRuleORM.__table__])
        )
    async with async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)() as s:
        yield s
    await engine.dispose()


async def _workspace_rule(session: AsyncSession, target: str, effect: PolicyEffect) -> None:
    await PolicyRuleRepository(session, CALLER).create(
        PolicyRule(
            subject_type=PolicySubjectType.WORKSPACE,
            subject_id=CALLER.workspace_id,
            target=target,
            effect=effect,
        )
    )
    await session.commit()


def _stored_paths(s3_client: MagicMock, s3_path: str) -> set[str]:
    prefix = s3_path
    assert prefix.startswith("skills/w1/packages/")
    keys = {call.kwargs["Key"] for call in s3_client.put_object.call_args_list}
    assert all(key.startswith(prefix) for key in keys)
    return {key[len(prefix) :] for key in keys}


@pytest.mark.parametrize(
    "github_url",
    [
        "https://github.com/coreyhaines31/marketingskills/tree/main/skills/seo-audit",
        "https://github.com/coreyhaines31/marketingskills/blob/main/skills/seo-audit/SKILL.md",
    ],
    ids=["tree-url-to-the-package", "blob-url-to-its-skill-md"],
)
async def test_a_github_url_into_a_monorepo_imports_only_that_skill_package(
    github_url, github_serves_zipball, s3_client
):
    skill = await _service().create_from_github(SkillImportFromGithub(github_url=github_url))

    assert github_serves_zipball == [ZIPBALL_URL]
    assert _stored_paths(s3_client, skill.s3_path) == {"SKILL.md", "references/x.md"}
    assert skill.name == "seo-audit"
    assert skill.content is None  # the body is the stored SKILL.md
    assert skill.source_type == SkillSourceType.GITHUB.value
    assert skill.source_url == github_url


async def test_a_github_url_to_a_missing_path_names_the_path(github_serves_zipball, s3_client):
    with pytest.raises(ValueError, match="skills/nope"):
        await _service().create_from_github(
            SkillImportFromGithub(
                github_url="https://github.com/coreyhaines31/marketingskills/tree/main/skills/nope"
            )
        )

    s3_client.put_object.assert_not_called()


@pytest.mark.parametrize(
    ("target", "effect"),
    [
        ("registry_trust:community", PolicyEffect.DENY),
        ("registry:github", PolicyEffect.DENY),
        # an allowlist of registries that does not name GitHub
        ("registry:0b6f8c1e-2a4d-4f7e-9a51-6d2c3b4a5e6f", PolicyEffect.ALLOW),
    ],
    ids=["deny-community", "deny-github", "allowlist-without-github"],
)
async def test_an_install_policy_that_excludes_github_refuses_the_import_before_downloading(
    target, effect, policy_session, github_serves_zipball, s3_client
):
    await _workspace_rule(policy_session, target, effect)

    with pytest.raises(CatalogInstallRefusedError):
        await _service(policy_session).create_from_github(SkillImportFromGithub(github_url=URL))

    assert github_serves_zipball == []
    s3_client.put_object.assert_not_called()


@pytest.mark.parametrize(
    ("target", "effect"),
    [
        ("registry_trust:official", PolicyEffect.DENY),
        ("registry:github", PolicyEffect.ALLOW),
        ("registry_trust:community", PolicyEffect.ALLOW),
    ],
    ids=["deny-other-trust", "allowlist-names-github", "allowlist-names-community"],
)
async def test_an_install_policy_that_admits_github_lets_the_import_through(
    target, effect, policy_session, github_serves_zipball, s3_client
):
    await _workspace_rule(policy_session, target, effect)

    skill = await _service(policy_session).create_from_github(SkillImportFromGithub(github_url=URL))

    assert skill.name == "seo-audit"
    assert github_serves_zipball == [ZIPBALL_URL]
