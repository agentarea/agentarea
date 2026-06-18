"""SkillsToolset — manage workspace skills as file packages.

A skill is a package of files (SKILL.md plus optional helpers). Three create
verbs cover authoring (file map), bulk import (ZIP), and external import
(GitHub). Mutation splits cleanly into ``edit_metadata`` and ``edit_content``
to avoid overloading; reads come in inline-text and presigned-URL flavors via
a single ``get_file`` verb.

Tool method signatures are explicit kwargs (MCP-idiomatic flat wire schema)
but the source of truth is the Pydantic DTOs in
``agentarea_agents.schemas.skills_dto`` — ``SkillCreateFromFiles``,
``SkillCreateFromArchive``, ``SkillImportFromGithub``, ``SkillEditMetadata``,
and ``SkillEditContent``. The contract test in
``tests/unit/test_mcp_rest_parity.py`` enforces parity.

This toolset is distinct from the SDK-side ``SkillActivationTool`` (in
``agentarea_agents_sdk.skills.skill_toolset``) — that one exposes a single
``activate_skill`` entry point for agents to load a skill into their context.
"""

import base64
import io
import json
import posixpath
import re
import zipfile
from typing import Any
from uuid import UUID

from agentarea_agents.schemas.skills_dto import (
    SkillCreateFromArchive,
    SkillCreateFromFiles,
    SkillEditContent,
    SkillEditMetadata,
    SkillImportFromGithub,
)
from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_definition import toolset

from .base import platform_context, platform_read_context

MAX_FILES = 200
MAX_INLINE_BYTES = 5 * 1024 * 1024  # 5 MB total across the file map
MAX_PATH_DEPTH = 10
MAX_GITHUB_SKILL_CANDIDATES = 50
MAX_GITHUB_IMPORTS = 10
MAX_GITHUB_REPO_ZIP_BYTES = 25 * 1024 * 1024
MAX_GITHUB_PACKAGE_FILES = 200
MAX_GITHUB_PACKAGE_BYTES = 10 * 1024 * 1024
FRONTMATTER_NAME_RE = re.compile(r"^name:\s*['\"]?(?P<name>[^'\"\n]+?)['\"]?\s*$", re.MULTILINE)
FRONTMATTER_DESCRIPTION_RE = re.compile(
    r"^description:\s*['\"]?(?P<description>[^'\"\n]+?)['\"]?\s*$",
    re.MULTILINE,
)


def _validate_files_payload(files: Any) -> str | None:
    """Return error message if invalid, otherwise None."""
    if not isinstance(files, dict) or not files:
        return "files must be a non-empty {path: text} map"
    if len(files) > MAX_FILES:
        return f"Too many files ({len(files)}); limit is {MAX_FILES}. Use create_from_archive for bulk."
    total = 0
    for path, text in files.items():
        if not isinstance(text, str):
            return f"file {path!r} value must be a string"
        if path.count("/") + 1 > MAX_PATH_DEPTH:
            return f"file {path!r} exceeds max path depth {MAX_PATH_DEPTH}"
        total += len(text.encode("utf-8"))
        if total > MAX_INLINE_BYTES:
            mb = MAX_INLINE_BYTES // (1024 * 1024)
            return (
                f"Total inline content exceeds {mb} MB limit. "
                "Use create_from_archive for bulk uploads."
            )
    return None


def _normalize_files(files: dict[str, str]) -> dict[str, str]:
    return {p.lstrip("/"): v for p, v in files.items()}


def _has_skill_md(files: dict[str, str]) -> bool:
    return any(k.lower() in ("skill.md", "skill.markdown") for k in files)


def _skill_summary(skill: Any) -> dict[str, Any]:
    return {
        "id": str(skill.id),
        "name": skill.name,
        "description": skill.description,
        "source_type": skill.source_type,
    }


def _frontmatter_name(content: str) -> str | None:
    match = FRONTMATTER_NAME_RE.search(content)
    return match.group("name").strip() if match else None


def _frontmatter_description(content: str) -> str | None:
    match = FRONTMATTER_DESCRIPTION_RE.search(content)
    return match.group("description").strip() if match else None


async def _fetch_text(url: str) -> str:
    import httpx

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


def _raw_github_url(owner: str, repo: str, branch: str, path: str) -> str:
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path.lstrip('/')}"


def _candidate_package_path(skill_md_path: str) -> str:
    package_path = posixpath.dirname(skill_md_path)
    return "" if package_path == "." else package_path


