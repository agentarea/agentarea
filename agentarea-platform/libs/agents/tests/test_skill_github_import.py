"""GitHub import over REST: a tree URL into a monorepo imports only that package."""

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

from .test_catalog_skills import FakeFactory, FakeSkillRepo

SKILL_MD = "---\nname: seo-audit\ndescription: Audit a site for SEO\n---\n# SEO audit\n"
ZIPBALL_URL = "https://api.github.com/repos/coreyhaines31/marketingskills/zipball/main"


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

    def client(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(
        "agentarea_agents.infrastructure.github_skill_importer.safe_async_client", client
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


def _service() -> SkillService:
    repo = FakeSkillRepo()
    uc = UserContext(user_id="u1", workspace_id="w1")
    svc = SkillService(FakeFactory(repo, uc), uc, storage_service=SkillStorageService())
    svc._get_repository = lambda: repo
    return svc


def _stored_paths(s3_client: MagicMock, skill_id: str) -> set[str]:
    prefix = SkillStorageService()._get_s3_prefix("w1", skill_id)
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
    assert _stored_paths(s3_client, str(skill.id)) == {"SKILL.md", "references/x.md"}
    assert skill.name == "seo-audit"
    assert skill.content == SKILL_MD
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
