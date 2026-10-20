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
import logging
import posixpath
import zipfile
from typing import Annotated, Any, Literal
from uuid import UUID

from agentarea_agents_sdk.tools.base_tool import ToolError
from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_authz import enforced_in_handler, requires, unrestricted
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_common.auth.resource_visibility import readable_resource_ids
from agentarea_governance.application.catalog_install import CatalogInstallRefusedError
from pydantic import BaseModel, Field

from agentarea_agents.application.skill_parser import parse_frontmatter
from agentarea_agents.infrastructure.github_skill_importer import extract_skill_package
from agentarea_agents.schemas.skills_dto import (
    SkillCreateFromArchive,
    SkillCreateFromFiles,
    SkillEditContent,
    SkillEditMetadata,
    SkillImportFromGithub,
)

from .platform_base import platform_context, platform_read_context

logger = logging.getLogger(__name__)

MAX_FILES = 200
MAX_INLINE_BYTES = 5 * 1024 * 1024  # 5 MB total across the file map
MAX_PATH_DEPTH = 10
MAX_GITHUB_SKILL_CANDIDATES = 50
MAX_GITHUB_IMPORTS = 10

SkillId = Annotated[str, Field(description="Skill id (UUID), from `skills_list` or a create call.")]
FileMap = Annotated[
    dict[str, str],
    Field(
        description=(
            "Package files as {relative path: UTF-8 text}, e.g. "
            '{"SKILL.md": "<markdown with YAML frontmatter>", "scripts/run.py": "<code>"}. '
            f"Must include SKILL.md at the root; at most {MAX_FILES} files, "
            f"{MAX_INLINE_BYTES // (1024 * 1024)} MB total, {MAX_PATH_DEPTH} path segments deep."
        )
    ),
]


class SkillSummary(BaseModel):
    id: str = Field(description="Skill id (UUID).")
    name: str = Field(description="Skill name.")
    description: str | None = Field(default=None, description="What the skill is for.")
    source_type: str = Field(description="How the skill was created: content, zip, github or path.")


class SkillDetail(SkillSummary):
    source_url: str | None = Field(
        default=None, description="Where the skill was imported from, e.g. a GitHub URL."
    )
    content: str | None = Field(default=None, description="The skill's SKILL.md markdown.")


class SkillCreated(SkillSummary):
    file_count: int = Field(description="Number of files stored in the package.")


class ImportedSkill(SkillSummary):
    source_url: str = Field(description="The GitHub URL the import was asked for.")
    resolved_source_url: str | None = Field(
        default=None, description="Raw URL of the SKILL.md this package was built from."
    )
    package_path: str | None = Field(
        default=None, description="Package directory inside the repository; empty for the root."
    )


class ImportedSkills(BaseModel):
    created: list[ImportedSkill] = Field(description="One entry per imported package.")
    count: int = Field(description="Number of skills created.")


class SkillMetadata(BaseModel):
    id: str = Field(description="Skill id (UUID).")
    name: str = Field(description="Skill name after the edit.")
    description: str | None = Field(default=None, description="Skill description after the edit.")


class SkillContentEdit(BaseModel):
    id: str = Field(description="Skill id (UUID).")
    mode: Literal["content", "package"] = Field(
        description="content: a single SKILL.md stored inline; package: a file tree in storage."
    )
    files_written: list[str] = Field(description="Paths written, sorted.")


class SkillDeleted(BaseModel):
    deleted: bool = Field(description="True when a skill was deleted; false when none matched.")


class SkillFileEntry(BaseModel):
    path: str = Field(description="Path inside the package, e.g. SKILL.md or scripts/run.py.")
    size: int = Field(description="Size in bytes.")
    url: str | None = Field(
        default=None, description="Presigned download URL; present only with include_urls=true."
    )


SkillFileEntries = list[SkillFileEntry]


