"""Parser tests for RegistryService catalog source formats.

Covers the pure-function parsing layer for all registry types.
DB-coupled entity creation is verified in operator handler tests and the
end-to-end minikube smoke test.
"""

from agentarea_registry.application.service import (
    VALID_REGISTRY_TYPES,
    RegistryService,
)


class TestValidTypes:
    def test_includes_mcp_and_skills(self):
        assert "mcp_servers" in VALID_REGISTRY_TYPES
        assert "skills" in VALID_REGISTRY_TYPES

    def test_includes_llm_catalog_types(self):
        assert "llm_providers" in VALID_REGISTRY_TYPES
        assert "llm_models" in VALID_REGISTRY_TYPES

    def test_includes_default_agents(self):
        assert "default_agents" in VALID_REGISTRY_TYPES


class TestParseLLMProviders:
    def test_basic_provider(self):
        data = {
            "providers": [
                {
                    "provider_key": "openai",
                    "name": "OpenAI",
                    "description": "GPT models",
                    "provider_type": "openai",
                    "icon": "openai.svg",
                }
            ]
        }

        items = RegistryService._parse_llm_providers(data)

        assert len(items) == 1
        item = items[0]
        assert item["external_id"] == "openai"
        assert item["name"] == "OpenAI"
        assert item["description"] == "GPT models"
        assert item["spec"]["provider_key"] == "openai"
        assert item["spec"]["provider_type"] == "openai"
        assert item["spec"]["icon"] == "openai.svg"

    def test_skips_entries_without_provider_key(self):
        data = {"providers": [{"name": "Missing key"}, {"provider_key": "ok", "name": "OK"}]}

        items = RegistryService._parse_llm_providers(data)

        assert len(items) == 1
        assert items[0]["external_id"] == "ok"

    def test_empty_when_no_providers_key(self):
        assert RegistryService._parse_llm_providers({}) == []
        assert RegistryService._parse_llm_providers({"providers": []}) == []

    def test_preserves_is_builtin_flag(self):
        data = {
            "providers": [
                {"provider_key": "p1", "name": "P1", "provider_type": "t", "is_builtin": False}
            ]
        }
        items = RegistryService._parse_llm_providers(data)
        assert items[0]["spec"]["is_builtin"] is False


class TestParseLLMModels:
    def test_basic_model(self):
        data = {
            "models": [
                {
                    "provider_key": "openai",
                    "model_name": "gpt-4o",
                    "display_name": "GPT-4o",
                    "description": "Latest GPT-4 model",
                    "context_window": 128000,
                }
            ]
        }

        items = RegistryService._parse_llm_models(data)

        assert len(items) == 1
        item = items[0]
        assert item["external_id"] == "openai/gpt-4o"
        assert item["name"] == "GPT-4o"
        assert item["spec"]["provider_key"] == "openai"
        assert item["spec"]["model_name"] == "gpt-4o"
        assert item["spec"]["context_window"] == 128000

    def test_skips_entries_missing_provider_or_model(self):
        data = {
            "models": [
                {"provider_key": "openai"},
                {"model_name": "solo"},
                {"provider_key": "openai", "model_name": "gpt-4o"},
            ]
        }
        items = RegistryService._parse_llm_models(data)
        assert len(items) == 1
        assert items[0]["external_id"] == "openai/gpt-4o"

    def test_preserves_optional_fields(self):
        data = {
            "models": [
                {
                    "provider_key": "anthropic",
                    "model_name": "claude-3-opus",
                    "display_name": "Claude 3 Opus",
                    "max_output_tokens": 8192,
                    "supports_function_calling": True,
                }
            ]
        }
        items = RegistryService._parse_llm_models(data)
        spec = items[0]["spec"]
        assert spec["max_output_tokens"] == 8192
        assert spec["supports_function_calling"] is True

    def test_display_name_defaults_to_model_name(self):
        data = {"models": [{"provider_key": "p", "model_name": "m"}]}
        items = RegistryService._parse_llm_models(data)
        assert items[0]["name"] == "m"


class TestParseDefaultAgents:
    def test_basic_agent(self):
        data = {
            "agents": [
                {
                    "id": "00000000-0000-0000-0000-000000000001",
                    "name": "Default Agent",
                    "description": "System default",
                    "instruction": "Be helpful.",
                    "tools": [],
                }
            ]
        }

        items = RegistryService._parse_default_agents(data)

        assert len(items) == 1
        item = items[0]
        assert item["external_id"] == "00000000-0000-0000-0000-000000000001"
        assert item["name"] == "Default Agent"
        assert item["spec"]["instruction"] == "Be helpful."
        assert item["spec"]["tools"] == []

    def test_external_id_falls_back_to_name_when_id_missing(self):
        data = {"agents": [{"name": "Helper", "instruction": "Help."}]}
        items = RegistryService._parse_default_agents(data)
        assert items[0]["external_id"] == "Helper"

    def test_skips_agents_without_name(self):
        data = {"agents": [{"instruction": "x"}, {"name": "keep"}]}
        items = RegistryService._parse_default_agents(data)
        assert len(items) == 1
        assert items[0]["name"] == "keep"

    def test_preserves_tools_as_list_of_dicts(self):
        data = {
            "agents": [
                {
                    "name": "WithTools",
                    "tools": [
                        {"type": "mcp", "name": "filesystem"},
                        {"type": "code", "name": "python"},
                    ],
                }
            ]
        }
        items = RegistryService._parse_default_agents(data)
        tools = items[0]["spec"]["tools"]
        assert len(tools) == 2
        assert tools[0]["type"] == "mcp"


class TestParseSourceDispatch:
    def test_dispatches_llm_providers(self):
        result = RegistryService._parse_source(
            "llm_providers", {"providers": [{"provider_key": "p", "name": "P"}]}
        )
        assert result[0]["external_id"] == "p"

    def test_dispatches_llm_models(self):
        result = RegistryService._parse_source(
            "llm_models", {"models": [{"provider_key": "p", "model_name": "m"}]}
        )
        assert result[0]["external_id"] == "p/m"

    def test_dispatches_default_agents(self):
        result = RegistryService._parse_source(
            "default_agents", {"agents": [{"name": "A"}]}
        )
        assert result[0]["name"] == "A"

    def test_unknown_type_raises(self):
        import pytest

        with pytest.raises(ValueError, match="Unknown registry_type"):
            RegistryService._parse_source("bogus", {})
