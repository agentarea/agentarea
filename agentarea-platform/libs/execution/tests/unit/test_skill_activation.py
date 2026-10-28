"""Activating a skill writes its SKILL.md into the task log, never into workflow history (ADR-0044)."""

import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_agents.application.skill_packages import SkillPackages, clear_package_cache
from agentarea_agents.domain.skill_models import Skill
from agentarea_agents.infrastructure.github_skill_importer import (
    GitHubSourceGoneError,
    GitHubTreeMismatchError,
)
from agentarea_execution.activities import agent_execution_activities as activities
from agentarea_execution.activities.agent import files as files_module
from agentarea_execution.activities.agent.files import count_tokens
from agentarea_execution.models import ActivateSkillRequest, AgentConfigResult, SkillInfo
from agentarea_execution.workflows import agent_execution_workflow as workflow_module
from agentarea_execution.workflows.constants import Activities
from agentarea_governance.application.catalog_install import CatalogInstallRefusedError
from botocore.exceptions import ClientError, EndpointConnectionError
from sqlalchemy.exc import OperationalError
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

CATALOG_PACKAGE = "skills/catalog/" + "a" * 64 + "/"
SKILL_DIR = "inputs/skills/pdf-1a2b3c4d"


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_package_cache()
    yield
    clear_package_cache()


def _skill(name="pdf", s3_path=CATALOG_PACKAGE):
    return Skill(
        id=uuid4(), name=name, slug=name, source_type="content", workspace_id="w", s3_path=s3_path
    )


class FakeLog:
    entries: list = []

    async def append(self, task_id, rows, *, execution_id=None):
        FakeLog.entries.extend(rows)


@pytest.fixture
def activation(monkeypatch):
    from agentarea_execution.activities import dependencies

    ctx = AsyncMock()
    ctx.__aenter__.return_value = ctx
    ctx.task_log = MagicMock(return_value=FakeLog())
    skills = ctx.get_skill_service.return_value
    FakeLog.entries = []
    put_files = AsyncMock(return_value=(SKILL_DIR, [f"{SKILL_DIR}/SKILL.md"]))
    monkeypatch.setattr(files_module, "_put_skill_files", put_files)
    monkeypatch.setattr(dependencies, "ActivityServiceContainer", MagicMock())
    monkeypatch.setattr(dependencies, "ActivityContext", MagicMock(return_value=ctx))
    functions = {fn.__name__: fn for fn in activities.make_agent_activities(MagicMock())}
    activate_fn = functions["activate_skill_activity"]

    async def activate(request):
        return await ActivityEnvironment().run(activate_fn, request)

    return SimpleNamespace(skills=skills, activate=activate, put_files=put_files)


def _request(skill, **overrides):
    fields = {
        "skill_id": skill.id,
        "skill_name": skill.name,
        "user_context_data": {
            "user_id": "user",
            "workspace_id": "workspace",
            "agent_id": "agent-1",
        },
        "workspace_id": "workspace",
        "task_id": str(uuid4()),
        "tool_call_id": "call-1",
        "seq": 7,
        "event_id": str(uuid4()),
        "max_tokens": 8000,
        **overrides,
    }
    return ActivateSkillRequest(**fields)


def _packages(files):
    storage = MagicMock()
    storage.read_package = AsyncMock(return_value=files)
    return SkillPackages(storage, MagicMock(), None), storage


async def test_the_entry_goes_to_the_log_and_the_result_carries_only_its_size(activation):
    skill = _skill()
    activation.skills.get_with_catalog.return_value = skill
    activation.skills.read_skill_md = AsyncMock(return_value="# PDF\nSee https://pdf.example/docs")
    request = _request(skill)

    result = await activation.activate(request)

    [entry] = FakeLog.entries
    assert (entry.seq, str(entry.event_id), entry.role, entry.name, entry.tool_call_id) == (
        7,
        request.event_id,
        "tool",
        "activate_skill",
        "call-1",
    )
    assert entry.content.startswith('<skill_content name="pdf">\n# PDF\n')
    assert f"{SKILL_DIR}/" in entry.content
    assert "# PDF" not in result.model_dump_json()
    assert result.chars == len(entry.content)
    assert result.est_tokens >= count_tokens(entry.content)
    assert result.urls == ["pdf.example/docs"]
    assert not result.summarized
    assert activation.skills.get_with_catalog.await_args.kwargs == {"to_run": True}


