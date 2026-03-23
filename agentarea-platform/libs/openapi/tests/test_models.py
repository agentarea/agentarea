"""Tests for OpenAPIConnection domain model."""

from agentarea_openapi.domain.models import OpenAPIConnection


class TestOpenAPIConnectionModel:
    def test_create_with_spec_url(self):
        conn = OpenAPIConnection(
            name="Stripe API",
            base_url="https://api.stripe.com",
            spec_url="https://raw.githubusercontent.com/stripe/openapi/master/openapi/spec3.json",
        )
        assert conn.name == "Stripe API"
        assert conn.base_url == "https://api.stripe.com"
        assert conn.spec_url is not None
        assert conn.status == "active"
        assert conn.available_tools == []

    def test_create_with_spec_content(self):
        spec = {"openapi": "3.0.0", "paths": {}}
        conn = OpenAPIConnection(
            name="Internal API",
            base_url="https://internal.example.com",
            spec_content=spec,
        )
        assert conn.spec_content == spec
        assert conn.spec_url is None

    def test_create_minimal(self):
        """Connection can exist with just base_url — tools discovered later."""
        conn = OpenAPIConnection(
            name="My API",
            base_url="https://api.example.com",
        )
        assert conn.spec_url is None
        assert conn.spec_content is None
        assert conn.available_tools == []

    def test_get_and_set_available_tools(self):
        conn = OpenAPIConnection(
            name="Test API",
            base_url="https://api.example.com",
        )
        tools = [
            {"name": "listUsers", "description": "List users", "inputSchema": {"type": "object"}},
        ]
        conn.available_tools = tools
        assert conn.available_tools == tools
        assert len(conn.available_tools) == 1
