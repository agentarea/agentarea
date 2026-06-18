"""Project-files HTTP API end-to-end.

Files for a project live in S3/RustFS under
``workspaces/{workspace_id}/projects/{project_id}/...``, served by
``ArtifactService``.
The endpoints we exercise here:

  POST   /v1/projects/{id}/files          (multipart upload)
  GET    /v1/projects/{id}/files          (list)
  GET    /v1/projects/{id}/files/{path}   (authenticated download URL)
  DELETE /v1/projects/{id}/files/{path}

Load-bearing invariants:

  * The download URL host is reachable from outside the cluster. A regression
    where the API hands out an internal-only host (``rustfs:9000``) is silent
    in unit tests but fatal in the browser.
  * Workspace isolation: Bob can never list/upload/delete files in
    Alice's project.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

import httpx
import pytest


def _create_project(client: httpx.Client, name: str) -> str:
    resp = client.post("/v1/projects/", json={"name": name})
    resp.raise_for_status()
    return resp.json()["id"]


@pytest.mark.integration
def test_project_file_upload_list_download_delete_roundtrip(
    alice_client: httpx.Client,
) -> None:
    project_id = _create_project(alice_client, "files-roundtrip")
    body = b"project-file-content-omega-7\n"
    filename = "report.txt"

    upload = alice_client.post(
        f"/v1/projects/{project_id}/files",
        files={"file": (filename, body, "text/plain")},
    )
    assert upload.status_code == 204, upload.text[:200]

    listing = alice_client.get(f"/v1/projects/{project_id}/files")
    assert listing.status_code == 200, listing.text[:200]
    listed = listing.json()
    paths = [f["path"] for f in listed["files"]]
    assert filename in paths, f"{filename!r} not in {paths!r}"
    [item] = [f for f in listed["files"] if f["path"] == filename]
    assert item["size"] == len(body)

    dl = alice_client.get(f"/v1/projects/{project_id}/files/{filename}")
    assert dl.status_code == 200, dl.text[:200]
    payload = dl.json()
    assert payload["path"] == filename
    url = payload["url"]
    assert url.startswith("http"), url

    # Download URL must point at a public AgentArea host, never bare
    # ``rustfs`` / ``minio`` cluster names that browsers can't resolve.
    host = urlparse(url).hostname or ""
    assert host not in ("rustfs", "minio"), (
        f"presigned URL host {host!r} is internal-only — would 404 in browser"
    )
    public = os.environ.get("PUBLIC_S3_ENDPOINT")
    if public:
        assert urlparse(public).hostname == host, (
            f"presigned URL host {host!r} != PUBLIC_S3_ENDPOINT host "
            f"{urlparse(public).hostname!r}"
        )

    # And the URL actually serves the bytes back with the caller's auth.
    with httpx.Client(headers=alice_client.headers, timeout=10.0) as http:
        served = http.get(url)
    served.raise_for_status()
    assert served.content == body

    deleted = alice_client.delete(f"/v1/projects/{project_id}/files/{filename}")
    assert deleted.status_code == 204, deleted.text[:200]

    listing_after = alice_client.get(f"/v1/projects/{project_id}/files").json()
    assert filename not in [f["path"] for f in listing_after["files"]]


@pytest.mark.integration
def test_project_file_download_404_when_missing(
    alice_client: httpx.Client,
) -> None:
    project_id = _create_project(alice_client, "files-missing")
    dl = alice_client.get(f"/v1/projects/{project_id}/files/never.txt")
    assert dl.status_code == 404, dl.text[:200]


@pytest.mark.integration
def test_project_files_are_workspace_scoped(
    alice_client: httpx.Client, bob_client: httpx.Client
) -> None:
    project_id = _create_project(alice_client, "files-isolation")
    alice_client.post(
        f"/v1/projects/{project_id}/files",
        files={"file": ("secret.txt", b"alice-eyes-only", "text/plain")},
    ).raise_for_status()

    # Bob must not see Alice's project at all.
    listing = bob_client.get(f"/v1/projects/{project_id}/files")
    assert listing.status_code == 404, (
        f"CRITICAL: Bob listed Alice's project files: HTTP {listing.status_code} "
        f"{listing.text[:200]!r}"
    )
    upload = bob_client.post(
        f"/v1/projects/{project_id}/files",
        files={"file": ("evil.txt", b"x", "text/plain")},
    )
    assert upload.status_code == 404, upload.text[:200]
    download = bob_client.get(f"/v1/projects/{project_id}/files/secret.txt")
    assert download.status_code == 404, download.text[:200]
    delete = bob_client.delete(f"/v1/projects/{project_id}/files/secret.txt")
    assert delete.status_code == 404, delete.text[:200]


@pytest.mark.integration
def test_project_file_unknown_project_returns_404(
    alice_client: httpx.Client,
) -> None:
    fake = "00000000-0000-0000-0000-000000000000"
    resp = alice_client.post(
        f"/v1/projects/{fake}/files",
        files={"file": ("x.txt", b"x", "text/plain")},
    )
    assert resp.status_code == 404, resp.text[:200]
