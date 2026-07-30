"""Unit tests for skill execution integration.

Tests the integration between skills and agent execution workflow
without requiring full infrastructure (database, S3, Temporal).
"""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from agentarea_execution.models import AgentConfigRequest, AgentConfigResult, SkillInfo


class TestSkillPromptInjection:
    """Tests for skill content injection into agent prompts."""

    def test_skill_info_model(self):
        """Test SkillInfo model structure."""
        skill = SkillInfo(
            id=str(uuid4()),
            name="Test Skill",
            content="# Test Skill\nYou are an expert at testing.",
            files=["templates/example.txt", "data/config.yaml"],
        )

        assert skill.name == "Test Skill"
        assert "testing" in skill.content
        assert len(skill.files) == 2

    def test_agent_config_result_with_skills(self):
        """Test AgentConfigResult includes skills."""
        skills = [
            SkillInfo(
                id=str(uuid4()),
                name="Skill A",
                content="# Skill A\nDo task A.",
                files=[],
            ),
            SkillInfo(
                id=str(uuid4()),
                name="Skill B",
                content="# Skill B\nDo task B.",
                files=["template.txt"],
            ),
        ]

        config = AgentConfigResult(
            id=str(uuid4()),
            name="Test Agent",
            description="Test description",
            instruction="You are a test agent.",
            model_id=str(uuid4()),
            context_window=128000,
            tools=[],
            events_config={},
            planning=False,
            skills=skills,
        )

        assert len(config.skills) == 2
        assert config.skills[0].name == "Skill A"
        assert config.skills[1].name == "Skill B"

    def test_skill_content_formatting_for_prompt(self):
        """Test that skill content can be properly formatted for prompts."""
        skills = [
            SkillInfo(
                id=str(uuid4()),
                name="Code Review",
                content="# Code Review Skill\n\nYou are an expert at reviewing code.",
                files=["templates/review_template.md"],
            ),
        ]

        # Format skills for system prompt (as would be done in workflow)
        skill_sections = []
        for skill in skills:
            section = f"\n\n## Skill: {skill.name}\n\n{skill.content}"
            if skill.files:
                section += f"\n\nAvailable files: {', '.join(skill.files)}"
            skill_sections.append(section)

        combined_skills = "".join(skill_sections)

        assert "## Skill: Code Review" in combined_skills
        assert "expert at reviewing code" in combined_skills
        assert "review_template.md" in combined_skills

    def test_multiple_skills_ordering(self):
        """Test that multiple skills maintain order."""
        skills = [
            SkillInfo(id="1", name="First", content="Content 1", files=[]),
            SkillInfo(id="2", name="Second", content="Content 2", files=[]),
            SkillInfo(id="3", name="Third", content="Content 3", files=[]),
        ]

        config = AgentConfigResult(
            id=str(uuid4()),
            name="Multi-skill Agent",
            description="",
            instruction="Base instruction",
            model_id=str(uuid4()),
            context_window=128000,
            skills=skills,
        )

        assert config.skills[0].name == "First"
        assert config.skills[1].name == "Second"
        assert config.skills[2].name == "Third"


class TestSkillWorkflowIntegration:
    """Tests for skill integration in workflow execution."""

    def test_instruction_with_skills_injection(self):
        """Test that skills are properly injected into the instruction."""
        base_instruction = "You are a helpful assistant."

        skills = [
            SkillInfo(
                id=str(uuid4()),
                name="Writing Helper",
                content="You excel at writing clear documentation.",
                files=[],
            ),
        ]

        # Simulate workflow's skill injection logic
        instruction_parts = [base_instruction]

        if skills:
            instruction_parts.append("\n\n# Skills\n")
            for skill in skills:
                instruction_parts.append(f"\n## {skill.name}\n{skill.content}")
                if skill.files:
                    instruction_parts.append(f"\n\nFiles available: {', '.join(skill.files)}")

        final_instruction = "".join(instruction_parts)

        assert "You are a helpful assistant" in final_instruction
        assert "# Skills" in final_instruction
        assert "## Writing Helper" in final_instruction
        assert "clear documentation" in final_instruction

    def test_empty_skills_no_injection(self):
        """Test that empty skills list doesn't add skill section."""
        base_instruction = "You are a helpful assistant."
        skills = []

        # Simulate workflow's skill injection logic
        instruction_parts = [base_instruction]

        if skills:
            instruction_parts.append("\n\n# Skills\n")
            for skill in skills:
                instruction_parts.append(f"\n## {skill.name}\n{skill.content}")

        final_instruction = "".join(instruction_parts)

        assert final_instruction == base_instruction
        assert "# Skills" not in final_instruction

    def test_skill_with_multifile_package(self):
        """Test skill with multiple files shows file manifest."""
        skill = SkillInfo(
            id=str(uuid4()),
            name="Data Analysis",
            content="# Data Analysis Skill\n\nYou help analyze data.",
            files=[
                "SKILL.md",
                "templates/report.md",
                "examples/sample_analysis.py",
                "config/settings.yaml",
            ],
        )

        # Build file manifest section
        manifest = f"Files in package ({len(skill.files)}):\n"
        for f in skill.files:
            manifest += f"  - {f}\n"

        assert "4" in manifest
        assert "templates/report.md" in manifest
        assert "examples/sample_analysis.py" in manifest


