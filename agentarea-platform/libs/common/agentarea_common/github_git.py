"""Public GitHub content without the REST API or a token (ADR-0044).

The REST API allows 60 anonymous requests an hour per address, shared by every
tenant of a deployment. Git's own endpoints do not count against it: a ref is
resolved with one protocol-v2 ``ls-refs`` request to
``github.com/<repo>.git/git-upload-pack``, and the files of a commit come from
its archive at ``codeload.github.com``. A folder's tree SHA is computed here
from the files, exactly as git computes it, so a pointer is pinned and checked
without asking GitHub for its tree.

An archive is immutable for a commit, so the last few are kept in-process by
``(repo, commit)``: a sync that reads several folders of one commit downloads
it once.
"""

import asyncio
import hashlib
import io
import re
import tarfile
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from agentarea_common.outbound import Destination, outbound_client

GITHUB = "https://github.com"
CODELOAD = "https://codeload.github.com"
TIMEOUT_SECONDS = 60.0
# Compressed bytes of one archive; a repository bigger than this is read
# through the REST API with a token, or not at all.
MAX_ARCHIVE_BYTES = 25 * 1024 * 1024
# What reading an archive may decompress and hash, kept or not.
MAX_ARCHIVE_UNPACKED_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 50_000
MAX_LS_REFS_BYTES = 64 * 1024
ARCHIVE_CACHE_MAX_BYTES = 64 * 1024 * 1024

TREE_MODE = "40000"
SYMLINK_MODE = "120000"
_REPO_PART = re.compile(r"[A-Za-z0-9_.-]+")
_GIT_SHA = re.compile(r"[0-9a-f]{40}")

_archives: OrderedDict[tuple[str, str], bytes] = OrderedDict()
_archive_bytes = 0


class GitHubGitError(RuntimeError):
    """GitHub refused or failed a git read."""


class GitHubGitNotFoundError(GitHubGitError):
    """The repository, ref or commit is not there, or is private."""


class GitHubGitRateLimitError(GitHubGitError):
    """GitHub throttled the read."""


class GitHubArchiveTooLargeError(ValueError):
    """The archive, or what was asked of it, is over its cap."""


@dataclass(frozen=True)
class GitFile:
    """One file of a commit: its git mode, blob SHA, and its bytes when kept."""

    mode: str
    sha: str
    data: bytes | None


def clear_archive_cache() -> None:
    global _archive_bytes
    _archives.clear()
    _archive_bytes = 0


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\x00" % len(data) + data, usedforsecurity=False).hexdigest()


def git_tree_shas(files: Mapping[str, tuple[str, str]]) -> dict[str, str]:
    """The tree SHA of every directory holding ``files`` (``path -> (mode, blob sha)``).

    ``""`` is the root. Entries sort as git sorts them: by name, a directory's
    name with a trailing slash.
    """
    children: dict[str, dict[str, tuple[str, str | None]]] = {"": {}}
    for path, (mode, sha) in files.items():
        parts = path.split("/")
        for depth in range(len(parts) - 1):
            parent, child = "/".join(parts[:depth]), "/".join(parts[: depth + 1])
            children.setdefault(parent, {})[parts[depth]] = (TREE_MODE, None)
            children.setdefault(child, {})
        children.setdefault("/".join(parts[:-1]), {})[parts[-1]] = (mode, sha)

    def depth_of(directory: str) -> int:
        return directory.count("/") + 1 if directory else 0

    shas: dict[str, str] = {}
    for directory in sorted(children, key=depth_of, reverse=True):
        entries = children[directory]

        def order(name: str, entries: dict = entries) -> bytes:
            return (name + "/" if entries[name][0] == TREE_MODE else name).encode()

        body = bytearray()
        for name in sorted(entries, key=order):
            mode, sha = entries[name]
            if sha is None:
                sha = shas[f"{directory}/{name}" if directory else name]
            body += f"{mode} {name}".encode() + b"\x00" + bytes.fromhex(sha)
        shas[directory] = hashlib.sha1(
            b"tree %d\x00" % len(body) + bytes(body), usedforsecurity=False
        ).hexdigest()
    return shas


def _checked_repo(repo: str) -> str:
    parts = repo.split("/")
    if len(parts) != 2 or not all(_REPO_PART.fullmatch(p) and p not in (".", "..") for p in parts):
        raise GitHubGitError(f"Not a GitHub repository name: {repo!r}")
    return repo


