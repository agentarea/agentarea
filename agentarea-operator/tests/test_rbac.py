"""RBAC manifest checks.

deploy/rbac.yaml is the operator's actual grant, applied as-is with no
templating, so these assertions read it directly rather than trusting a
description of what it should contain.
"""

from __future__ import annotations

from pathlib import Path

import yaml

RBAC_PATH = Path(__file__).parent.parent / "deploy" / "rbac.yaml"


def _load_docs() -> list[dict]:
    return [d for d in yaml.safe_load_all(RBAC_PATH.read_text()) if d]


def _rules_for(doc: dict) -> list[dict]:
    return doc.get("rules", [])


def test_no_clusterrolebinding_grants_secrets_access():
    """Secrets access must never ride on a ClusterRoleBinding.

    A ClusterRole can still list secrets in its rules (to be reused by scoped
    RoleBindings below), but nothing bound cluster-wide may include the
    "secrets" resource — that would hand the operator every Secret in the
    cluster on behalf of any CR author, regardless of the author's own
    Secrets access.
    """
    docs = _load_docs()
    cluster_role_bindings = [d for d in docs if d.get("kind") == "ClusterRoleBinding"]
    assert cluster_role_bindings, "expected at least one ClusterRoleBinding"

    cluster_roles_by_name = {
        d["metadata"]["name"]: d for d in docs if d.get("kind") == "ClusterRole"
    }

    for crb in cluster_role_bindings:
        role_name = crb["roleRef"]["name"]
        role = cluster_roles_by_name.get(role_name)
        assert role is not None, f"ClusterRoleBinding references unknown role {role_name}"
        for rule in _rules_for(role):
            assert "secrets" not in rule.get("resources", []), (
                f"ClusterRole {role_name} is bound cluster-wide via "
                f"{crb['metadata']['name']} yet grants access to secrets"
            )


def test_secrets_access_is_scoped_by_a_namespaced_rolebinding():
    """Whatever ClusterRole grants secrets must only be bound via a namespaced
    RoleBinding, and the read must be a "get" (the operator only ever reads a
    single named Secret; it never lists or watches them)."""
    docs = _load_docs()
    secrets_roles = [
        d
        for d in docs
        if d.get("kind") == "ClusterRole"
        and any("secrets" in r.get("resources", []) for r in _rules_for(d))
    ]
    assert secrets_roles, "expected a ClusterRole granting secrets access"

    for role in secrets_roles:
        role_name = role["metadata"]["name"]
        secrets_rule = next(r for r in _rules_for(role) if "secrets" in r["resources"])
        assert secrets_rule["verbs"] == ["get"], (
            f"{role_name} should only need 'get' on secrets, got {secrets_rule['verbs']}"
        )

        bindings = [
            d
            for d in docs
            if d.get("kind") == "RoleBinding" and d["roleRef"]["name"] == role_name
        ]
        assert bindings, f"{role_name} must be bound by at least one namespaced RoleBinding"
        for binding in bindings:
            assert binding["metadata"].get("namespace"), (
                f"RoleBinding {binding['metadata']['name']} for {role_name} must be namespaced"
            )

        assert not any(
            d.get("kind") == "ClusterRoleBinding" and d["roleRef"]["name"] == role_name
            for d in docs
        ), f"{role_name} must never be bound via a ClusterRoleBinding"


def test_registrysyncs_is_granted():
    docs = _load_docs()
    agentarea_rules = [
        r
        for d in docs
        if d.get("kind") == "ClusterRole"
        for r in _rules_for(d)
        if r.get("apiGroups") == ["agentarea.io"]
    ]
    resources: set[str] = set()
    for rule in agentarea_rules:
        resources.update(rule.get("resources", []))

    assert "registrysyncs" in resources
    assert "registrysyncs/status" in resources
