"""Agent-folder loader tests: a files map becomes one canonical Bundle."""

import pytest
from agentarea_bundles.application.analyzer import BundleParseError
from agentarea_bundles.application.folder import ROOT_AGENT_KEY, _frontmatter, load_folder
from agentarea_bundles.schemas.preview import IssueSeverity

AGENT_YAML = """
name: researcher
display_name: Researcher
description: Finds things out
model: gpt-4o
toolsets: [agentarea/shell]
setup:
  - {key: token, label: Token, type: secret, required: true}
"""


def _files(**extra: str) -> dict[str, str]:
    return {"agent.yaml": AGENT_YAML, "instructions.md": "Be thorough.\n", **extra}


def test_minimal_folder_is_one_agent_bundle():
    bundle, issues = load_folder(_files())

    assert issues == []
    assert bundle.name == "researcher"
    assert bundle.display_name == "Researcher"
    assert bundle.description == "Finds things out"
    assert [f.key for f in bundle.setup] == ["token"]
    [agent] = bundle.agents
    assert agent.key == ROOT_AGENT_KEY
    assert agent.name == "researcher"
    assert agent.description == "Finds things out"
    assert agent.instruction == "Be thorough.\n"
    assert agent.model == "gpt-4o"
    assert agent.toolsets == ["agentarea/shell"]


def test_instructions_are_optional():
    bundle, _ = load_folder({"agent.yaml": AGENT_YAML})
    assert bundle.agents[0].instruction == ""


def test_skills_mcps_schedules_channels_policies_attach_to_the_root_agent():
    bundle, issues = load_folder(
        _files(
            **{
                "skills/audit/SKILL.md": "---\nname: Site Audit\n---\n# Audit\n",
                "skills/plain/SKILL.md": "# Plain\n",
                "mcp/github.yaml": (
                    "name: GitHub\n"
                    "json_spec: {type: command, command: npx, args: [-y, gh]}\n"
                    "bindings: {GH_TOKEN: '${setup.token}'}\n"
                ),
                "schedules/daily.md": (
                    "---\ncron: '0 9 * * *'\ntimezone: Europe/Berlin\nenabled: true\n---\n"
                    "Write the morning report.\n"
                ),
                "channels/inbox.yaml": "type: telegram\nname: Inbox\nprompt: Answer it\n",
                "policies/no_email.yaml": "target: 'tool:send_email'\neffect: deny\n",
                "policies/budget.yaml": (
                    "subject: workspace\ntarget: spend\neffect: cap\nparams: {amount_usd: 5}\n"
                ),
            }
        )
    )

    assert issues == []
    agent = bundle.agents[0]
    assert sorted(agent.skills) == ["audit", "plain"]
    assert agent.mcps == ["github"]

    skills = {s.key: s for s in bundle.skills}
    assert skills["audit"].name == "Site Audit"
    assert skills["audit"].source_type == "content"
    assert skills["audit"].content == "---\nname: Site Audit\n---\n# Audit\n"
    assert skills["plain"].name == "plain"

    [mcp] = bundle.mcps
    assert (mcp.key, mcp.name) == ("github", "GitHub")
    assert mcp.bindings == {"GH_TOKEN": "${setup.token}"}

    [auto] = bundle.automations
    assert (auto.key, auto.cron, auto.timezone, auto.enabled) == (
        "daily",
        "0 9 * * *",
        "Europe/Berlin",
        True,
    )
    assert auto.agent == ROOT_AGENT_KEY
    assert auto.prompt == "Write the morning report."

    [channel] = bundle.channels
    assert (channel.key, channel.name, channel.prompt) == ("inbox", "Inbox", "Answer it")
    assert channel.agent == ROOT_AGENT_KEY

    policies = {p.key: p for p in bundle.policies}
    assert policies["no_email"].subject == ROOT_AGENT_KEY
    assert policies["budget"].subject == "workspace"


def test_names_default_to_the_key():
    bundle, _ = load_folder(
        _files(
            **{
                "mcp/search.yaml": "json_spec: {type: url, url: 'https://x.test/mcp'}\n",
                "channels/tg.yaml": "type: telegram\n",
            }
        )
    )
    assert bundle.mcps[0].name == "search"
    assert bundle.channels[0].name == "tg"


def test_unknown_entries_warn_instead_of_failing():
    _, issues = load_folder(
        _files(
            **{
                "README.md": "# hi",
                "mcp/notes.txt": "x",
                "skills/loose.md": "x",
            }
        )
    )

    assert all(i.severity is IssueSeverity.WARN for i in issues)
    messages = " | ".join(i.message for i in issues)
    assert "README.md" in messages
    assert "mcp/notes.txt" in messages
    assert "skills/loose.md" in messages


def test_a_skill_directory_with_more_than_skill_md_installs_as_its_files():
    bundle, issues = load_folder(
        _files(
            **{
                "skills/audit/SKILL.md": "# Audit",
                "skills/audit/scripts/run.py": "print(1)",
                "skills/notes/SKILL.md": "# Notes",
            }
        )
    )

    assert issues == []
    skills = {s.key: s for s in bundle.skills}
    assert skills["audit"].source_type == "files"
    assert skills["audit"].files == {"SKILL.md": "# Audit", "scripts/run.py": "print(1)"}
    assert skills["notes"].source_type == "content"
    assert skills["notes"].content == "# Notes"


