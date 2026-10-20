"""A SKILL.md is an old index's stub only when it carries the stub's exact marker
line and the Source, Repository and Path lines after it; nothing else is guessed.
A bare stub is exactly what an index wrote for one skill; any edit makes it not bare.
"""

import pytest
from agentarea_agents.application.skill_stub import STUB_MARKER, StubSource, bare_stub, parse_stub

LINES = [
    "Source: https://github.com/o/r/blob/main/skills/pdf/SKILL.md",
    "Repository: o/r",
    "Path: skills/pdf/SKILL.md",
]


def _stub(*lines: str, marker: str = STUB_MARKER) -> str:
    return "\n".join(["---", "name: pdf", "---", "Fill PDFs", "", marker, *lines, "License: MIT"])


def test_the_stub_names_the_original_and_the_folder_it_lives_in():
    stub = parse_stub(_stub(*LINES))

    assert stub == StubSource(
        source_url="https://github.com/o/r/blob/main/skills/pdf/SKILL.md",
        repo="o/r",
        path="skills/pdf/SKILL.md",
    )
    assert stub is not None and stub.folder == "skills/pdf"


@pytest.mark.parametrize(
    "body",
    [
        "---\nname: pdf\n---\n# Fill PDFs\n" + "\n".join(LINES),
        _stub(*LINES, marker="Imported system skill metadata."),
        _stub(*LINES[:2]),
        _stub(LINES[0], "Repository: ", LINES[2]),
        "\n".join([*LINES, STUB_MARKER]),
    ],
    ids=["no-marker", "other-marker", "no-path", "empty-repository", "lines-before-marker"],
)
def test_anything_short_of_the_stub_is_not_a_stub(body):
    assert parse_stub(body) is None


NAME, DESCRIPTION = "pdf--o-r--1", "Fill PDFs"
INDEX_STUB = "\n".join(
    [
        "---",
        f'name: "{NAME}"',
        f'description: "{DESCRIPTION}"',
        "---",
        "",
        DESCRIPTION,
        "",
        STUB_MARKER,
        *LINES,
        "License: MIT",
        "Distribution: compatible",
    ]
)


def _bare(body: str):
    return bare_stub(body, name=NAME, description=DESCRIPTION)


def test_the_stub_an_index_wrote_for_the_skill_is_bare():
    assert _bare(INDEX_STUB) == parse_stub(INDEX_STUB)
    assert _bare(INDEX_STUB.replace(f'"{DESCRIPTION}"', DESCRIPTION) + "\n\n") is not None


@pytest.mark.parametrize(
    "body",
    [
        INDEX_STUB + "\nMy notes",
        INDEX_STUB.replace(STUB_MARKER, "# Always use pdftk\n\n" + STUB_MARKER),
        INDEX_STUB.replace(f'description: "{DESCRIPTION}"', 'description: "Fill PDFs fast"'),
        INDEX_STUB.replace("---\n\n", "allowed-tools: Bash\n---\n\n"),
        INDEX_STUB.replace(LINES[0], "Source: my notes"),
        INDEX_STUB + "\n" + LINES[2],
        INDEX_STUB.replace("License: MIT", "License: internal only"),
    ],
    ids=[
        "note-after",
        "instructions-above",
        "frontmatter-description",
        "frontmatter-key",
        "source-notes",
        "second-path",
        "license-words",
    ],
)
def test_a_stub_someone_edited_is_not_bare(body):
    assert _bare(body) is None


def test_a_stub_for_another_skill_is_not_bare():
    assert bare_stub(INDEX_STUB, name="other", description=DESCRIPTION) is None
    assert bare_stub(INDEX_STUB, name=NAME, description="Something else") is None