async def test_activation_reads_the_body_once_per_package_digest(activation):
    skill = _skill()
    packages, storage = _packages({"SKILL.md": b"# PDF\nSteps"})
    activation.skills.get_with_catalog.return_value = skill
    activation.skills.read_skill_md = packages.read_skill_md

    await activation.activate(_request(skill))
    await activation.activate(_request(skill, seq=9, event_id=str(uuid4())))

    storage.read_package.assert_awaited_once_with(CATALOG_PACKAGE)
    assert [e.content.split("\n")[1] for e in FakeLog.entries] == ["# PDF", "# PDF"]


@pytest.mark.parametrize("size", [10 * 1024, 256 * 1024, 2 * 1024 * 1024])
async def test_the_result_is_the_same_few_bytes_whatever_the_body_size(activation, size):
    skill = _skill()
    activation.skills.get_with_catalog.return_value = skill
    activation.skills.read_skill_md = AsyncMock(return_value="x" * size)

    result = await activation.activate(_request(skill, max_tokens=1_000_000))

    assert len(result.model_dump_json()) < 200


def test_a_2_mb_single_character_body_counts_in_well_under_a_second():
    started = time.perf_counter()
    tokens = count_tokens("x" * 2 * 1024 * 1024)

    assert tokens > 0
    assert time.perf_counter() - started < 1.0


def test_special_token_text_counts_as_plain_text():
    assert count_tokens("<|endoftext|>") > 1


async def test_a_body_over_the_cap_is_pointed_at_and_its_entry_fits_the_cap(activation):
    skill = _skill()
    body = "# Big\n" + "Use pdfplumber. " * 130_000  # ~2 MB
    activation.skills.get_with_catalog.return_value = skill
    activation.skills.read_skill_md = AsyncMock(return_value=body)

    result = await activation.activate(_request(skill, max_tokens=4000))

    [entry] = FakeLog.entries
    assert result.summarized
    assert count_tokens(entry.content) <= 4000
    assert entry.content.startswith('<skill_content name="pdf">')
    assert f"{SKILL_DIR}/SKILL.md" in entry.content
    assert "# Big" in entry.content


async def test_a_body_over_the_cap_without_a_sandbox_is_stored_for_read_tool_output(
    activation, monkeypatch
):
    from agentarea_execution.workflows import context_store

    stored = {}

    class Store:
        def __init__(self, workspace_id, task_id):
            pass

        async def store_output(self, output_id, content):
            stored[output_id] = content

    monkeypatch.setattr(context_store, "ContextStore", Store)
    activation.put_files.side_effect = RuntimeError("no sandbox")
    skill = _skill()
    body = "y" * 100_000
    activation.skills.get_with_catalog.return_value = skill
    activation.skills.read_skill_md = AsyncMock(return_value=body)

    await activation.activate(_request(skill, max_tokens=2000))

    assert stored == {"call-1": body}
    assert 'read_tool_output("call-1")' in FakeLog.entries[0].content


