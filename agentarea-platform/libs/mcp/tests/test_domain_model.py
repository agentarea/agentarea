import pytest
from agentarea_common.base.models import BaseModel
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance
from agentarea_mcp.domain.verification_types import (
    DEFAULT_VERIFICATION,
    VERIFICATION_SCHEMA_VERSION,
)


class TestVerificationTypes:
    def test_default_verification_schema_version(self):
        assert DEFAULT_VERIFICATION["schema_version"] == VERIFICATION_SCHEMA_VERSION

    def test_default_verification_status(self):
        assert DEFAULT_VERIFICATION["status"] == "never_attempted"

    def test_default_verification_at_is_none(self):
        assert DEFAULT_VERIFICATION["at"] is None

    def test_default_verification_error_is_none(self):
        assert DEFAULT_VERIFICATION["error"] is None

    def test_verification_schema_version_constant(self):
        assert VERIFICATION_SCHEMA_VERSION == 1

    def test_verification_payload_is_independent_copy(self):
        d1 = dict(DEFAULT_VERIFICATION)
        d2 = dict(DEFAULT_VERIFICATION)
        d1["status"] = "succeeded"
        assert d2["status"] == "never_attempted"


class TestMCPServerInstanceModel:
    def _make_instance(self, json_spec=None, server_spec_id="test-spec-id", **kwargs):
        return MCPServerInstance(
            name="test-instance",
            server_spec_id=server_spec_id,
            json_spec=json_spec or {},
            **kwargs,
        )

    def test_default_verification_is_never_attempted(self):
        instance = self._make_instance()
        assert instance.verification["status"] == "never_attempted"
        assert instance.verification["schema_version"] == 1

    def test_auth_config_table_is_registered_with_metadata(self):
        assert "mcp_auth_configs" in BaseModel.metadata.tables

    def test_custom_verification_accepted(self):
        verification = {
            "schema_version": 1,
            "status": "succeeded",
            "at": "2026-04-18T00:00:00Z",
            "error": None,
        }
        instance = self._make_instance(verification=verification)
        assert instance.verification["status"] == "succeeded"

    def test_verification_is_independent_from_default(self):
        instance1 = self._make_instance()
        instance2 = self._make_instance()
        instance1.verification["status"] = "succeeded"
        assert instance2.verification["status"] == "never_attempted"

    def test_last_dispatch_defaults_none(self):
        instance = self._make_instance()
        assert instance.last_dispatch is None

    def test_tools_defaults_none(self):
        instance = self._make_instance()
        assert instance.tools is None

    def test_no_status_attribute(self):
        instance = self._make_instance()
        assert not hasattr(instance, "status")

    def test_endpoint_url_url_type(self):
        instance = self._make_instance(
            json_spec={"type": "url", "endpoint_url": "https://example.com/mcp"}
        )
        assert instance.endpoint_url == "https://example.com/mcp"

    @pytest.mark.parametrize(
        "json_spec",
        [
            {"type": "docker", "port": 9000},
            {"type": "docker"},
            {"type": "command"},
            {"type": "kubernetes"},
            # Even an address the Go manager once reported must not be handed
            # back: reaching it directly skips the gateway that starts the
            # workload on demand and holds a request lease for the call.
            {
                "type": "docker",
                "port": 9000,
                "internal_url": "http://mcp-foo.agentarea.svc.cluster.local:8000",
            },
            {"type": "docker", "port": 9000, "internal_url": "/mcp/abc"},
        ],
    )
    def test_container_backed_instances_have_no_direct_endpoint(self, json_spec):
        """Python must not know how to address a container-backed workload.

        This property used to rebuild the manager's `mcp-<id>` naming scheme (and
        pass through Kubernetes Service DNS), which is a route around the gateway
        — no on-demand start, no request lease, no idle reclamation.
        """
        instance = self._make_instance(json_spec=json_spec)
        instance.id = "abc-123"
        with pytest.raises(ValueError, match="no direct endpoint"):
            _ = instance.endpoint_url

    def test_endpoint_url_bundle_raises(self):
        instance = self._make_instance(json_spec={"type": "bundle"})
        with pytest.raises(ValueError, match="bundle has no endpoint_url"):
            _ = instance.endpoint_url

    def test_endpoint_url_unknown_type_raises(self):
        instance = self._make_instance(json_spec={"type": "unknown"})
        with pytest.raises(ValueError, match="no endpoint_url"):
            _ = instance.endpoint_url