def _pkt(line: str) -> bytes:
    data = line.encode()
    return b"%04x" % (len(data) + 4) + data


def _pkt_lines(body: bytes) -> list[str]:
    lines, at = [], 0
    while at + 4 <= len(body):
        try:
            size = int(body[at : at + 4], 16)
        except ValueError as e:
            raise GitHubGitError("GitHub answered something that is not a git response") from e
        if size < 4:
            at += 4
            continue
        lines.append(body[at + 4 : at + size].decode("utf-8", "replace").rstrip("\n"))
        at += size
    return lines


def _check(response: httpx.Response, what: str) -> None:
    if response.status_code == 200:
        return
    if response.status_code == 429 or (
        response.status_code == 403 and response.headers.get("Retry-After")
    ):
        raise GitHubGitRateLimitError(f"GitHub throttled {what}; retry later")
    if response.status_code in (401, 404):
        raise GitHubGitNotFoundError(f"{what}: not on GitHub, or private")
    raise GitHubGitError(f"{what}: GitHub answered {response.status_code}")


async def resolve_commit(
    repo: str, ref: str | None, *, transport: httpx.AsyncBaseTransport | None = None
) -> str:
    """The commit ``ref`` names: a branch, a tag (peeled), or ``None`` for HEAD.

    A 40-hex ``ref`` is already a commit and is returned as is.
    """
    _checked_repo(repo)
    if ref and _GIT_SHA.fullmatch(ref):
        return ref
    if ref is not None and (not ref or any(c.isspace() or ord(c) < 32 for c in ref)):
        raise GitHubGitError(f"Not a git ref: {ref!r}")
    if ref is None:
        wanted = ["HEAD"]
    elif ref.startswith("refs/"):
        wanted = [ref]
    else:
        wanted = [f"refs/heads/{ref}", f"refs/tags/{ref}"]
    body = (
        _pkt("command=ls-refs\n")
        + _pkt("agent=agentarea\n")
        + b"0001"
        + _pkt("peel\n")
        + _pkt("symrefs\n")
        + b"".join(_pkt(f"ref-prefix {name}\n") for name in wanted)
        + b"0000"
    )
    what = f"{repo} ref {ref or 'HEAD'}"
    async with outbound_client(
        Destination.VENDOR, timeout=TIMEOUT_SECONDS, transport=transport
    ) as client:
        try:
            response = await client.post(
                f"{GITHUB}/{repo}.git/git-upload-pack",
                content=body,
                headers={
                    "Content-Type": "application/x-git-upload-pack-request",
                    "Accept": "application/x-git-upload-pack-result",
                    "Git-Protocol": "version=2",
                    "User-Agent": "git/2 agentarea",
                },
            )
        except httpx.RequestError as e:
            raise GitHubGitError(f"{what}: {e}") from e
    _check(response, what)
    if len(response.content) > MAX_LS_REFS_BYTES:
        raise GitHubGitError(f"{what}: GitHub answered more refs than asked for")
    found: dict[str, str] = {}
    for line in _pkt_lines(response.content):
        fields = line.split(" ")
        if len(fields) < 2 or not _GIT_SHA.fullmatch(fields[0]):
            continue
        peeled = next((f[7:] for f in fields[2:] if f.startswith("peeled:")), None)
        found[fields[1]] = peeled if peeled and _GIT_SHA.fullmatch(peeled) else fields[0]
    for name in wanted:
        if name in found:
            return found[name]
    raise GitHubGitNotFoundError(f"{repo} has no branch or tag {ref!r}")


async def _download_archive(
    repo: str, commit: str, *, max_bytes: int, transport: httpx.AsyncBaseTransport | None
) -> bytes:
    global _archive_bytes
    cached = _archives.get((repo, commit))
    if cached is not None:
        _archives.move_to_end((repo, commit))
        if len(cached) > max_bytes:
            raise GitHubArchiveTooLargeError(f"{repo} at {commit} is larger than {max_bytes} bytes")
        return cached
    what = f"{repo} at {commit}"
    body = bytearray()
    async with outbound_client(
        Destination.VENDOR, timeout=TIMEOUT_SECONDS, transport=transport
    ) as client:
        try:
            async with client.stream(
                "GET",
                f"{CODELOAD}/{repo}/tar.gz/{quote(commit)}",
                headers={"User-Agent": "agentarea"},
            ) as response:
                _check(response, what)
                async for chunk in response.aiter_bytes():
                    body += chunk
                    if len(body) > max_bytes:
                        raise GitHubArchiveTooLargeError(
                            f"{what} is larger than {max_bytes // (1024 * 1024)} MB compressed"
                        )
        except httpx.RequestError as e:
            raise GitHubGitError(f"{what}: {e}") from e
    data = bytes(body)
    if len(data) <= ARCHIVE_CACHE_MAX_BYTES:
        replaced = _archives.pop((repo, commit), None)
        if replaced is not None:
            _archive_bytes -= len(replaced)
        _archives[(repo, commit)] = data
        _archive_bytes += len(data)
        while _archive_bytes > ARCHIVE_CACHE_MAX_BYTES:
            _, evicted = _archives.popitem(last=False)
            _archive_bytes -= len(evicted)
    return data


