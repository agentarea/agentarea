"""AnalyzeRequest: exactly one source, and an agent folder is a bounded, relative file map."""

import pytest
from agentarea_api.api.v1.bundles import _MAX_BUNDLE_BYTES, AnalyzeRequest
from pydantic import ValidationError


def test_files_is_a_source_of_its_own():
    body = AnalyzeRequest(files={"agent.yaml": "name: a\n"})
    assert body.files == {"agent.yaml": "name: a\n"}


def test_a_canonical_bundle_is_a_source_of_its_own():
    body = AnalyzeRequest(bundle={"name": "a"})
    assert body.bundle is not None and body.bundle.name == "a"


def test_setup_values_ride_along_so_the_plan_sees_them():
    body = AnalyzeRequest(files={"agent.yaml": "name: a\n"}, setup_values={"model": "m2"})
    assert body.setup_values == {"model": "m2"}
    assert AnalyzeRequest(source="name: a").setup_values == {}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"files": {}},
        {"source": "name: a", "files": {"agent.yaml": "name: a"}},
        {"source_url": "https://x.test/b.yaml", "files": {"agent.yaml": "name: a"}},
        {"source": "name: a", "bundle": {"name": "a"}},
    ],
)
def test_exactly_one_source(payload):
    with pytest.raises(ValidationError, match="exactly one"):
        AnalyzeRequest(**payload)


@pytest.mark.parametrize("path", ["/etc/passwd", "../agent.yaml", "skills/../../x", "a\\b"])
def test_unsafe_paths_are_rejected(path):
    with pytest.raises(ValidationError, match="path"):
        AnalyzeRequest(files={"agent.yaml": "name: a", path: "x"})


def test_folder_over_the_size_cap_is_rejected():
    with pytest.raises(ValidationError, match="5MB"):
        AnalyzeRequest(files={"agent.yaml": "x" * (_MAX_BUNDLE_BYTES + 1)})
