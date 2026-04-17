"""Parser tests for the RegistrySync reconcile module.

Pure-function tests — no DB, no K8s, no network.
"""

import pytest

from registry_sync import parse_source, VALID_TYPES


class TestValidTypes:
    def test_all_supported_types(self):
        assert set(VALID_TYPES) == {
            "mcp_servers",
            "skills",
            "llm_providers",
            "llm_models",
            "default_agents",
        }


class TestLLMProviderParser:
    def test_basic(self):
        items = parse_source(
            "llm_providers",
            {"providers": [{"provider_key": "openai", "name": "OpenAI"}]},
        )
        assert items[0]["external_id"] == "openai"
        assert items[0]["spec"]["provider_key"] == "openai"

    def test_skip_missing_key(self):
        items = parse_source(
            "llm_providers", {"providers": [{"name": "no key"}, {"provider_key": "ok"}]}
        )
        assert len(items) == 1
        assert items[0]["external_id"] == "ok"


class TestLLMModelParser:
    def test_basic(self):
        items = parse_source(
            "llm_models",
            {
                "models": [
                    {
                        "provider_key": "openai",
                        "model_name": "gpt-4o",
                        "context_window": 128000,
                    }
                ]
            },
        )
        assert items[0]["external_id"] == "openai/gpt-4o"
        assert items[0]["spec"]["context_window"] == 128000

    def test_skip_incomplete(self):
        items = parse_source(
            "llm_models",
            {
                "models": [
                    {"provider_key": "openai"},
                    {"model_name": "solo"},
                    {"provider_key": "p", "model_name": "m"},
                ]
            },
        )
        assert len(items) == 1


class TestDefaultAgentParser:
    def test_basic(self):
        items = parse_source(
            "default_agents",
            {
                "agents": [
                    {
                        "id": "00000000-0000-0000-0000-000000000001",
                        "name": "Helper",
                        "instruction": "Help.",
                        "tools": [{"type": "mcp", "name": "fs"}],
                    }
                ]
            },
        )
        assert items[0]["external_id"] == "00000000-0000-0000-0000-000000000001"
        assert items[0]["spec"]["instruction"] == "Help."
        assert items[0]["spec"]["tools"][0]["name"] == "fs"

    def test_external_id_falls_back_to_name(self):
        items = parse_source("default_agents", {"agents": [{"name": "X"}]})
        assert items[0]["external_id"] == "X"


class TestMCPServerParser:
    def test_legacy_format(self):
        items = parse_source(
            "mcp_servers",
            {
                "servers": [
                    {
                        "registry_id": "io.example/echo",
                        "connection_type": "url",
                        "json_spec": {"url": "https://example.com/mcp"},
                    }
                ]
            },
        )
        assert items[0]["external_id"] == "io.example/echo"


class TestSkillsParser:
    def test_basic(self):
        items = parse_source(
            "skills",
            {"skills": [{"name": "summarize", "content": "# Summarize"}]},
        )
        assert items[0]["external_id"] == "summarize"


class TestDispatchErrors:
    def test_unknown_type(self):
        with pytest.raises(ValueError, match="Unknown"):
            parse_source("bogus", {})
