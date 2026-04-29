"""Workspace-files HTTP API end-to-end.

Read-only listing of every object stored under
``workspaces/{workspace_id}/`` in S3/RustFS. This is the user-facing window
into files that may have been produced by agents, project uploads, or task
artifacts — anything that touched ``ArtifactService``.

Endpoints:

  GET /v1/files               (list)
  GET /v1/files/{path}        (presigned download URL)

Load-bearing invariant: workspace isolation is enforced by
``ArtifactService`` prepending ``workspaces/{workspace_id}/`` to every key,
where ``workspace_id`` comes from ``UserContextDep`` (auth-derived, not
client-supplied). Bob must never see Alice's bytes.
"""

from __future__ import annotations

import httpx
import pytest


def _create_project(client: httpx.Client, name: str) -> str:
    resp = client.post("/v1/projects/", json={"name": name})
    resp.raise_for_status()
    return resp.json()["id"]


def _upload_via_project(client: httpx.Client, project_id: str, filename: str, body: bytes) -> None:
    resp = client.post(
        f"/v1/projects/{project_id}/files",
        files={"file": (filename, body, "text/plain")},
    )
    resp.raise_for_status()


@pytest.mark.integration
def test_workspace_files_listing_includes_uploaded_project_file(
    alice_client: httpx.Client,
) -> None:
    """Project uploads land in the same artifacts bucket under
    ``projects/{id}/``, so they show up directly in the workspace listing."""
    project_id = _create_project(alice_client, "ws-files-listing")
    _upload_via_project(alice_client, project_id, "report.txt", b"hello-workspace\n")

    listing = alice_client.get("/v1/files")
    assert listing.status_code == 200, listing.text[:200]
    paths = [f["path"] for f in listing.json()["files"]]
    assert f"projects/{project_id}/report.txt" in paths, paths


@pytest.mark.integration
def test_workspace_files_show_empty_project_as_folder(
    alice_client: httpx.Client,
) -> None:
    """Newly-created projects must be visible in /files even before any file
    is uploaded — surfaced via the ``directories`` field."""
    project_id = _create_project(alice_client, "ws-files-empty-project")

    listing = alice_client.get("/v1/files")
    assert listing.status_code == 200, listing.text[:200]
    body = listing.json()
    assert f"projects/{project_id}/" in body.get("directories", []), body


@pytest.mark.integration
def test_workspace_files_are_isolated_per_workspace(
    alice_client: httpx.Client, bob_client: httpx.Client
) -> None:
    alice_project = _create_project(alice_client, "ws-files-isolation")
    _upload_via_project(alice_client, alice_project, "secret.txt", b"alice-eyes-only")

    bob_listing = bob_client.get("/v1/files")
    assert bob_listing.status_code == 200, bob_listing.text[:200]
    bob_paths = [f["path"] for f in bob_listing.json()["files"]]
    assert not any("secret.txt" in p for p in bob_paths), (
        f"CRITICAL: Bob saw Alice's file in workspace listing: {bob_paths!r}"
    )


@pytest.mark.integration
def test_workspace_file_download_404_when_missing(
    alice_client: httpx.Client,
) -> None:
    resp = alice_client.get("/v1/files/never-existed.txt")
    assert resp.status_code == 404, resp.text[:200]


@pytest.mark.integration
def test_workspace_file_path_traversal_is_refused(
    alice_client: httpx.Client,
) -> None:
    # ArtifactService rejects '..' segments — the API must surface that as a
    # 4xx, never as a 200 reaching out of the workspace prefix.
    resp = alice_client.get("/v1/files/../../etc/passwd")
    assert resp.status_code in (400, 404, 422), resp.text[:200]
