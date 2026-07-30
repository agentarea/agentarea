"""Parser tests for RegistryService catalog source formats.

Covers the pure-function parsing layer for all registry types.
DB-coupled entity creation is verified in operator handler tests and the
end-to-end minikube smoke test.
"""

import pytest
from agentarea_registry.application.service import (
    TYPE_BY_TOPLEVEL_KEY,
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

    def test_includes_agents(self):
        assert "agents" in VALID_REGISTRY_TYPES

    def test_includes_bundles(self):
        assert "bundles" in VALID_REGISTRY_TYPES


class TestDetectType:
    @pytest.mark.parametrize(("key", "expected"), list(TYPE_BY_TOPLEVEL_KEY.items()))
    def test_detects_each_type_from_its_key(self, key, expected):
        assert RegistryService._detect_type({key: []}) == expected

    def test_every_detectable_type_is_a_valid_registry_type(self):
        # Guards the mapping against drift: every detected type must be one
        # create_registry accepts, and every valid type must be detectable.
        assert set(TYPE_BY_TOPLEVEL_KEY.values()) == set(VALID_REGISTRY_TYPES)

    def test_detection_key_matches_parser_key(self):
        # The detection key for each type must be the same top-level key the
        # corresponding parser reads, or detection silently mis-routes. Feed a
        # one-item doc under the detected key and assert the parser sees it.
        sentinels = {
            "mcp_servers": {
                "servers": [
                    {
                        "server": {
                            "name": "x/y",
                            "remotes": [{"type": "streamable-http", "url": "https://x"}],
                        }
                    }
                ]
            },
            "skills": {"skills": [{"name": "x"}]},
            "llm_providers": {"providers": [{"provider_key": "x", "name": "X"}]},
            "llm_models": {"models": [{"provider_key": "x", "model_name": "m"}]},
            "agents": {"agents": [{"name": "x"}]},
        }
        for rtype, data in sentinels.items():
            assert RegistryService._detect_type(data) == rtype
            assert len(RegistryService._parse_source(rtype, data)) == 1

    def test_rejects_unknown_shape(self):
        with pytest.raises(ValueError, match="cannot detect registry type"):
            RegistryService._detect_type({"widgets": []})

    def test_rejects_non_mapping(self):
        with pytest.raises(ValueError, match="not a mapping"):
            RegistryService._detect_type([{"name": "x"}])

    def test_rejects_ambiguous_shape(self):
        with pytest.raises(ValueError, match="ambiguous"):
            RegistryService._detect_type({"servers": [], "skills": []})

    def test_ignores_non_list_key(self):
        # A key present but not a list must not trigger a match.
        with pytest.raises(ValueError, match="cannot detect registry type"):
            RegistryService._detect_type({"servers": {"not": "a list"}})


class TestParseMCPServers:
    def _telegram_entry(self):
        # Mirrors data/catalog/mcp-servers.json (standard MCP registry format,
        # pypi package → stdio command wrapped by mcp-bridge).
        return {
            "servers": [
                {
                    "server": {
                        "name": "ai.agentarea.catalog/telegram",
                        "title": "Telegram",
                        "description": "Telegram MCP server (Telethon).",
                        "version": "0.6.3",
                        "packages": [
                            {
                                "registryType": "pypi",
                                "identifier": "telegram-mcp",
                                "name": "telegram-mcp",
                                "version": "0.6.3",
                                "environmentVariables": [
                                    {"name": "TELEGRAM_API_ID", "required": True, "isSecret": True},
                                    {
                                        "name": "TELEGRAM_API_HASH",
                                        "required": True,
                                        "isSecret": True,
                                    },
                                    {
                                        "name": "TELEGRAM_SESSION_STRING",
                                        "required": True,
                                        "isSecret": True,
                                    },
                                    {
                                        "name": "TELEGRAM_EXPOSED_TOOLS",
                                        "required": False,
                                        "isSecret": False,
                                        "default": "read-only",
                                    },
                                ],
                            }
                        ],
                    },
                    "_meta": {"io.modelcontextprotocol.registry/official": {"isLatest": True}},
                }
            ]
        }

    def test_unrecognized_format_raises(self):
        with pytest.raises(ValueError, match="'server' key"):
            RegistryService._parse_mcp_servers(
                {"servers": [{"registry_id": "io.example/echo", "connection_type": "url"}]}
            )

    def test_pypi_package_parses_to_uvx_command(self):
        items = RegistryService._parse_mcp_servers(self._telegram_entry())

        # Only the pypi package → a single command-type item.
        assert len(items) == 1
        spec = items[0]["spec"]
        assert items[0]["name"] == "Telegram"
        assert items[0]["external_id"] == "ai.agentarea.catalog/telegram/command"
        assert spec["connection_type"] == "command"
        assert spec["command"] == "uvx"
        assert spec["args"] == ["telegram-mcp"]
        assert spec["transport"] == "stdio"

    def test_env_schema_preserved_for_ui_and_secret_routing(self):
        items = RegistryService._parse_mcp_servers(self._telegram_entry())
        env_schema = items[0]["spec"]["env_schema"]

        names = [e["name"] for e in env_schema]
        assert names == [
            "TELEGRAM_API_ID",
            "TELEGRAM_API_HASH",
            "TELEGRAM_SESSION_STRING",
            "TELEGRAM_EXPOSED_TOOLS",
        ]
        # Credentials route through the secret manager (isSecret) and are required.
        by_name = {e["name"]: e for e in env_schema}
        assert by_name["TELEGRAM_SESSION_STRING"]["isSecret"] is True
        assert by_name["TELEGRAM_SESSION_STRING"]["required"] is True
        # Read-only by default, user-overridable, not a secret.
        assert by_name["TELEGRAM_EXPOSED_TOOLS"]["default"] == "read-only"
        assert by_name["TELEGRAM_EXPOSED_TOOLS"]["isSecret"] is False


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
        assert items[0]["spec"]["context_window"] is None


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

        items = RegistryService._parse_agents(data)

        assert len(items) == 1
        item = items[0]
        assert item["external_id"] == "00000000-0000-0000-0000-000000000001"
        assert item["name"] == "Default Agent"
        assert item["spec"]["instruction"] == "Be helpful."
        assert item["spec"]["tools"] == []

    def test_external_id_falls_back_to_name_when_id_missing(self):
        data = {"agents": [{"name": "Helper", "instruction": "Help."}]}
        items = RegistryService._parse_agents(data)
        assert items[0]["external_id"] == "Helper"

    def test_skips_agents_without_name(self):
        data = {"agents": [{"instruction": "x"}, {"name": "keep"}]}
        items = RegistryService._parse_agents(data)
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
        items = RegistryService._parse_agents(data)
        tools = items[0]["spec"]["tools"]
        assert len(tools) == 2
        assert tools[0]["type"] == "mcp"

    def test_preferred_models_carried_into_spec(self):
        data = {"agents": [{"name": "A", "preferred_models": ["gpt-4o", "o3"]}]}
        items = RegistryService._parse_agents(data)
        spec = items[0]["spec"]
        assert spec["preferred_models"] == ["gpt-4o", "o3"]
        # The catalog never carries a runnable instance UUID under model_id.
        assert "model_id" not in spec


class TestParseBundles:
    def _bundle(self, **over):
        base = {
            "schema_version": "0.1.0",
            "name": "productivity-lite",
            "display_name": "Productivity Lite",
            "description": "A lightweight assistant.",
            "metadata": {"category": "productivity", "capabilities": ["interactive"]},
            "skills": [{"key": "s", "name": "S", "source_type": "content", "content": "# S"}],
            "agents": [{"key": "a", "name": "A", "model": "gpt-4o", "skills": ["s"]}],
        }
        base.update(over)
        return base

    def test_basic_bundle(self):
        items = RegistryService._parse_bundles({"bundles": [self._bundle()]})
        assert len(items) == 1
        item = items[0]
        # external_id is the stable bundle name (idempotency key), not display_name.
        assert item["external_id"] == "productivity-lite"
        assert item["name"] == "Productivity Lite"
        assert item["version"] == "0.1.0"
        # The whole canonical Bundle is preserved as spec so install runs unchanged.
        assert item["spec"]["agents"][0]["model"] == "gpt-4o"
        assert item["spec"]["skills"][0]["content"] == "# S"

    def test_name_used_when_no_display_name(self):
        items = RegistryService._parse_bundles({"bundles": [self._bundle(display_name=None)]})
        assert items[0]["name"] == "productivity-lite"

    def test_tags_fall_back_to_capabilities(self):
        items = RegistryService._parse_bundles({"bundles": [self._bundle()]})
        assert items[0]["tags"] == ["interactive"]

    def test_explicit_tags_win_over_capabilities(self):
        items = RegistryService._parse_bundles({"bundles": [self._bundle(tags=["ops"])]})
        assert items[0]["tags"] == ["ops"]

    def test_skips_bundles_without_name(self):
        data = {"bundles": [{"schema_version": "0.1.0"}, self._bundle()]}
        items = RegistryService._parse_bundles(data)
        assert len(items) == 1
        assert items[0]["external_id"] == "productivity-lite"

    def test_empty_when_no_bundles_key(self):
        assert RegistryService._parse_bundles({}) == []
        assert RegistryService._parse_bundles({"bundles": []}) == []


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

    def test_dispatches_agents(self):
        result = RegistryService._parse_source("agents", {"agents": [{"name": "A"}]})
        assert result[0]["name"] == "A"

    def test_dispatches_bundles(self):
        result = RegistryService._parse_source(
            "bundles", {"bundles": [{"name": "b", "schema_version": "0.1.0"}]}
        )
        assert result[0]["external_id"] == "b"

    def test_unknown_type_raises(self):
        import pytest

        with pytest.raises(ValueError, match="Unknown registry_type"):
            RegistryService._parse_source("bogus", {})
