"""A skill is a bundle of files, so activating one puts it in the sandbox.

The sandbox workspace persists for the life of the task, so the bundle is
uploaded once at activation and every later bash call sees it on disk. This is
what removes the need for a second execution tool: there is no skill-script
path to run, only files and one shell.
"""

from agentarea_execution.activities.skill_materialization import (
    assemble_skill_bundle,
    build_skill_input_files,
    skill_workspace_dir,
)


def test_a_skill_is_a_folder_that_always_has_a_manifest():
    # There is no "content-only" kind of skill. Prose is simply the SKILL.md
    # of a folder whose other files are optional.
    bundle = assemble_skill_bundle("# How to docx", [])
    assert bundle == [("SKILL.md", b"# How to docx")]


def test_manifest_is_added_alongside_bundled_files():
    bundle = assemble_skill_bundle("# Docs", [("generate.py", b"x")])
    assert bundle == [("SKILL.md", b"# Docs"), ("generate.py", b"x")]


def test_a_manifest_in_the_bundle_wins_over_stored_prose():
    bundle = assemble_skill_bundle("stale", [("SKILL.md", b"fresh")])
    assert bundle == [("SKILL.md", b"fresh")]


def test_manifest_match_is_case_insensitive():
    bundle = assemble_skill_bundle("stale", [("skill.md", b"fresh")])
    assert bundle == [("skill.md", b"fresh")]


def test_a_skill_with_neither_prose_nor_files_still_has_a_manifest():
    assert assemble_skill_bundle(None, []) == [("SKILL.md", b"")]


def test_directory_is_derived_from_the_skill_name():
    assert skill_workspace_dir("docx", "id-1").startswith("skills/docx-")


def test_directory_name_is_slugified():
    assert skill_workspace_dir("My Skill v2", "id-1").startswith("skills/my-skill-v2-")


def test_non_ascii_names_keep_their_identity():
    # Stripping every non-[a-z0-9] char collapsed each of these to the same
    # directory, so two skills would silently overwrite one another.
    assert skill_workspace_dir("Отчёт", "id-1") != skill_workspace_dir("План", "id-2")
    assert skill_workspace_dir("Отчёт", "id-1") == skill_workspace_dir("Отчёт", "id-1")


def test_names_that_slugify_to_nothing_stay_distinct():
    assert skill_workspace_dir("!!!", "id-1") != skill_workspace_dir("???", "id-2")


def test_degenerate_names_are_stable_across_calls():
    assert skill_workspace_dir("!!!", "id-1") == skill_workspace_dir("!!!", "id-1")


def test_every_directory_stays_under_the_skills_root():
    for name in ("Отчёт", "!!!", "../../etc", "", "ok"):
        assert skill_workspace_dir(name, "id-1").startswith("skills/")
        assert ".." not in skill_workspace_dir(name, "id-1")


def test_directory_never_escapes_the_skills_root():
    # A hostile or sloppy skill name must not write outside skills/.
    assert skill_workspace_dir("../../etc", "id-1").startswith("skills/etc-")
    assert skill_workspace_dir("/abs/path", "id-1").startswith("skills/abs-path-")


def test_unnamed_skill_still_gets_a_stable_directory():
    assert skill_workspace_dir("", "id-1").startswith("skills/skill-")


def test_files_are_placed_under_the_skill_directory():
    files = build_skill_input_files("docx", "id-1", [("generate.py", b"print(1)")])

    assert len(files) == 1
    assert files[0]["path"].startswith("skills/docx-")
    assert files[0]["path"].endswith("/generate.py")


def test_two_skills_whose_names_slugify_alike_never_share_a_directory():
    # "deploy_api" and "Deploy API" are both legal names that slugify to the
    # same string; sharing a directory would make the agent read one skill's
    # manifest and run the other's scripts, silently.
    assert skill_workspace_dir("deploy_api", "id-1") != skill_workspace_dir("Deploy API", "id-2")


def test_content_is_base64_encoded_for_transport():
    import base64

    files = build_skill_input_files("docx", "id-1", [("generate.py", b"print(1)")])
    assert base64.b64decode(files[0]["content_base64"]) == b"print(1)"


def test_nested_bundle_paths_are_preserved():
    files = build_skill_input_files("docx", "id-1", [("lib/util.py", b"x")])
    assert files[0]["path"].endswith("/lib/util.py")


def test_traversal_in_a_bundle_path_is_rejected():
    files = build_skill_input_files("docx", "id-1", [("../../evil.py", b"x"), ("ok.py", b"y")])
    assert len(files) == 1
    assert files[0]["path"].endswith("/ok.py")


def test_binary_content_survives():
    payload = bytes(range(256))
    files = build_skill_input_files("docx", "id-1", [("logo.png", payload)])

    import base64

    assert base64.b64decode(files[0]["content_base64"]) == payload


def test_empty_bundle_yields_nothing():
    assert build_skill_input_files("docx", "id-1", []) == []
