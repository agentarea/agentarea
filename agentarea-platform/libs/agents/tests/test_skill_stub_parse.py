"""A SKILL.md is an old index's stub only when it carries the stub's exact marker
line and the Source, Repository and Path lines after it; nothing else is guessed.
"""

import pytest
from agentarea_agents.application.skill_stub_refresh import STUB_MARKER, StubSource, parse_stub

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