def _unpack(
    data: bytes,
    *,
    prefix: str,
    keep: Callable[[str, str], bool],
    max_kept_bytes: int | None,
    max_kept_files: int | None,
    what: str,
) -> dict[str, GitFile]:
    files: dict[str, GitFile] = {}
    kept_bytes = kept_files = unpacked = members = 0
    root: str | None = None
    under = f"{prefix}/" if prefix else ""
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for member in tar:
                members += 1
                if members > MAX_ARCHIVE_MEMBERS:
                    raise GitHubArchiveTooLargeError(
                        f"{what} holds more than {MAX_ARCHIVE_MEMBERS} entries"
                    )
                if member.isfile():
                    # Skipping a member of a gzip stream still inflates it, so
                    # every file counts, inside the prefix or not.
                    unpacked += member.size
                    if unpacked > MAX_ARCHIVE_UNPACKED_BYTES:
                        raise GitHubArchiveTooLargeError(f"{what} unpacks to too much")
                if root is None:
                    root = member.name.split("/", 1)[0] + "/"
                if not member.name.startswith(root):
                    continue
                path = member.name[len(root) :]
                if not path.startswith(under) or not (member.isfile() or member.issym()):
                    continue
                rel = path[len(under) :]
                if member.issym():
                    content = member.linkname.encode("utf-8")
                    mode = SYMLINK_MODE
                else:
                    stream = tar.extractfile(member)
                    content = stream.read() if stream is not None else b""
                    mode = "100755" if member.mode & 0o111 else "100644"
                kept = keep(rel, mode)
                if kept:
                    kept_files += 1
                    kept_bytes += len(content)
                    if max_kept_files is not None and kept_files > max_kept_files:
                        raise GitHubArchiveTooLargeError(
                            f"{what} holds more than {max_kept_files} files under {prefix or '/'}"
                        )
                    if max_kept_bytes is not None and kept_bytes > max_kept_bytes:
                        raise GitHubArchiveTooLargeError(
                            f"{what} holds more than {max_kept_bytes // (1024 * 1024)} MB "
                            f"under {prefix or '/'}"
                        )
                files[rel] = GitFile(mode, git_blob_sha(content), content if kept else None)
    except (tarfile.TarError, EOFError, OSError) as e:
        raise GitHubGitError(f"{what}: the archive is not readable ({e})") from e
    return files


async def read_archive(
    repo: str,
    commit: str,
    *,
    prefix: str,
    keep: Callable[[str, str], bool] = lambda _path, _mode: True,
    max_kept_bytes: int | None = None,
    max_kept_files: int | None = None,
    max_archive_bytes: int = MAX_ARCHIVE_BYTES,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, GitFile]:
    """Every file of ``repo`` at ``commit`` under ``prefix``, by path relative to it.

    Every file is hashed; ``keep(path, mode)`` decides whose bytes are
    returned, and only those count against ``max_kept_*``. Git's own content
    (links as their target, executables by mode) is what is hashed, so the
    result gives the folder's tree SHA through :func:`git_tree_shas`.
    """
    _checked_repo(repo)
    if not _GIT_SHA.fullmatch(commit):
        raise GitHubGitError(f"Not a commit: {commit!r}")
    data = await _download_archive(repo, commit, max_bytes=max_archive_bytes, transport=transport)
    # Decompressing and hashing is CPU work: off the event loop.
    return await asyncio.to_thread(
        _unpack,
        data,
        prefix=prefix.strip("/"),
        keep=keep,
        max_kept_bytes=max_kept_bytes,
        max_kept_files=max_kept_files,
        what=f"{repo} at {commit}",
    )
