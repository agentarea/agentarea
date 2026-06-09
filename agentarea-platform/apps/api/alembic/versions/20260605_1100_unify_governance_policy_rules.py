"""Unify governance policies into relational policy rules.

Replaces the typed per-scope ``governance_policies`` document bundle with a
unified ``policies`` table of relational rules. Each ``governance_policies`` row
is decomposed (inverse of ``rules_to_document``) into one rule row per known
sub-policy field, carrying ``workspace_id`` / ``created_by`` / ``enabled`` and
mapping ``scope_type`` -> ``subject_type``, ``scope_id`` -> ``subject_id``.

Stray/unknown nested keys that cannot map to a known rule are logged and
skipped. ``task_policy_snapshots`` is untouched. The downgrade recreates an
empty ``governance_policies`` table (data recompose is best-effort/empty).

Revision ID: 20260605_1100_unify_gov_policy
Revises: 20260605_1000_add_workspace_slug
Create Date: 2026-06-05 11:00:00.000000

"""

import json
import logging
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

logger = logging.getLogger("alembic.governance_unify")

# revision identifiers, used by Alembic.
revision: str = "20260605_1100_unify_gov_policy"
down_revision: str = "20260605_1000_add_workspace_slug"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB_TYPE = postgresql.JSONB().with_variant(sa.JSON(), "sqlite")


def _decompose_document(document: dict) -> list[dict]:
    """Inverse of rules_to_document: known sub-policies -> rule param dicts.

    Returns a list of ``{target, effect, params}`` dicts. Unknown keys are
    skipped (logged) so the migration never crashes on unexpected content.
    """
    rules: list[dict] = []

    budget = document.get("budget") or {}
    if budget.get("monthly_spend_cap_usd") is not None:
        rules.append(
            {
                "target": "spend",
                "effect": "cap",
                "params": {
                    "amount_usd": str(budget["monthly_spend_cap_usd"]),
                    "period": "month",
                },
            }
        )
    if budget.get("run_budget_usd") is not None:
        rules.append(
            {
                "target": "spend",
                "effect": "cap",
                "params": {"amount_usd": str(budget["run_budget_usd"]), "period": "run"},
            }
        )
    if budget.get("service_budget_usd") is not None:
        rules.append(
            {
                "target": "service",
                "effect": "cap",
                "params": {"amount_usd": str(budget["service_budget_usd"])},
            }
        )

    tokens = document.get("tokens") or {}
    token_params = {}
    if tokens.get("max_tokens") is not None:
        token_params["max_tokens"] = tokens["max_tokens"]
    if tokens.get("max_tokens_per_call") is not None:
        token_params["max_tokens_per_call"] = tokens["max_tokens_per_call"]
    if token_params:
        rules.append({"target": "tokens", "effect": "cap", "params": token_params})

    tools = document.get("tools") or {}
    for name in tools.get("allowed") or []:
        rules.append({"target": f"tool:{name}", "effect": "allow", "params": {}})
    for name in tools.get("denied") or []:
        rules.append({"target": f"tool:{name}", "effect": "deny", "params": {}})

    approval = document.get("approval") or {}
    approvers = approval.get("approvers") or []
    if approval.get("requires_human_approval") is True:
        rules.append(
            {
                "target": "*",
                "effect": "approval",
                "params": {"approvers": approvers} if approvers else {},
            }
        )
        approvers = []  # already carried on the global rule
    for tool_name in approval.get("escalation_rules") or []:
        rules.append(
            {
                "target": f"tool:{tool_name}",
                "effect": "approval",
                "params": {"approvers": approvers} if approvers else {},
            }
        )
        approvers = []

    content = document.get("content_safety") or {}
    safety_params = {}
    if content.get("prompt_injection_detection_enabled") is not None:
        safety_params["prompt_injection"] = content["prompt_injection_detection_enabled"]
    if content.get("output_sanitizer_enabled") is not None:
        safety_params["output_sanitizer"] = content["output_sanitizer_enabled"]
    if safety_params:
        rules.append({"target": "content", "effect": "safety", "params": safety_params})

    known_keys = {"budget", "tokens", "tools", "approval", "content_safety"}
    for key in document.keys():
        if key not in known_keys:
            logger.warning("dropping unmappable governance document key %r", key)

    return rules


