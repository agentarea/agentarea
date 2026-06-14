"""Tests for the SkillParser."""

import io
import zipfile

import pytest

from agentarea_agents.application.skill_parser import (
    ParsedSkill,
    SkillPackageManifest,
    SkillParser,
)


class TestSkillParserParseContent:
    """Tests for parsing skill content."""

    def test_parse_content_with_frontmatter(self):
        """Test parsing content with valid YAML frontmatter."""
        parser = SkillParser()
        content = """---
name: test-skill
description: A test skill
allowed-tools:
  - kubectl
  - helm
---
# Test Skill

This is the skill content.
"""
        result = parser.parse_content(content)

        assert isinstance(result, ParsedSkill)
        assert result.metadata.name == "test-skill"
        assert result.metadata.description == "A test skill"
        assert result.metadata.allowed_tools == ["kubectl", "helm"]
        assert "# Test Skill" in result.content
        assert result.raw_content == content

    def test_parse_content_preserves_raw_frontmatter(self):
        """Test raw frontmatter preserves all fields."""
        parser = SkillParser()
        content = """---
name: Frontmatter Skill
description: Example
allowed-tools:
  - curl
license: Apache-2.0
custom-field: custom
---
# Frontmatter Skill
"""
        result = parser.parse_content(content)

        assert result.metadata.raw_frontmatter["name"] == "Frontmatter Skill"
        assert result.metadata.raw_frontmatter["license"] == "Apache-2.0"
        assert result.metadata.raw_frontmatter["custom-field"] == "custom"

    def test_parse_content_without_name_extracts_from_heading(self):
        """Test that name is extracted from first heading if not in frontmatter."""
        parser = SkillParser()
        content = """---
description: A skill without name in frontmatter
---
# My Skill Name

Content here.
"""
        result = parser.parse_content(content)

        assert result.metadata.name == "My Skill Name"

    def test_parse_content_without_frontmatter(self):
        """Test parsing content without any frontmatter."""
        parser = SkillParser()
        content = """# Simple Skill

Just some instructions.
"""
        result = parser.parse_content(content)

        assert result.metadata.name == "Simple Skill"
        assert result.metadata.description is None
        assert result.metadata.allowed_tools == []

    def test_parse_content_unnamed_skill(self):
        """Test parsing content with no name or heading."""
        parser = SkillParser()
        content = """Some content without a heading."""

        result = parser.parse_content(content)

        assert result.metadata.name == "Unnamed Skill"

    def test_parse_content_empty_allowed_tools(self):
        """Test that empty allowed-tools is handled."""
        parser = SkillParser()
        content = """---
name: test-skill
allowed-tools:
---
Content
"""
        result = parser.parse_content(content)

        assert result.metadata.allowed_tools == []


class TestSkillParserFindMainSkillFile:
    """Tests for finding the main skill file."""

    def test_find_skill_md_exact_match(self):
        """Test finding SKILL.md in root."""
        parser = SkillParser()
        files = ["SKILL.md", "templates/deploy.yaml", "README.md"]

        result = parser.find_main_skill_file(files)

        assert result == "SKILL.md"

    def test_find_skill_md_case_insensitive(self):
        """Test finding skill.md (lowercase)."""
        parser = SkillParser()
        files = ["skill.md", "other.txt"]

        result = parser.find_main_skill_file(files)

        assert result == "skill.md"

    def test_find_skill_md_mixed_case(self):
        """Test finding Skill.md (mixed case)."""
        parser = SkillParser()
        files = ["Skill.md", "README.md"]

        result = parser.find_main_skill_file(files)

        assert result == "Skill.md"

    def test_find_no_skill_file(self):
        """Test when no skill file is found."""
        parser = SkillParser()
        files = ["config.yaml", "scripts/run.sh"]

        result = parser.find_main_skill_file(files)

        assert result is None

    def test_find_prioritizes_skill_md_over_other_md(self):
        """Test that SKILL.md is prioritized over other .md files."""
        parser = SkillParser()
        files = ["README.md", "SKILL.md", "CHANGELOG.md"]

        result = parser.find_main_skill_file(files)

        assert result == "SKILL.md"

    def test_ignores_nested_skill_files(self):
        """Test that nested skill files are ignored for main file detection."""
        parser = SkillParser()
        files = ["docs/SKILL.md", "README.md"]

        result = parser.find_main_skill_file(files)

        assert result is None


