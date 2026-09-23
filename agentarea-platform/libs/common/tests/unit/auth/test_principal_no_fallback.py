"""A principal is never fabricated.

Every context object must trace back to something that actually authenticated:
a real user, or an explicitly declared piece of platform infrastructure. Code
that cannot name its principal must fail loudly instead of inventing one.
"""

import pytest

from agentarea_common.auth.context import ServicePrincipal, UserContext


class TestServicePrincipal:
    def test_carries_no_user_or_workspace(self):
        """The whole point: it cannot be mistaken for, or coerced into, a user.

        Earlier code wrote UserContext(user_id="system", workspace_id="system")
        and every workspace-scoped query silently ran against a "system" tenant.
        A ServicePrincipal has no such attributes, so that mistake stops being
        expressible.
        """
        principal = ServicePrincipal(service="outbox-relay", reason="reads across all workspaces")

        assert not hasattr(principal, "user_id")
        assert not hasattr(principal, "workspace_id")
        assert not hasattr(principal, "accessible_workspaces")

    def test_requires_a_declared_reason(self):
        with pytest.raises(ValueError, match="reason"):
            ServicePrincipal(service="outbox-relay", reason="")

    def test_requires_a_service_name(self):
        with pytest.raises(ValueError, match="service"):
            ServicePrincipal(service="", reason="reads across all workspaces")

    def test_is_not_a_user_context(self):
        principal = ServicePrincipal(service="outbox-relay", reason="infrastructure")
        assert not isinstance(principal, UserContext)


class TestUserContextRejectsEmptyPrincipal:
    def test_empty_user_id_is_refused(self):
        """`user_id or ""` used to produce exactly this."""
        with pytest.raises(ValueError, match="user_id"):
            UserContext(user_id="", workspace_id="ws-1")

    def test_empty_workspace_id_is_refused(self):
        with pytest.raises(ValueError, match="workspace_id"):
            UserContext(user_id="user-1", workspace_id="")

    def test_real_principal_is_accepted(self):
        ctx = UserContext(user_id="user-1", workspace_id="ws-1")
        assert ctx.user_id == "user-1"
        assert ctx.accessible_workspaces == ["ws-1"]


class TestWorkspaceScopedRepositoryRefusesServicePrincipal:
    def test_service_principal_cannot_scope_a_repository(self):
        """A ServicePrincipal has no workspace, so it must never reach a scoped repo.

        Without this guard the type is only a convention; with it, the failure
        happens at construction instead of silently returning another tenant's
        rows (or none at all).
        """
        from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository

        principal = ServicePrincipal(service="webhook-lookup", reason="pre-tenant lookup")

        with pytest.raises(TypeError, match="ServicePrincipal"):
            WorkspaceScopedRepository(
                session=object(), model_class=type("FakeORM", (), {}), user_context=principal
            )