def upgrade() -> None:
    """Create policies, migrate governance_policies rows, drop governance_policies."""
    op.create_table(
        "policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("subject_type", sa.String(50), nullable=False),
        sa.Column("subject_id", sa.String(255), nullable=False),
        sa.Column("target", sa.String(255), nullable=False),
        sa.Column("effect", sa.String(50), nullable=False),
        sa.Column("params", JSONB_TYPE, nullable=False, server_default="{}"),
        sa.Column("condition", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("ix_policies_workspace_id", "policies", ["workspace_id"])
    op.create_index("ix_policies_created_by", "policies", ["created_by"])
    op.create_index("ix_policies_subject_type", "policies", ["subject_type"])
    op.create_index("ix_policies_subject_id", "policies", ["subject_id"])
    op.create_index("ix_policies_target", "policies", ["target"])
    op.create_index("ix_policies_effect", "policies", ["effect"])
    op.create_index(
        "ix_policies_workspace_subject",
        "policies",
        ["workspace_id", "subject_type", "subject_id"],
    )

    # ---- data migration: decompose governance_policies documents into rules ----
    bind = op.get_bind()
    rows = (
        bind.execute(
            sa.text(
                "SELECT workspace_id, created_by, scope_type, scope_id, document, enabled "
                "FROM governance_policies"
            )
        )
        .mappings()
        .all()
    )

    insert_stmt = sa.text(
        "INSERT INTO policies "
        "(id, subject_type, subject_id, target, effect, params, condition, "
        " enabled, priority, workspace_id, created_by, created_at, updated_at) "
        "VALUES (:id, :subject_type, :subject_id, :target, :effect, :params, NULL, "
        " :enabled, 0, :workspace_id, :created_by, now(), now())"
    )

    for row in rows:
        document = row["document"]
        if isinstance(document, str):
            document = json.loads(document)
        document = document or {}
        for rule in _decompose_document(document):
            bind.execute(
                insert_stmt,
                {
                    "id": str(uuid.uuid4()),
                    "subject_type": row["scope_type"],
                    "subject_id": row["scope_id"],
                    "target": rule["target"],
                    "effect": rule["effect"],
                    "params": json.dumps(rule["params"]),
                    "enabled": row["enabled"],
                    "workspace_id": row["workspace_id"],
                    "created_by": row["created_by"],
                },
            )

    op.drop_table("governance_policies")


def downgrade() -> None:
    """Recreate an empty governance_policies table and drop policies.

    Data recompose is best-effort/empty — see the module docstring.
    Raises RuntimeError if policies rows exist to prevent silent data loss.
    """
    bind = op.get_bind()
    count = bind.execute(sa.text("SELECT COUNT(*) FROM policies")).scalar()
    if count:
        raise RuntimeError(
            f"downgrade() would permanently destroy {count} policy rule(s). "
            "Back up or export the policies table before rolling back this migration."
        )
    op.create_table(
        "governance_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("scope_type", sa.String(50), nullable=False),
        sa.Column("scope_id", sa.String(255), nullable=False),
        sa.Column("document", JSONB_TYPE, nullable=False, server_default="{}"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "workspace_id", "scope_type", "scope_id", name="uq_governance_policies_scope"
        ),
    )
    op.create_index("ix_governance_policies_workspace_id", "governance_policies", ["workspace_id"])
    op.create_index("ix_governance_policies_created_by", "governance_policies", ["created_by"])
    op.create_index("ix_governance_policies_scope_type", "governance_policies", ["scope_type"])
    op.create_index("ix_governance_policies_scope_id", "governance_policies", ["scope_id"])

    op.drop_index("ix_policies_workspace_subject", table_name="policies")
    op.drop_index("ix_policies_effect", table_name="policies")
    op.drop_index("ix_policies_target", table_name="policies")
    op.drop_index("ix_policies_subject_id", table_name="policies")
    op.drop_index("ix_policies_subject_type", table_name="policies")
    op.drop_index("ix_policies_created_by", table_name="policies")
    op.drop_index("ix_policies_workspace_id", table_name="policies")
    op.drop_table("policies")