class TestSkillParserBuildManifest:
    """Tests for building package manifests."""

    def test_build_manifest_from_paths(self):
        """Test building manifest from file paths."""
        parser = SkillParser()
        paths = ["SKILL.md", "templates/deploy.yaml", "examples/config.json"]
        sizes = {"SKILL.md": 100, "templates/deploy.yaml": 200, "examples/config.json": 50}

        result = parser.build_manifest_from_paths(paths, sizes)

        assert isinstance(result, SkillPackageManifest)
        assert result.main_skill_path == "SKILL.md"
        assert len(result.files) == 3
        assert result.total_size == 350

        # Check main skill file is marked
        main_file = next(f for f in result.files if f.path == "SKILL.md")
        assert main_file.is_main_skill is True

    def test_build_manifest_from_zip(self):
        """Test building manifest from a ZIP file."""
        parser = SkillParser()

        # Create a test ZIP file in memory
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("SKILL.md", "# Test Skill\n\nContent")
            zf.writestr("templates/deploy.yaml", "apiVersion: v1")

        zip_buffer.seek(0)

        result = parser.build_manifest_from_zip(zip_buffer)

        assert result.main_skill_path == "SKILL.md"
        assert len(result.files) == 2

    def test_build_manifest_from_zip_with_root_folder(self):
        """Test building manifest from ZIP with common root folder (GitHub style)."""
        parser = SkillParser()

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("repo-main/SKILL.md", "# Test")
            zf.writestr("repo-main/templates/deploy.yaml", "content")

        zip_buffer.seek(0)

        result = parser.build_manifest_from_zip(zip_buffer)

        # Should strip the root folder
        assert result.main_skill_path == "SKILL.md"
        file_paths = [f.path for f in result.files]
        assert "SKILL.md" in file_paths
        assert "templates/deploy.yaml" in file_paths

    def test_build_manifest_skips_macosx_folder(self):
        """Test that __MACOSX folder is skipped."""
        parser = SkillParser()

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("SKILL.md", "# Test")
            zf.writestr("__MACOSX/._SKILL.md", "metadata")

        zip_buffer.seek(0)

        result = parser.build_manifest_from_zip(zip_buffer)

        file_paths = [f.path for f in result.files]
        assert "__MACOSX/._SKILL.md" not in file_paths
        assert len(result.files) == 1


class TestSkillParserExtractFromZip:
    """Tests for extracting and parsing skills from ZIP files."""

    def test_extract_main_skill_from_zip(self):
        """Test extracting and parsing main skill from ZIP."""
        parser = SkillParser()

        skill_content = """---
name: deploy-app
description: Deploy application
allowed-tools: [kubectl]
---
# Deploy

Steps to deploy.
"""

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("SKILL.md", skill_content)
            zf.writestr("templates/deploy.yaml", "apiVersion: v1")

        zip_buffer.seek(0)

        parsed, manifest = parser.extract_main_skill_from_zip(zip_buffer)

        assert parsed.metadata.name == "deploy-app"
        assert parsed.metadata.description == "Deploy application"
        assert manifest.main_skill_path == "SKILL.md"

    def test_extract_from_zip_without_skill_file_raises(self):
        """Test that extracting from ZIP without skill file raises ValueError."""
        parser = SkillParser()

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("config.yaml", "key: value")

        zip_buffer.seek(0)

        with pytest.raises(ValueError, match="No SKILL.md found at package root"):
            parser.extract_main_skill_from_zip(zip_buffer)

    def test_extract_from_zip_with_only_readme_raises(self):
        """Test that ZIP with only README.md is rejected."""
        parser = SkillParser()

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("README.md", "# Readme")

        zip_buffer.seek(0)

        with pytest.raises(ValueError, match="No SKILL.md found at package root"):
            parser.extract_main_skill_from_zip(zip_buffer)

    def test_extract_from_zip_with_github_style_root(self):
        """Test extracting from GitHub-style ZIP with root folder."""
        parser = SkillParser()

        skill_content = """---
name: github-skill
---
# GitHub Skill
"""

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("owner-repo-abc123/SKILL.md", skill_content)
            zf.writestr("owner-repo-abc123/README.md", "# Readme")

        zip_buffer.seek(0)

        parsed, manifest = parser.extract_main_skill_from_zip(zip_buffer)

        assert parsed.metadata.name == "github-skill"
        assert manifest.main_skill_path == "SKILL.md"
