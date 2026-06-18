"""Parser tests for the RegistrySync reconcile module.

Pure-function tests — no DB, no K8s, no network.
"""

import pytest

from registry_sync import _parse_bundles, _upsert_mcp_server, parse_source, VALID_TYPES


class TestValidTypes:
    def test_all_supported_types(self):
        assert set(VALID_TYPES) == {
            "mcp_servers",
            "skills",
            "llm_providers",
            "llm_models",
            "agents",
            "bundles",
        }


class TestBundleParser:
    def test_basic(self):
        items = parse_source(
            "bundles",
            {
                "bundles": [
                    {
                        "schema_version": "0.1.0",
                        "name": "productivity-lite",
                        "display_name": "Productivity Lite",
                        "description": "Plan your day.",
                        "metadata": {"capabilities": ["interactive"]},
                        "agents": [{"key": "a", "name": "A", "model": "gpt-4o"}],
                    }
                ]
            },
        )
        assert len(items) == 1
        assert items[0]["external_id"] == "productivity-lite"
        assert items[0]["name"] == "Productivity Lite"
        assert items[0]["version"] == "0.1.0"
        assert items[0]["spec"]["agents"][0]["model"] == "gpt-4o"
        assert items[0]["tags"] == ["interactive"]

    def test_skips_without_name(self):
        items = _parse_bundles({"bundles": [{"schema_version": "0.1.0"}]})
        assert items == []


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


class TestAgentParser:
    def test_basic(self):
        items = parse_source(
            "agents",
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
        items = parse_source("agents", {"agents": [{"name": "X"}]})
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

    def test_standard_format_preserves_raw_spec_icons(self):
        items = parse_source(
            "mcp_servers",
            {
                "servers": [
                    {
                        "server": {
                            "name": "io.example/echo",
                            "title": "Echo",
                            "description": "Echo server",
                            "version": "1.2.3",
                            "icons": [{"src": "/api/static/icons/mcp/echo.svg"}],
                            "remotes": [{"url": "https://example.com/mcp"}],
                            "packages": [
                                {
                                    "registryType": "npm",
                                    "name": "@example/echo",
                                    "version": "1.2.3",
                                }
                            ],
                        }
                    }
                ]
            },
        )

        assert [item["external_id"] for item in items] == [
            "io.example/echo",
            "io.example/echo/command",
        ]
        assert items[0]["spec"]["raw_spec"]["icons"][0]["src"] == (
            "/api/static/icons/mcp/echo.svg"
        )
        assert items[1]["spec"]["raw_spec"]["icons"][0]["src"] == (
            "/api/static/icons/mcp/echo.svg"
        )

    def test_upsert_writes_raw_spec_to_mcp_server_json_spec(self):
        class Result:
            def __init__(self, row=None):
                self.row = row

            def fetchone(self):
                return self.row

        class FakeConn:
            def __init__(self):
                self.calls = []

            def execute(self, statement, params=None):
                sql = str(statement)
                self.calls.append((sql, params or {}))
                if sql.startswith("SELECT id FROM mcp_servers"):
                    return Result(None)
                if sql.startswith("SELECT 1 FROM mcp_servers"):
                    return Result(None)
                return Result(None)

        raw_spec = {
            "name": "io.example/echo",
            "icons": [{"src": "https://cdn.example.com/echo.svg"}],
        }
        conn = FakeConn()
        _upsert_mcp_server(
            conn,
            {
                "name": "Echo",
                "description": "Echo server",
                "version": "1.2.3",
                "registry_url": "https://registry.example.com",
                "spec": {
                    "connection_type": "url",
                    "url": "https://example.com/mcp",
                    "transport": "streamable-http",
                    "raw_spec": raw_spec,
                },
                "tags": ["streamable-http"],
            },
            "workspace-1",
            "registry-item-1",
        )

        insert_params = next(
            params for sql, params in conn.calls if sql.startswith("INSERT INTO mcp_servers")
        )
        assert insert_params["json_spec"] == (
            '{"name": "io.example/echo", "icons": [{"src": "https://cdn.example.com/echo.svg"}]}'
        )
        assert insert_params["registry_url"] == "https://registry.example.com"
        assert insert_params["rid"] == "registry-item-1"
        assert insert_params["rurl"] == "https://example.com/mcp"
        assert insert_params["slug"] == "echo"


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
