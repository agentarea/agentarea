"""Turn a skill bundle into sandbox input files.

A skill is a directory of files. Activating one copies it into the task's
sandbox workspace, which persists across bash calls, so the agent reaches its
scripts with the ordinary shell instead of a bespoke execution tool.
"""

import base64
import re
from hashlib import sha256
from pathlib import PurePosixPath

SKILLS_ROOT = "skills"
SKILL_MANIFEST = "SKILL.md"


def assemble_skill_bundle(
    content: str | None, files: list[tuple[str, bytes]]
) -> list[tuple[str, bytes]]:
    """Assemble a skill's folder: always a manifest, everything else optional.

    A skill is a directory of files, so stored prose is not a different kind of
    skill — it is that directory's SKILL.md. Treating the two as separate kinds
    is what forced a second, bespoke execution path.
    """
    if any(PurePosixPath(path).name.lower() == SKILL_MANIFEST.lower() for path, _ in files):
        return files
    return [(SKILL_MANIFEST, (content or "").encode("utf-8")), *files]


def skill_workspace_dir(skill_name: str) -> str:
    """Sandbox directory holding a skill's bundle, always under the skills root.

    The slug keeps unicode letters and digits: reducing to ``[a-z0-9]`` collapsed
    every non-ASCII name to one directory, so two skills would silently overwrite
    each other's files. Names that carry no alphanumerics at all fall back to a
    digest of the name rather than a shared constant, for the same reason.
    """
    name = skill_name or ""
    # str.isalnum is unicode-aware, so "Отчёт" keeps its letters instead of
    # vanishing; every other run of characters becomes a single separator.
    slug = re.sub(r"-+", "-", "".join(c if c.isalnum() else "-" for c in name.lower())).strip("-")
    if not slug:
        slug = f"skill-{sha256(name.encode('utf-8')).hexdigest()[:8]}" if name else "skill"
    return f"{SKILLS_ROOT}/{slug}"


def build_skill_input_files(
    skill_name: str, files: list[tuple[str, bytes]]
) -> list[dict[str, str]]:
    """Lay a skill's files out under its sandbox directory, dropping unsafe paths."""
    directory = skill_workspace_dir(skill_name)
    input_files: list[dict[str, str]] = []

    for relative_path, content in files:
        clean = PurePosixPath((relative_path or "").replace("\\", "/"))
        parts = [p for p in clean.parts if p not in ("", ".")]
        if not parts or ".." in parts or clean.is_absolute():
            continue

        input_files.append(
            {
                "path": f"{directory}/{'/'.join(parts)}",
                "content_base64": base64.b64encode(content).decode("ascii"),
            }
        )

    return input_files