async def _list_github_skill_candidates(
    github_url: str,
) -> tuple[Any, str, list[dict[str, str | None]]]:
    """Return candidate skill packages found in a GitHub URL scope."""
    from agentarea_agents.infrastructure.github_skill_importer import GitHubSkillImporter

    importer = GitHubSkillImporter()
    repo_info = importer.parse_github_url(github_url)
    branch = repo_info.branch or await importer._get_default_branch(repo_info.owner, repo_info.repo)

    tree_url = (
        f"https://api.github.com/repos/{repo_info.owner}/{repo_info.repo}/git/trees/"
        f"{branch}?recursive=1"
    )
    tree = json.loads(await _fetch_text(tree_url))

    scope = (repo_info.path or "").strip("/")

    all_paths = [
        str(item.get("path"))
        for item in tree.get("tree", [])
        if isinstance(item, dict)
        and item.get("type") == "blob"
        and str(item.get("path", "")).lower().endswith("skill.md")
    ]
    if scope and scope.lower().endswith("skill.md"):
        paths = [path for path in all_paths if path == scope]
    elif scope:
        exact = f"{scope.rstrip('/')}/SKILL.md"
        if exact in all_paths:
            paths = [exact]
        else:
            prefix = f"{scope.rstrip('/')}/"
            paths = [path for path in all_paths if path.startswith(prefix)]
    else:
        paths = all_paths

    if not paths:
        raise ValueError(f"No SKILL.md found in GitHub repository: {github_url}")
    if len(paths) > MAX_GITHUB_SKILL_CANDIDATES:
        raise ValueError(
            f"Repository contains {len(paths)} SKILL.md candidates; "
            f"limit is {MAX_GITHUB_SKILL_CANDIDATES}. Use a more specific tree URL."
        )

    def sort_key(path: str) -> tuple[int, str]:
        return (0 if path.lower() == "skill.md" else 1, path)

    candidates: list[dict[str, str | None]] = []
    for path in sorted(paths, key=sort_key):
        raw_url = _raw_github_url(repo_info.owner, repo_info.repo, branch, path)
        content = await _fetch_text(raw_url)
        candidates.append(
            {
                "name": _frontmatter_name(content),
                "description": _frontmatter_description(content),
                "skill_path": path,
                "package_path": _candidate_package_path(path),
                "raw_url": raw_url,
            }
        )

    return repo_info, branch, candidates


def _select_github_candidates(
    candidates: list[dict[str, str | None]],
    *,
    selector: str | None,
    import_all: bool,
) -> list[dict[str, str | None]]:
    if import_all:
        return candidates

    if selector:
        wanted = selector.strip().lower()
        matches = [
            candidate
            for candidate in candidates
            if (candidate.get("name") or "").lower() == wanted
            or (candidate.get("package_path") or "").lower().endswith(f"/{wanted}")
            or (candidate.get("package_path") or "").lower() == wanted
        ]
        if not matches:
            raise ValueError(f"No SKILL.md with name or path {selector!r} found")
        if len(matches) > 1:
            raise ValueError(f"Multiple skills match {selector!r}; use a more specific path")
        return matches

    if len(candidates) == 1:
        return candidates

    raise ValueError("Multiple skills found")


async def _github_skill_package_zip(
    repo_zip_data: bytes,
    *,
    package_path: str | None,
) -> bytes:
    """Re-root one skill package from a GitHub repository ZIP."""
    package_prefix = f"{package_path.strip('/')}/" if package_path else ""

    out = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(repo_zip_data)) as source,
        zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target,
    ):
        selected: list[zipfile.ZipInfo] = []
        total_size = 0
        for info in source.infolist():
            if info.is_dir():
                continue
            parts = info.filename.split("/", 1)
            if len(parts) != 2:
                continue
            relative = parts[1]
            if package_prefix:
                if not relative.startswith(package_prefix):
                    continue
                relative = relative[len(package_prefix) :]
            if not relative or relative.startswith("__MACOSX/"):
                continue
            selected.append(info)
            total_size += info.file_size
            if len(selected) > MAX_GITHUB_PACKAGE_FILES:
                raise ValueError(
                    f"GitHub skill package contains more than {MAX_GITHUB_PACKAGE_FILES} files"
                )
            if total_size > MAX_GITHUB_PACKAGE_BYTES:
                mb = MAX_GITHUB_PACKAGE_BYTES // (1024 * 1024)
                raise ValueError(f"GitHub skill package exceeds {mb} MB uncompressed limit")

        for info in selected:
            relative = info.filename.split("/", 1)[1]
            if package_prefix:
                relative = relative[len(package_prefix) :]
            target.writestr(relative, source.read(info.filename))

    return out.getvalue()


