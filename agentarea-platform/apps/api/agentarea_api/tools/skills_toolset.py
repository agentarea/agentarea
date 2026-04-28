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
        "has_files": skill.s3_path is not None,
    }


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
        """Create a skill from a file map (path -> text). Must include SKILL.md.

        Limits: 200 files, 5 MB total. For larger or binary packages use
        create_from_archive. name/description default to YAML frontmatter
        parsed from SKILL.md.
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
    ) -> str:
        """Import a skill package from a public GitHub repository URL."""
        try:
            payload = SkillImportFromGithub(
                github_url=github_url,
                name=name or None,
                description=description or None,
            )
        except ValueError as exc:
            return json.dumps({"error": str(exc)})

        async with platform_context() as (_session, user_ctx, repo_factory, _broker, _secret):
            from agentarea_agents.application.skill_service import SkillService

            service = SkillService(repository_factory=repo_factory, user_context=user_ctx)
            skill = await service.create_from_github(payload)
            summary = _skill_summary(skill)
            summary["source_url"] = skill.source_url
            return json.dumps(summary, default=str)

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