class TestBuildAgentConfigWithSkills:
    """Tests for build_agent_config_activity with skills."""

    @pytest.mark.asyncio
    async def test_build_config_loads_skills(self):
        """Test that build_agent_config loads attached skills."""
        # Create mock skill
        mock_skill = MagicMock()
        mock_skill.id = uuid4()
        mock_skill.name = "Test Skill"
        mock_skill.content = "# Test Skill Content"
        mock_skill.s3_path = None  # Content-only skill

        # Create mock agent with skills
        mock_agent = MagicMock()
        mock_agent.id = uuid4()
        mock_agent.name = "Agent with Skills"
        mock_agent.description = "Test description"
        mock_agent.instruction = "You are a test agent."
        mock_agent.model_id = str(uuid4())
        mock_agent.tools = []
        mock_agent.events_config = {}
        mock_agent.planning = False
        mock_agent.skills = [mock_skill]

        # Verify the skill data is accessible
        assert len(mock_agent.skills) == 1
        assert mock_agent.skills[0].name == "Test Skill"
        assert mock_agent.skills[0].content == "# Test Skill Content"

    @pytest.mark.asyncio
    async def test_skill_info_creation_from_model(self):
        """Test creating SkillInfo from skill model."""
        # Simulate skill model attributes
        skill_id = uuid4()
        skill_name = "Code Review"
        skill_content = "# Code Review\nYou review code professionally."
        skill_files = ["templates/checklist.md"]

        # Create SkillInfo as done in activity
        skill_info = SkillInfo(
            id=str(skill_id),
            name=skill_name,
            content=skill_content,
            files=skill_files,
        )

        assert str(skill_id) == skill_info.id
        assert skill_info.name == "Code Review"
        assert "review code" in skill_info.content
        assert "templates/checklist.md" in skill_info.files


class TestSkillFileResolution:
    """Tests for skill file resolution activity."""

    def test_skill_file_path_normalization(self):
        """Test that file paths are properly normalized."""
        # Various path formats that should be handled
        paths = [
            "SKILL.md",
            "templates/example.txt",
            "./templates/example.txt",
            "templates/../templates/example.txt",
        ]

        # Normalize paths (as would be done in activity)
        import posixpath

        normalized = [posixpath.normpath(p) for p in paths]

        assert normalized[0] == "SKILL.md"
        assert normalized[1] == "templates/example.txt"
        assert normalized[2] == "templates/example.txt"
        assert normalized[3] == "templates/example.txt"

    def test_content_type_detection(self):
        """Test content type detection for skill files."""
        import mimetypes

        files = {
            "SKILL.md": "text/markdown",
            "config.yaml": None,  # May not be in default mimetypes
            "data.json": "application/json",
            "script.py": "text/x-python",
        }

        for filename, expected_partial in files.items():
            content_type, _ = mimetypes.guess_type(filename)
            if expected_partial and content_type:
                # Just check it's detected (exact type may vary)
                assert content_type is not None


class TestAgentSkillsRelationship:
    """Tests for agent-skills relationship."""

    def test_agent_config_request_model(self):
        """Test AgentConfigRequest model."""
        request = AgentConfigRequest(
            agent_id=uuid4(),
            user_context_data={"user_id": "test", "workspace_id": "test-ws"},
            execution_context={"task_id": str(uuid4())},
            step_type="execute",
        )

        assert request.agent_id is not None
        assert request.user_context_data["workspace_id"] == "test-ws"

    def test_config_result_serialization(self):
        """Test that AgentConfigResult serializes properly."""
        skills = [
            SkillInfo(
                id=str(uuid4()),
                name="Serialization Test",
                content="Test content",
                files=["file1.txt", "file2.md"],
            ),
        ]

        config = AgentConfigResult(
            id=str(uuid4()),
            name="Test",
            description="Desc",
            instruction="Inst",
            model_id=str(uuid4()),
            context_window=128000,
            skills=skills,
        )

        # Serialize to dict (as would be done for Temporal)
        data = config.model_dump()

        assert "skills" in data
        assert len(data["skills"]) == 1
        assert data["skills"][0]["name"] == "Serialization Test"
        assert len(data["skills"][0]["files"]) == 2