class SkillFile(BaseModel):
    path: str = Field(description="Path inside the package.")
    content: str | None = Field(
        default=None, description="UTF-8 text of the file; present when as_url=false."
    )
    url: str | None = Field(
        default=None, description="Presigned download URL; present when as_url=true."
    )
    expires_in: int | None = Field(
        default=None, description="Seconds until the URL expires; present when as_url=true."
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


def _candidate_frontmatter(content: str) -> dict[str, str | None]:
    """Name and description as install will read them, or the parse error."""
    try:
        frontmatter, _body = parse_frontmatter(content)
    except ValueError as exc:
        logger.warning("SKILL.md candidate frontmatter does not parse", exc_info=True)
        return {"name": None, "description": None, "error": str(exc)}
    name = frontmatter.get("name")
    description = frontmatter.get("description")
    return {
        "name": name.strip() if isinstance(name, str) else None,
        "description": description.strip() if isinstance(description, str) else None,
    }


async def _fetch_text(url: str) -> str:
    from agentarea_common.utils.url_safety import safe_async_client

    async with safe_async_client(timeout=30.0, follow_redirects=True) as client:
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
                **_candidate_frontmatter(content),
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


@toolset(
    namespace="agentarea/skills",
    display_name="Skills",
    description="Manage workspace skills (multi-file authoring, GitHub import, archive upload).",
    category="platform",
    plane="build",
)
class SkillsToolset(Toolset):
    """Manage skills end-to-end: create from files / archive / GitHub, edit
    metadata or content (mode-aware), browse and read package files, delete.
    """

    open_world = False

    @tool_method(display_name="List skills", effect="read", output=list[SkillSummary])
    @enforced_in_handler("rows the graph says this caller may read; see readable_resource_ids")
    async def list(self) -> str:
        """List all skills in the workspace."""
        async with platform_read_context() as (_session, user_ctx, repo_factory, _broker, _secret):
            from agentarea_agents.application.skill_service import SkillService

            service = SkillService(repository_factory=repo_factory, user_context=user_ctx)
            skills = await service.list()
            readable = await readable_resource_ids(user_ctx.user_id)
            return json.dumps(
                [_skill_summary(s) for s in skills if str(s.id) in readable], default=str
            )

    @tool_method(display_name="Get skill", effect="read", output=SkillDetail)
    @requires("read", "skill", id_param="skill_id")
    async def get(self, skill_id: SkillId) -> str:
        """Get details of a skill, including its primary SKILL.md content."""
        async with platform_read_context() as (_session, user_ctx, repo_factory, _broker, _secret):
            from agentarea_agents.application.skill_service import SkillService

            service = SkillService(repository_factory=repo_factory, user_context=user_ctx)
            skill = await service.get(UUID(skill_id))
            if not skill:
                raise ToolError("Skill not found")
            payload = _skill_summary(skill)
            payload.update(
                {"source_url": skill.source_url, "content": await service.read_skill_md(skill)}
            )
            return json.dumps(payload, default=str)

    @tool_method(display_name="Create skill from files", effect="write", output=SkillCreated)
    @unrestricted("any member may create a skill, as POST /v1/skills allows")
    async def create(
        self,
        files: FileMap,
        name: Annotated[
            str,
            Field(
                description="Skill name, at most 255 characters; empty takes `name` "
                "from the SKILL.md frontmatter."
            ),
        ] = "",
        description: Annotated[
            str,
            Field(
                description="What the skill is for, at most 1000 characters; empty takes "
                "`description` from the SKILL.md frontmatter."
            ),
        ] = "",
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
            raise ToolError(err)
        normalized = _normalize_files(files)
        if not _has_skill_md(normalized):
            raise ToolError("files must include a SKILL.md at the root")

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
            raise ToolError(str(exc)) from exc

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

    @tool_method(display_name="Create skill from archive", effect="write", output=SkillSummary)
    @unrestricted("any member may create a skill, as POST /v1/skills/upload allows")
    async def create_from_archive(
        self,
        zip_base64: Annotated[
            str,
            Field(
                description="Standard base64 of a ZIP archive holding SKILL.md (at the root "
                "or in a single top-level folder) and any helper files."
            ),
        ],
        name: Annotated[
            str,
            Field(
                description="Skill name, at most 255 characters; empty takes `name` "
                "from the archive's SKILL.md frontmatter."
            ),
        ] = "",
        description: Annotated[
            str,
            Field(
                description="What the skill is for, at most 1000 characters; empty takes "
                "`description` from the archive's SKILL.md frontmatter."
            ),
        ] = "",
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
            raise ToolError(str(exc)) from exc
        try:
            zip_bytes = base64.b64decode(payload.zip_base64, validate=True)
        except Exception as exc:
            raise ToolError(f"Invalid base64: {exc}") from exc

        async with platform_context() as (_session, user_ctx, repo_factory, _broker, _secret):
            from agentarea_agents.application.skill_service import SkillService

            service = SkillService(repository_factory=repo_factory, user_context=user_ctx)
            skill = await service.create_from_zip(
                zip_data=zip_bytes,
                name=payload.name,
                description=payload.description,
            )
            return json.dumps(_skill_summary(skill), default=str)

    @tool_method(
        display_name="Import skill from GitHub",
        effect="write",
        open_world=True,
        output=ImportedSkill | ImportedSkills,
    )
    @unrestricted("any member may create a skill, as POST /v1/skills allows")
    async def import_from_github(
        self,
        github_url: Annotated[
            str,
            Field(
                description="Public GitHub URL: a repository "
                "(https://github.com/owner/repo), a tree path "
                "(https://github.com/owner/repo/tree/main/skills/foo) or a SKILL.md blob."
            ),
        ],
        name: Annotated[
            str,
            Field(
                description="Skill name, at most 255 characters; applies only when one "
                "package is imported. Empty takes the SKILL.md frontmatter. Also used to "
                "select a package when skill_name is empty."
            ),
        ] = "",
        description: Annotated[
            str,
            Field(
                description="Skill description, at most 1000 characters; applies only when "
                "one package is imported. Empty takes the SKILL.md frontmatter."
            ),
        ] = "",
        skill_name: Annotated[
            str,
            Field(
                description="Which package to import when the URL holds several SKILL.md "
                "files: a frontmatter name or package path, case-insensitive, from the "
                "`candidates` of a multiple_skills_found error."
            ),
        ] = "",
        import_all: Annotated[
            bool,
            Field(
                description=f"Import every SKILL.md package under the URL, at most "
                f"{MAX_GITHUB_IMPORTS}."
            ),
        ] = False,
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
            raise ToolError(str(exc)) from exc

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
            raise ToolError(json.dumps(payload)) from exc
        except Exception as exc:
            raise ToolError(str(exc)) from exc

        if len(selected) > MAX_GITHUB_IMPORTS:
            raise ToolError(
                f"Refusing to import {len(selected)} GitHub skill packages; "
                f"limit is {MAX_GITHUB_IMPORTS}. Use a more specific tree URL."
            )

        try:
            from agentarea_agents.infrastructure.github_skill_importer import GitHubSkillImporter

            repo_zip_data = await GitHubSkillImporter().download_repo(github_url)
        except Exception as exc:
            raise ToolError(str(exc)) from exc

        created: list[dict[str, Any]] = []
        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            from agentarea_agents.application.skill_service import SkillService

            service = SkillService(repository_factory=repo_factory, user_context=_user_ctx)
            try:
                await service.require_github_import_allowed()
            except CatalogInstallRefusedError as exc:
                raise ToolError(str(exc)) from exc
            repo = service._get_repository()
            for candidate in selected:
                try:
                    zip_data = extract_skill_package(
                        repo_zip_data,
                        package_path=candidate.get("package_path") or "",
                    )
                except ValueError as exc:
                    raise ToolError(str(exc)) from exc
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

    @tool_method(display_name="Edit skill metadata", effect="write", output=SkillMetadata)
    @requires("edit", "skill", id_param="skill_id")
    async def edit_metadata(
        self,
        skill_id: SkillId,
        name: Annotated[
            str, Field(description="New skill name, at most 255 characters; empty keeps it.")
        ] = "",
        description: Annotated[
            str,
            Field(description="New skill description, at most 1000 characters; empty keeps it."),
        ] = "",
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
            raise ToolError(str(exc)) from exc

        async with platform_context() as (_session, user_ctx, repo_factory, _broker, _secret):
            from agentarea_agents.application.skill_service import SkillService

            service = SkillService(repository_factory=repo_factory, user_context=user_ctx)
            skill = await service.update(UUID(skill_id), payload)
            if not skill:
                raise ToolError("Skill not found")
            return json.dumps(
                {"id": str(skill.id), "name": skill.name, "description": skill.description},
                default=str,
            )

    @tool_method(
        display_name="Edit skill files", effect="write", idempotent=True, output=SkillContentEdit
    )
    @requires("edit", "skill", id_param="skill_id")
    async def edit_content(self, skill_id: SkillId, files: FileMap) -> str:
        """Edit a skill's file content. Mode-aware:

        - Content-mode skill (single SKILL.md, no S3 package): only accepts a
          single ``SKILL.md`` entry; multi-file payloads are rejected (no
          silent promotion to package).
        - Package-mode skill: replaces the package in place — overwrites by
          path, deletes orphans not in the new map.
        """
        err = _validate_files_payload(files)
        if err:
            raise ToolError(err)
        normalized = _normalize_files(files)

        # Validate the payload up front via the DTO so the wire schema and
        # service layer agree on shape (even though we dispatch to two
        # different service methods depending on skill mode).
        try:
            SkillEditContent(files=normalized)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

        async with platform_context() as (_session, user_ctx, repo_factory, _broker, _secret):
            from agentarea_agents.application.skill_service import SkillService

            service = SkillService(repository_factory=repo_factory, user_context=user_ctx)
            skill = await service.get(UUID(skill_id))
            if not skill:
                raise ToolError("Skill not found")

            if skill.s3_path is None:
                # Content mode: only single SKILL.md allowed
                if len(normalized) != 1 or not _has_skill_md(normalized):
                    raise ToolError(
                        "Skill is content-mode (single SKILL.md only). "
                        "Multi-file edits are not supported. To migrate to a "
                        "package, delete this skill and re-create with create()."
                    )
                key = next(iter(normalized))
                updated = await service.set_content(UUID(skill_id), normalized[key])
                if updated is None:
                    raise ToolError(f"Skill {skill_id} not found")
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
                raise ToolError("files must include a SKILL.md at the root")
            updated = await service.replace_package_from_files(UUID(skill_id), normalized)
            return json.dumps(
                {
                    "id": str(updated.id),
                    "mode": "package",
                    "files_written": sorted(normalized.keys()),
                },
                default=str,
            )

    @tool_method(
        display_name="Delete skill", effect="destructive", idempotent=True, output=SkillDeleted
    )
    @requires("delete", "skill", id_param="skill_id")
    async def delete(self, skill_id: SkillId) -> str:
        """Delete a skill and its file storage."""
        async with platform_context() as (_session, user_ctx, repo_factory, _broker, _secret):
            from agentarea_agents.application.skill_service import SkillService

            service = SkillService(repository_factory=repo_factory, user_context=user_ctx)
            deleted = await service.delete(UUID(skill_id))
            return json.dumps({"deleted": deleted})

    @tool_method(display_name="List skill files", effect="read", output=SkillFileEntries)
    @unrestricted("package files, as GET /v1/skills/{id}/files serves them")
    async def list_files(
        self,
        skill_id: SkillId,
        include_urls: Annotated[
            bool,
            Field(description="Add a presigned download URL to each file, valid for 1 hour."),
        ] = False,
    ) -> str:
        """List files inside a skill package. Set include_urls=True for bulk
        hydration with a presigned download URL per file (one round-trip).
        """
        async with platform_read_context() as (_session, user_ctx, repo_factory, _broker, _secret):
            from agentarea_agents.application.skill_service import SkillService

            service = SkillService(repository_factory=repo_factory, user_context=user_ctx)
            try:
                files = await service.get_skill_files(
                    UUID(skill_id), include_urls=include_urls, to_run=True
                )
            except CatalogInstallRefusedError as exc:
                raise ToolError(str(exc)) from exc
            return json.dumps(
                [
                    {"path": f.path, "size": f.size, **({"url": f.url} if f.url else {})}
                    for f in files
                ],
                default=str,
            )

    @tool_method(display_name="Read skill file", effect="read", output=SkillFile)
    @unrestricted("package files, as GET /v1/skills/{id}/files/{path} serves them")
    async def get_file(
        self,
        skill_id: SkillId,
        path: Annotated[
            str,
            Field(
                description="File path inside the package, from `skills_list_files`, "
                "e.g. SKILL.md or scripts/run.py."
            ),
        ],
        as_url: Annotated[
            bool,
            Field(
                description="Return a presigned download URL instead of the text; needed "
                "for binary files."
            ),
        ] = False,
        expires_in: Annotated[
            int, Field(description="Lifetime of the URL in seconds; used only with as_url=true.")
        ] = 3600,
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
                        UUID(skill_id), path, expires_in=expires_in, to_run=True
                    )
                except (ValueError, CatalogInstallRefusedError) as exc:
                    raise ToolError(str(exc)) from exc
                return json.dumps({"url": url, "path": path, "expires_in": expires_in})

            try:
                raw = await service.get_skill_file_content(UUID(skill_id), path, to_run=True)
            except (ValueError, FileNotFoundError, CatalogInstallRefusedError) as exc:
                raise ToolError(str(exc)) from exc
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                raise ToolError(
                    json.dumps({"error": "binary file; retry with as_url=true", "size": len(raw)})
                ) from None
            return json.dumps({"path": path, "content": text})