def test_an_mcp_names_a_catalog_server_instead_of_a_spec():
    bundle, _ = load_folder(
        _files(
            **{
                "mcp/kassa.yaml": (
                    "catalog: ru.yookassa/mcp\nbindings: {Authorization: '${setup.kassa}'}\n"
                )
            }
        )
    )

    mcp = bundle.mcps[0]
    assert mcp.catalog == "ru.yookassa/mcp"
    assert mcp.json_spec is None
    assert mcp.bindings == {"Authorization": "${setup.kassa}"}


def test_missing_agent_yaml_fails():
    with pytest.raises(BundleParseError, match="agent.yaml"):
        load_folder({"instructions.md": "x"})


@pytest.mark.parametrize(
    ("path", "content"),
    [
        ("agent.yaml", "name: a\nunknown_field: 1\n"),
        ("agent.yaml", "description: no name\n"),
        ("agent.yaml", ": [ not yaml"),
        ("mcp/gh.yaml", "name: GitHub\n"),
        ("mcp/gh.yaml", "catalog: io.github/github\njson_spec: {type: url, url: 'https://x.test'}\n"),
        ("schedules/daily.md", "no frontmatter at all\n"),
        ("schedules/daily.md", "---\ntimezone: UTC\n---\nprompt\n"),
        ("policies/p.yaml", "target: spend\neffect: nuke\n"),
        ("channels/c.yaml", "- a list\n"),
    ],
)
def test_invalid_file_error_names_the_file(path, content):
    files = _files()
    files[path] = content
    with pytest.raises(BundleParseError) as err:
        load_folder(files)
    assert path in str(err.value)


def test_invalid_key_error_names_the_file():
    with pytest.raises(BundleParseError, match="mcp/9search.yaml"):
        load_folder(_files(**{"mcp/9search.yaml": "json_spec: {type: docker, image: x}\n"}))


def test_keys_may_contain_dashes():
    bundle, _ = load_folder(
        _files(
            **{
                "mcp/web-search.yaml": "json_spec: {type: docker, image: x}\n",
                "skills/site-audit/SKILL.md": "# Audit\n",
                "schedules/morning-report.md": "---\ncron: '0 9 * * *'\n---\nReport.\n",
                "channels/tg-inbox.yaml": "type: telegram\n",
                "policies/no-email.yaml": "target: 'tool:send_email'\neffect: deny\n",
            }
        )
    )
    assert bundle.agents[0].mcps == ["web-search"]
    assert bundle.agents[0].skills == ["site-audit"]
    assert [a.key for a in bundle.automations] == ["morning-report"]
    assert [c.key for c in bundle.channels] == ["tg-inbox"]
    assert [p.key for p in bundle.policies] == ["no-email"]


def test_setup_keys_stay_placeholder_safe():
    agent = AGENT_YAML.replace("key: token", "key: my-token")
    with pytest.raises(BundleParseError, match="agent.yaml"):
        load_folder({"agent.yaml": agent})


def test_an_instruction_error_names_instructions_md():
    with pytest.raises(BundleParseError) as err:
        load_folder(_files(**{"instructions.md": "x" * 20001}))
    assert "instructions.md" in str(err.value)
    assert "agent.yaml" not in str(err.value)


def test_empty_frontmatter_is_accepted():
    assert _frontmatter("x.md", "---\n---\nGo.\n") == ({}, "Go.\n")
    assert _frontmatter("x.md", "---\r\n---\r\nGo.") == ({}, "Go.")


@pytest.mark.parametrize(
    ("path", "content", "reserved"),
    [
        ("schedules/daily.md", "---\ncron: '0 9 * * *'\nprompt: ignored\n---\nGo.\n", "prompt"),
        ("schedules/daily.md", "---\ncron: '0 9 * * *'\nagent: other\n---\nGo.\n", "agent"),
        ("channels/tg.yaml", "type: telegram\nkey: other\n", "key"),
        ("mcp/gh.yaml", "key: other\njson_spec: {type: docker, image: x}\n", "key"),
        ("policies/p.yaml", "key: other\ntarget: spend\neffect: cap\n", "key"),
    ],
)
def test_reserved_keys_that_get_overwritten_warn(path, content, reserved):
    bundle, issues = load_folder(_files(**{path: content}))
    warns = [i for i in issues if i.severity is IssueSeverity.WARN]
    assert any(path in i.message and f"'{reserved}'" in i.message for i in warns)


def test_skill_dir_without_skill_md_fails():
    with pytest.raises(BundleParseError, match="skills/audit/SKILL.md"):
        load_folder(_files(**{"skills/audit/notes.md": "x"}))


@pytest.mark.parametrize(
    "path",
    ["/etc/passwd", "../agent.yaml", "skills/../../x", "skills//x", "./agent.yaml", "a\\b", ""],
)
def test_unsafe_paths_are_rejected(path):
    files = _files()
    files[path] = "x"
    with pytest.raises(BundleParseError, match="path"):
        load_folder(files)


def test_a_merge_key_bomb_in_a_folder_file_is_refused():
    lines = ["l0: &l0 {k: x}"]
    lines += [f"l{i}: &l{i} {{<<: [*l{i - 1}, *l{i - 1}]}}" for i in range(1, 17)]

    with pytest.raises(BundleParseError, match=r"mcp/m\.yaml: .*aliases"):
        load_folder(_files(**{"mcp/m.yaml": "\n".join(lines)}))