@toolset(
    namespace="agentarea/skills",
    display_name="Skills",
    description="Manage workspace skills (multi-file authoring, GitHub import, archive upload).",
    category="platform",
)
class SkillsToolset(Toolset):
    """Manage skills end-to-end: create from files / archive / GitHub, edit
    metadata or content (mode-aware), browse and read package files, delete.
    """

    @tool_method
    async def list(self) -> str:
        """List all skills in the workspace."""
        async with platform_read_context() as (_session, user_ctx, repo_factory, _broker, _secret):
            from agentarea_agents.application.skill_service import SkillService

            service = SkillService(repository_factory=repo_factory, user_context=user_ctx)
            skills = await service.list()
            return json.dumps([_skill_summary(s) for s in skills], default=str)

    @tool_method
    async def get(self, skill_id: str) -> str:
        """Get details of a skill, including its primary SKILL.md content."""
        async with platform_read_context() as (_session, user_ctx, repo_factory, _broker, _secret):
            from agentarea_agents.application.skill_service import SkillService

            service = SkillService(repository_factory=repo_factory, user_context=user_ctx)
            skill = await service.get(UUID(skill_id))
            if not skill:
                return json.dumps({"error": "Skill not found"})
            payload = _skill_summary(skill)
            payload.update({"source_url": skill.source_url, "content": skill.content})
            return json.dumps(payload, default=str)

    @tool_method
    async def create(
        self,
        files: dict[str, str],
        name: str = "",
        description: str = "",
    ) -> str:
        """Create a manually authored skill from inline files; do not use for URL/GitHub installs.

        Must include SKILL.md. Limits: 200 files, 5 MB total. For larger or
        binary packages use create_from_archive. For public GitHub repositories
        or repository package URLs, prefer import_from_github so the original
        package files and source traceability are preserved. name/description
        default to YAML frontmatter parsed from SKILL.md.
        """
        err = _validate_files_payload(files)
        if err:
            return json.dumps({"error": err})
        normalized = _normalize_files(files)
        if not _has_skill_md(normalized):
            return json.dumps({"error": "files must include a SKILL.md at the root"})

        # The DTO is the source of truth for the wire schema. Build it after
        # the toolset-side limit checks so the LLM gets the more helpful
        # validation messages first; SkillCreateFromFiles still guards us
        # against shape drift.
        try:
            payload = SkillCreateFromFiles(
                files=normalized,
                name=name or None,
                description=description or None,
            )
        except ValueError as exc:
            return json.dumps({"error": str(exc)})

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for path, text in payload.files.items():
                zf.writestr(path, text)

        async with platform_context() as (_session, user_ctx, repo_factory, _broker, _secret):
            from agentarea_agents.application.skill_service import SkillService

            service = SkillService(repository_factory=repo_factory, user_context=user_ctx)
            skill = await service.create_from_zip(
                zip_data=buffer.getvalue(),
                name=payload.name,
                description=payload.description,
            )
            summary = _skill_summary(skill)
            summary["file_count"] = len(payload.files)
            return json.dumps(summary, default=str)

    @tool_method
    async def create_from_archive(
        self,
        zip_base64: str,
        name: str = "",
        description: str = "",
    ) -> str:
        """Create a skill from a base64-encoded ZIP archive. Use for binary
        helpers or pre-built bundles. For inline text-only packages prefer create().
        """
        # Validate the textual fields via the DTO; the binary blob is decoded
        # outside the model because Pydantic-validating raw base64 buys us
        # nothing here.
        try:
            payload = SkillCreateFromArchive(
                zip_base64=zip_base64,
                name=name or None,
                description=description or None,
            )
        except ValueError as exc:
            return json.dumps({"error": str(exc)})
        try:
            zip_bytes = base64.b64decode(payload.zip_base64, validate=True)
        except Exception as exc:
            return json.dumps({"error": f"Invalid base64: {exc}"})

        async with platform_context() as (_session, user_ctx, repo_factory, _broker, _secret):
            from agentarea_agents.application.skill_service import SkillService

            service = SkillService(repository_factory=repo_factory, user_context=user_ctx)
            skill = await service.create_from_zip(
                zip_data=zip_bytes,
                name=payload.name,
                description=payload.description,
            )
            return json.dumps(_skill_summary(skill), default=str)

    @tool_method
    async def import_from_github(
        self,
        github_url: str,
        name: str = "",
        description: str = "",
        skill_name: str = "",
        import_all: bool = False,
    ) -> str:
        """Import skill package(s) from a public GitHub repository URL.

        If the repository or tree contains multiple SKILL.md files, pass
        skill_name to choose one or import_all=true to import every candidate.
        Without either, the tool returns candidates instead of guessing.
        """
        try:
            payload = SkillImportFromGithub(
                github_url=github_url,
                name=name or None,
                description=description or None,
            )
        except ValueError as exc:
            return json.dumps({"error": str(exc)})

        return await self._import_github_packages(
            github_url=payload.github_url,
            source_url=payload.github_url,
            name=payload.name or "",
            description=payload.description or "",
            skill_name=skill_name,
            import_all=import_all,
        )

    async def _import_github_packages(
        self,
        *,
        github_url: str,
        source_url: str,
        name: str = "",
        description: str = "",
        skill_name: str = "",
        import_all: bool = False,
    ) -> str:
        candidates: list[dict[str, str | None]] = []
        try:
            _repo_info, _branch, candidates = await _list_github_skill_candidates(github_url)
            selected = _select_github_candidates(
                candidates,
                selector=skill_name or name or None,
                import_all=import_all,
            )
        except ValueError as exc:
            payload: dict[str, Any] = {"error": str(exc)}
            if str(exc) == "Multiple skills found":
                payload.update(
                    {
                        "code": "multiple_skills_found",
                        "candidates": candidates,
                        "hint": "Call import_from_github again with skill_name, "
                        "a more specific GitHub tree URL, or import_all=true.",
                    }
                )
            return json.dumps(payload)
        except Exception as exc:
            return json.dumps({"error": str(exc)})

        if len(selected) > MAX_GITHUB_IMPORTS:
            return json.dumps(
                {
                    "error": (
                        f"Refusing to import {len(selected)} GitHub skill packages; "
                        f"limit is {MAX_GITHUB_IMPORTS}. Use a more specific tree URL."
                    )
                }
            )

        try:
            from agentarea_agents.infrastructure.github_skill_importer import GitHubSkillImporter

            repo_zip_data = await GitHubSkillImporter().download_repo(github_url)
            if len(repo_zip_data) > MAX_GITHUB_REPO_ZIP_BYTES:
                mb = MAX_GITHUB_REPO_ZIP_BYTES // (1024 * 1024)
                return json.dumps({"error": f"GitHub repository ZIP exceeds {mb} MB limit"})
        except Exception as exc:
            return json.dumps({"error": str(exc)})

        created: list[dict[str, Any]] = []
        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            from agentarea_agents.application.skill_service import SkillService

            service = SkillService(repository_factory=repo_factory, user_context=_user_ctx)
            repo = service._get_repository()
            for candidate in selected:
                try:
                    zip_data = await _github_skill_package_zip(
                        repo_zip_data,
                        package_path=candidate.get("package_path") or "",
                    )
                except ValueError as exc:
                    return json.dumps({"error": str(exc)})
                skill = await service.create_from_zip(
                    zip_data=zip_data,
                    name=(name or None) if len(selected) == 1 else None,
                    description=(description or None) if len(selected) == 1 else None,
                )
                updated = await repo.update(str(skill.id), source_url=source_url)
                if updated is not None:
                    skill = updated
                summary = _skill_summary(skill)
                summary.update(
                    {
                        "source_url": source_url,
                        "resolved_source_url": candidate.get("raw_url"),
                        "package_path": candidate.get("package_path"),
                    }
                )
                created.append(summary)

        if len(created) == 1:
            return json.dumps(created[0], default=str)
        return json.dumps({"created": created, "count": len(created)}, default=str)

    @tool_method
    async def edit_metadata(
        self,
        skill_id: str,
        name: str = "",
        description: str = "",
    ) -> str:
        """Update a skill's name and/or description. Never touches files."""
        # Build patch with only the fields the caller actually set so we get
        # true PATCH semantics through SkillEditMetadata.model_dump(exclude_unset=True).
        patch: dict[str, str] = {}
        if name:
            patch["name"] = name
        if description:
            patch["description"] = description
        try:
            payload = SkillEditMetadata.model_validate(patch)
        except ValueError as exc:
            return json.dumps({"error": str(exc)})

        async with platform_context() as (_session, user_ctx, repo_factory, _broker, _secret):
            from agentarea_agents.application.skill_service import SkillService

            service = SkillService(repository_factory=repo_factory, user_context=user_ctx)
            skill = await service.update(UUID(skill_id), payload)
            if not skill:
                return json.dumps({"error": "Skill not found"})
            return json.dumps(
                {"id": str(skill.id), "name": skill.name, "description": skill.description},
                default=str,
            )

    @tool_method
    async def edit_content(self, skill_id: str, files: dict[str, str]) -> str:
        """Edit a skill's file content. Mode-aware:

        - Content-mode skill (single SKILL.md, no S3 package): only accepts a
          single ``SKILL.md`` entry; multi-file payloads are rejected (no
          silent promotion to package).
        - Package-mode skill: replaces the package in place — overwrites by
          path, deletes orphans not in the new map.
        """
        err = _validate_files_payload(files)
        if err:
            return json.dumps({"error": err})
        normalized = _normalize_files(files)

        # Validate the payload up front via the DTO so the wire schema and
        # service layer agree on shape (even though we dispatch to two
        # different service methods depending on skill mode).
        try:
            SkillEditContent(files=normalized)
        except ValueError as exc:
            return json.dumps({"error": str(exc)})

        async with platform_context() as (_session, user_ctx, repo_factory, _broker, _secret):
            from agentarea_agents.application.skill_service import SkillService

            service = SkillService(repository_factory=repo_factory, user_context=user_ctx)
            skill = await service.get(UUID(skill_id))
            if not skill:
                return json.dumps({"error": "Skill not found"})

            if skill.s3_path is None:
                # Content mode: only single SKILL.md allowed
                if len(normalized) != 1 or not _has_skill_md(normalized):
                    return json.dumps(
                        {
                            "error": (
                                "Skill is content-mode (single SKILL.md only). "
                                "Multi-file edits are not supported. To migrate to a "
                                "package, delete this skill and re-create with create()."
                            )
                        }
                    )
                key = next(iter(normalized))
                updated = await service.set_content(UUID(skill_id), normalized[key])
                return json.dumps(
                    {
                        "id": str(updated.id),
                        "mode": "content",
                        "files_written": ["SKILL.md"],
                    },
                    default=str,
                )

            # Package mode
            if not _has_skill_md(normalized):
                return json.dumps({"error": "files must include a SKILL.md at the root"})
            updated = await service.replace_package_from_files(UUID(skill_id), normalized)
            return json.dumps(
                {
                    "id": str(updated.id),
                    "mode": "package",
                    "files_written": sorted(normalized.keys()),
                },
                default=str,
            )

    @tool_method
    async def delete(self, skill_id: str) -> str:
        """Delete a skill and its file storage."""
        async with platform_context() as (_session, user_ctx, repo_factory, _broker, _secret):
            from agentarea_agents.application.skill_service import SkillService

            service = SkillService(repository_factory=repo_factory, user_context=user_ctx)
            deleted = await service.delete(UUID(skill_id))
            return json.dumps({"deleted": deleted})

    @tool_method
    async def list_files(self, skill_id: str, include_urls: bool = False) -> str:
        """List files inside a skill package. Set include_urls=True for bulk
        hydration with a presigned download URL per file (one round-trip).
        """
        async with platform_read_context() as (_session, user_ctx, repo_factory, _broker, _secret):
            from agentarea_agents.application.skill_service import SkillService

            service = SkillService(repository_factory=repo_factory, user_context=user_ctx)
            files = await service.get_skill_files(UUID(skill_id), include_urls=include_urls)
            return json.dumps(
                [
                    {"path": f.path, "size": f.size, **({"url": f.url} if f.url else {})}
                    for f in files
                ],
                default=str,
            )

    @tool_method
    async def get_file(
        self,
        skill_id: str,
        path: str,
        as_url: bool = False,
        expires_in: int = 3600,
    ) -> str:
        """Read one file from a skill package. Returns inline UTF-8 text by
        default; set as_url=True to receive a presigned download URL instead
        (use for binary files or large reads).
        """
        async with platform_read_context() as (_session, user_ctx, repo_factory, _broker, _secret):
            from agentarea_agents.application.skill_service import SkillService

            service = SkillService(repository_factory=repo_factory, user_context=user_ctx)
            if as_url:
                try:
                    url = await service.get_skill_file_url(
                        UUID(skill_id), path, expires_in=expires_in
                    )
                except ValueError as exc:
                    return json.dumps({"error": str(exc)})
                return json.dumps({"url": url, "path": path, "expires_in": expires_in})

            try:
                raw = await service.get_skill_file_content(UUID(skill_id), path)
            except (ValueError, FileNotFoundError) as exc:
                return json.dumps({"error": str(exc)})
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                return json.dumps(
                    {
                        "error": "binary file; retry with as_url=true",
                        "size": len(raw),
                    }
                )
            return json.dumps({"path": path, "content": text})