@pytest.mark.parametrize(
    ("failure", "service"),
    [
        (EndpointConnectionError(endpoint_url="http://s3.test"), "Object storage"),
        (
            ClientError(
                {"Error": {"Code": "SlowDown"}, "ResponseMetadata": {"HTTPStatusCode": 503}},
                "GetObject",
            ),
            "Object storage",
        ),
        (OperationalError("SELECT 1", {}, ConnectionRefusedError("refused")), "The database"),
        (ConnectionError("reset by peer"), "A service"),
    ],
)
async def test_an_unreachable_service_is_retried_and_named(activation, failure, service):
    skill = _skill()
    activation.skills.get_with_catalog.return_value = skill
    activation.skills.read_skill_md = AsyncMock(side_effect=failure)

    with pytest.raises(ApplicationError, match=f"{service} is unreachable") as error:
        await activation.activate(_request(skill))
    assert not error.value.non_retryable
    assert error.value.details == ({"service": service},)
    assert FakeLog.entries == []


@pytest.mark.parametrize(
    "failure",
    [
        KeyError("spec"),
        ClientError(
            {"Error": {"Code": "AccessDenied"}, "ResponseMetadata": {"HTTPStatusCode": 403}},
            "GetObject",
        ),
        RuntimeError("bug"),
    ],
)
async def test_any_other_error_is_final_and_names_the_skill(activation, failure):
    skill = _skill()
    activation.skills.get_with_catalog.return_value = skill
    activation.skills.read_skill_md = AsyncMock(side_effect=failure)

    with pytest.raises(ApplicationError, match="Skill 'pdf' could not be activated") as error:
        await activation.activate(_request(skill))
    assert error.value.non_retryable


async def test_activation_reads_the_package_the_run_was_configured_with(activation):
    skill = _skill(s3_path="skills/catalog/" + "b" * 64 + "/")
    activation.skills.get_with_catalog.return_value = skill
    activation.skills.read_skill_md = AsyncMock(return_value="# v1")

    await activation.activate(_request(skill, package=CATALOG_PACKAGE))

    assert activation.skills.read_skill_md.await_args.kwargs == {"at": CATALOG_PACKAGE}


async def test_the_file_listing_counts_toward_the_cap(activation):
    skill = _skill()
    paths = [f"{SKILL_DIR}/scripts/tool_{i}.py" for i in range(400)]
    activation.put_files.return_value = (SKILL_DIR, paths)
    activation.skills.get_with_catalog.return_value = skill
    activation.skills.read_skill_md = AsyncMock(return_value="# PDF\nSteps")

    await activation.activate(_request(skill, max_tokens=600))

    [entry] = FakeLog.entries
    assert count_tokens(entry.content) <= 600
    assert entry.content.startswith('<skill_content name="pdf">\n# PDF\nSteps')


async def test_sizes_are_counted_with_the_tokenizer_not_by_characters(activation):
    skill = _skill()
    body = "Извлеки таблицы из PDF и сохрани их в CSV. " * 200
    activation.skills.get_with_catalog.return_value = skill
    activation.skills.read_skill_md = AsyncMock(return_value=body)
    cap = len(body) // 4 + 200

    result = await activation.activate(_request(skill, max_tokens=cap))

    assert result.summarized
    assert count_tokens(FakeLog.entries[0].content) <= cap


@pytest.mark.parametrize(
    "gone",
    [
        GitHubSourceGoneError("The skill was removed upstream: o/r/pdf"),
        GitHubTreeMismatchError("tree mismatch"),
    ],
)
async def test_an_upstream_source_gone_is_final(activation, gone):
    skill = _skill()
    activation.skills.get_with_catalog.return_value = skill
    activation.skills.read_skill_md = AsyncMock(side_effect=gone)

    with pytest.raises(ApplicationError, match="Skill 'pdf' cannot be read") as error:
        await activation.activate(_request(skill))
    assert error.value.non_retryable


async def test_a_skill_the_install_policy_refuses_is_final(activation):
    skill = _skill()
    activation.skills.get_with_catalog.side_effect = CatalogInstallRefusedError(
        "Install refused by policy: denied by registry_trust:community for workspace w"
    )
    activation.skills.read_skill_md = AsyncMock()

    with pytest.raises(ApplicationError, match="registry_trust:community") as error:
        await activation.activate(_request(skill))
    assert error.value.non_retryable
    activation.skills.read_skill_md.assert_not_awaited()


