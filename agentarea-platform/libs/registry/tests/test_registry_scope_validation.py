"""What a registry may be, by scope (ADR-0044).

A workspace admin adds a registry for their workspace only: a skills or agents
index, or a GitHub repository of skills, labelled private or community, read
upstream or mirrored. Anything the platform could not sync, or that would let a workspace
write platform-wide entities or claim the platform's trust, is refused.
"""

import pytest
from agentarea_registry.application.service import validate_registry_source

WORKSPACE = {"scope": "workspace", "workspace_id": "ws-1", "mode": "upstream", "trust": "private"}
PLATFORM = {"scope": "platform", "workspace_id": None, "mode": "mirror", "trust": "official"}


def _check(registry_type="skills", source_type="url", source_url="https://x/i.json", **fields):
    validate_registry_source(
        registry_type=registry_type, source_type=source_type, source_url=source_url, **fields
    )


@pytest.mark.parametrize(
    ("registry_type", "source_type", "source_url"),
    [
        ("skills", "url", "https://x/skills.json"),
        ("agents", "url", "https://x/agents.json"),
        ("skills", "github", "acme/skills"),
    ],
)
def test_a_workspace_may_add_a_skill_or_agent_source(registry_type, source_type, source_url):
    _check(registry_type, source_type, source_url, **WORKSPACE)


@pytest.mark.parametrize("registry_type", ["mcp_servers", "llm_providers", "llm_models", "bundles"])
def test_a_workspace_registry_holds_no_type_that_writes_platform_entities(registry_type):
    with pytest.raises(ValueError, match="workspace registry holds"):
        _check(registry_type, **WORKSPACE)


@pytest.mark.parametrize("trust", ["official", "verified"])
def test_a_workspace_cannot_claim_the_platforms_trust(trust):
    with pytest.raises(ValueError, match="trust"):
        _check(**{**WORKSPACE, "trust": trust})


@pytest.mark.parametrize("source_type", ["url", "github"])
def test_a_workspace_registry_may_mirror_its_content(source_type):
    source_url = "acme/skills" if source_type == "github" else "https://x/skills.json"
    _check(source_type=source_type, source_url=source_url, **{**WORKSPACE, "mode": "mirror"})


def test_a_workspace_registry_needs_its_workspace():
    with pytest.raises(ValueError, match="needs its workspace"):
        _check(**{**WORKSPACE, "workspace_id": None})


def test_a_platform_registry_names_no_workspace():
    with pytest.raises(ValueError, match="no workspace"):
        _check(**{**PLATFORM, "workspace_id": "ws-1"})


@pytest.mark.parametrize("source_url", ["https://github.com/acme/skills", "acme", "a/b/c"])
def test_a_github_source_is_owner_slash_repo(source_url):
    with pytest.raises(ValueError, match="owner/repo"):
        _check(source_type="github", source_url=source_url, **PLATFORM)


def test_a_github_source_holds_skills():
    with pytest.raises(ValueError, match="holds skills"):
        _check("agents", "github", "acme/agents", **PLATFORM)


@pytest.mark.parametrize(
    ("field", "value"), [("scope", "org"), ("mode", "copy"), ("trust", "famous")]
)
def test_unknown_values_are_refused(field, value):
    with pytest.raises(ValueError, match=field):
        _check(**{**PLATFORM, field: value})


@pytest.mark.parametrize("fields", [WORKSPACE, {**PLATFORM, "mode": "upstream"}])
def test_a_skills_source_read_with_credentials_is_mirrored(fields):
    with pytest.raises(ValueError, match="credentials"):
        _check(credentials=True, **fields)
    _check(credentials=True, **{**fields, "mode": "mirror"})
    _check("agents", credentials=True, **fields)