async def test_a_skill_gone_is_final(activation):
    skill = _skill()
    activation.skills.get_with_catalog.return_value = None

    with pytest.raises(ApplicationError, match="no longer exists") as error:
        await activation.activate(_request(skill))
    assert error.value.non_retryable


# --- histories recorded before activation read the package ----------------------


def test_an_old_config_payload_with_skill_bodies_still_deserializes():
    old = {
        "id": str(uuid4()),
        "name": "Agent",
        "description": "",
        "instruction": "Do it",
        "model_id": str(uuid4()),
        "context_window": 64000,
        "skills": [
            {
                "id": str(uuid4()),
                "name": "pdf",
                "description": "PDFs",
                "content": "# Old body",
                "files": ["(additional files available)"],
            }
        ],
    }

    config = AgentConfigResult.model_validate(old)

    assert config.skills[0].content == "# Old body"
    assert config.outage_wait is None


async def test_a_run_recorded_before_the_change_activates_from_the_carried_body(monkeypatch):
    from agentarea_agents_sdk.skills import SkillActivationTool, SkillCatalogBuilder, SkillEntry
    from agentarea_execution.models import MaterializeSkillFilesResult
    from agentarea_execution.workflows.models import ToolCall

    seen = []

    async def execute_activity(name, *, args, **kwargs):
        seen.append(name)
        return MaterializeSkillFilesResult(success=False, error="no sandbox")

    monkeypatch.setattr(workflow_module.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(workflow_module.workflow, "logger", MagicMock())
    monkeypatch.setattr(workflow_module.workflow, "patched", lambda _patch_id: False)
    monkeypatch.setattr(
        workflow_module.workflow, "info", lambda: SimpleNamespace(workflow_id="wf-1")
    )
    skills = [
        SkillInfo(id=str(uuid4()), name="pdf", description="", content="# Old body").model_dump()
    ]
    flow = workflow_module.AgentExecutionWorkflow()
    flow.state.task_id = "task"
    flow.state.workspace_id = "workspace"
    flow.state.agent_config = {"skills": skills}
    flow._skill_tool = SkillActivationTool(
        SkillCatalogBuilder.build_registry(
            [SkillEntry(name="pdf", description="", content="# Old body", files=[])]
        )
    )
    flow._gate_tool_call = AsyncMock(return_value=(True, False))
    flow.event_manager = MagicMock()

    await flow._execute_skill_activation(
        ToolCall(
            id="call-1",
            type="function",
            function={"name": "activate_skill", "arguments": json.dumps({"skill_name": "pdf"})},
        )
    )

    assert flow.state.messages[-1].content.startswith('<skill_content name="pdf">\n# Old body')
    assert seen == [Activities.MATERIALIZE_SKILL_FILES]


def test_the_outage_cap_counts_from_the_chains_first_run(monkeypatch):
    # A continued run reports its own start; the execution timeout runs from the chain's.
    from datetime import UTC, datetime, timedelta

    from agentarea_execution.workflows.agent import outage

    chain_start = datetime(2026, 1, 1, tzinfo=UTC)
    run_start = chain_start + timedelta(hours=4)
    info = SimpleNamespace(
        execution_timeout=timedelta(hours=6),
        workflow_start_time=run_start,
        run_timeout=None,
        start_time=run_start,
    )
    monkeypatch.setattr(outage.workflow, "info", lambda: info)
    flow = workflow_module.AgentExecutionWorkflow()
    flow.state.chain_expires_at = chain_start + timedelta(hours=6)

    assert flow._outage_hard_cap() == chain_start + timedelta(hours=6) - timedelta(minutes=10)

    flow.state.chain_expires_at = None  # a run from before the chain's expiry was carried
    assert flow._outage_hard_cap() == run_start + timedelta(hours=6) - timedelta(minutes=10)
