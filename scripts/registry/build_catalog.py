#!/usr/bin/env python
"""Generate the agents.json + bundles.json catalog documents.

These are the catalog-format documents published to
  s3://agentarea-mcp-registry/registry/system/{agents,bundles}.json
and reconciled into registry_items by `agentarea-api reconcile`.

Every bundle is validated against the canonical `Bundle` pydantic model before
it is written, so a malformed catalog fails here rather than at reconcile time.

Run:
    uv run python scripts/registry/build_catalog.py
    # writes data/catalog/agents.json and data/catalog/bundles.json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

OUT_DIR = Path(__file__).resolve().parents[2] / "data" / "catalog"

# Models that agents reference. AgentCreate.model_id accepts a literal provider
# id, so the catalog is portable; the workspace just needs that provider keyed.
DEFAULT_MODEL = "gpt-4o"


# ── Agents catalog (matches RegistryService._parse_agents) ──────────────────


def _agent(
    name: str,
    description: str,
    instruction: str,
    *,
    tools: list[dict[str, Any]] | None = None,
    tags: list[str] | None = None,
    planning: bool = False,
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "version": "1.0.0",
        "instruction": instruction.strip(),
        "model_id": DEFAULT_MODEL,
        "tools": tools or [],
        "planning": planning,
        "tags": tags or [],
    }


AGENTS: list[dict[str, Any]] = [
    _agent(
        "Research Assistant",
        "Researches topics and produces cited summaries.",
        """
        You are a thorough research assistant. Break the question into sub-topics,
        gather facts, and produce a concise summary with explicit sources. Flag
        uncertainty rather than guessing.
        """,
        tags=["research", "writing"],
        planning=True,
    ),
    _agent(
        "Code Reviewer",
        "Reviews diffs for bugs, security issues, and clarity.",
        """
        You review code changes. Report concrete defects with severity, cite the
        file and line, and suggest a fix. Prefer high-signal findings over nits.
        """,
        tags=["engineering", "review"],
    ),
    _agent(
        "Data Analyst",
        "Answers questions over datasets and explains the method.",
        """
        You analyze data and explain your reasoning. State assumptions, show the
        steps you took, and call out caveats in the data before giving a verdict.
        """,
        tags=["data", "analysis"],
        planning=True,
    ),
    _agent(
        "Customer Support",
        "Resolves customer questions with a friendly, accurate tone.",
        """
        You are a customer support agent. Be empathetic and precise. If you are
        unsure of policy, say so and escalate rather than inventing an answer.
        """,
        tags=["support"],
    ),
    _agent(
        "Content Writer",
        "Drafts blog posts and marketing copy from a brief.",
        """
        You write clear, engaging content from a brief. Match the requested tone,
        lead with the value, and keep paragraphs tight.
        """,
        tags=["content", "marketing"],
    ),
    _agent(
        "SEO Specialist",
        "Turns keywords into on-page and content recommendations.",
        """
        You are an SEO specialist. Given a topic or keyword, propose titles, meta
        descriptions, an outline, and internal-linking ideas grounded in intent.
        """,
        tags=["seo", "marketing"],
    ),
    _agent(
        "DevOps Helper",
        "Explains and drafts infra/CI changes safely.",
        """
        You help with DevOps tasks. Prefer the smallest safe change, explain the
        blast radius, and never propose destructive operations without a warning.
        """,
        tags=["devops", "engineering"],
    ),
    _agent(
        "Email Triager",
        "Sorts and prioritizes an inbox into clear next actions.",
        """
        You triage email. Group by urgency and importance, draft short replies for
        routine messages, and surface the few items that truly need attention.
        """,
        tags=["productivity", "email"],
    ),
    _agent(
        "Meeting Notetaker",
        "Turns raw notes/transcripts into summaries and action items.",
        """
        You convert meeting notes into a crisp summary, decisions, and owner-tagged
        action items. Keep it skimmable.
        """,
        tags=["productivity"],
    ),
    _agent(
        "Product Manager",
        "Helps shape specs, user stories, and prioritization.",
        """
        You act as a pragmatic product manager. Clarify the problem, write tight
        user stories with acceptance criteria, and recommend a priority order.
        """,
        tags=["product"],
        planning=True,
    ),
]


# ── Bundles catalog (each entry is a canonical Bundle) ──────────────────────


def _skill(key: str, name: str, content: str) -> dict[str, Any]:
    return {
        "key": key,
        "name": name,
        "source_type": "content",
        "content": content.strip() + "\n",
    }


def _url_mcp(key: str, name: str, endpoint_url: str) -> dict[str, Any]:
    """A remote MCP connector. OAuth is discovered from the URL at connect time,
    so no auth config is baked into the bundle.
    """
    return {
        "key": key,
        "name": name,
        "json_spec": {"type": "url", "endpoint_url": endpoint_url},
    }


def _bundle(
    name: str,
    display_name: str,
    description: str,
    *,
    category: str,
    capabilities: list[str],
    setup: list[dict[str, Any]] | None = None,
    skills: list[dict[str, Any]] | None = None,
    mcps: list[dict[str, Any]] | None = None,
    agents: list[dict[str, Any]] | None = None,
    automations: list[dict[str, Any]] | None = None,
    policies: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    bundle: dict[str, Any] = {
        "schema_version": "0.1.0",
        "name": name,
        "display_name": display_name,
        "description": description.strip(),
        "metadata": {
            "developer": "AgentArea",
            "category": category,
            "capabilities": capabilities,
        },
    }
    if setup:
        bundle["setup"] = setup
    if skills:
        bundle["skills"] = skills
    if mcps:
        bundle["mcps"] = mcps
    if agents:
        bundle["agents"] = agents
    if automations:
        bundle["automations"] = automations
    if policies:
        bundle["policies"] = policies
    return bundle


_MODEL_SETUP = {
    "key": "model",
    "label": "Model",
    "type": "string",
    "required": False,
    "default": DEFAULT_MODEL,
    "help": "Provider model id used by the bundle's agents.",
}


def _agent_def(key: str, name: str, instruction: str, **over: Any) -> dict[str, Any]:
    d = {
        "key": key,
        "name": name,
        "model": "${setup.model}",
        "instruction": instruction.strip(),
    }
    d.update(over)
    return d


BUNDLES: list[dict[str, Any]] = [
    _bundle(
        "productivity-lite",
        "Productivity Lite",
        "A lightweight assistant that plans your day and triages tasks.",
        category="productivity",
        capabilities=["interactive"],
        setup=[_MODEL_SETUP],
        skills=[
            _skill("daily_planning", "Daily Planning", "# Daily Planning\nPropose a prioritized, time-boxed plan."),
            _skill("task_triage", "Task Triage", "# Task Triage\nOrder tasks by urgency x importance."),
        ],
        agents=[
            _agent_def(
                "assistant",
                "Productivity Assistant",
                "You help the user plan their day and triage tasks. Be concise and actionable.",
                skills=["daily_planning", "task_triage"],
            )
        ],
    ),
    _bundle(
        "research-assistant",
        "Research Assistant",
        "Researches topics and writes cited summaries.",
        category="research",
        capabilities=["interactive"],
        setup=[_MODEL_SETUP],
        skills=[
            _skill("source_review", "Source Review", "# Source Review\nCheck claims against sources; flag uncertainty."),
        ],
        agents=[
            _agent_def(
                "researcher",
                "Researcher",
                "Break a question into sub-topics, gather facts, and summarize with explicit sources.",
                skills=["source_review"],
            )
        ],
    ),
    _bundle(
        "content-studio",
        "Content Studio",
        "Plan, draft, and optimize marketing content.",
        category="marketing",
        capabilities=["interactive", "write"],
        setup=[_MODEL_SETUP],
        skills=[
            _skill("brief_to_outline", "Brief to Outline", "# Brief to Outline\nTurn a brief into a structured outline."),
            _skill("seo_pass", "SEO Pass", "# SEO Pass\nSuggest titles, meta, and internal links by intent."),
        ],
        agents=[
            _agent_def("writer", "Content Writer", "Write engaging content from a brief; match tone.", skills=["brief_to_outline"]),
            _agent_def("seo", "SEO Editor", "Optimize drafts for search intent.", skills=["seo_pass"]),
        ],
    ),
    _bundle(
        "dev-workflow",
        "Dev Workflow",
        "Code review and DevOps helpers for engineering teams.",
        category="engineering",
        capabilities=["interactive"],
        setup=[_MODEL_SETUP],
        skills=[
            _skill("review_checklist", "Review Checklist", "# Review Checklist\nBugs, security, clarity, tests."),
        ],
        agents=[
            _agent_def("reviewer", "Code Reviewer", "Review diffs; report defects with severity and a fix.", skills=["review_checklist"]),
            _agent_def("devops", "DevOps Helper", "Draft safe infra/CI changes; explain blast radius."),
        ],
    ),
    _bundle(
        "customer-support",
        "Customer Support",
        "Front-line support assistant with an escalation policy.",
        category="support",
        capabilities=["interactive"],
        setup=[_MODEL_SETUP],
        skills=[
            _skill("support_tone", "Support Tone", "# Support Tone\nEmpathetic, precise; escalate when unsure."),
        ],
        agents=[
            _agent_def("support", "Support Agent", "Resolve customer questions accurately and kindly.", skills=["support_tone"]),
        ],
        policies=[
            {"key": "deny_refunds", "target": "tool:issue_refund", "effect": "deny",
             "message": "Never issue refunds autonomously."},
            {"key": "approve_escalation", "target": "tool:escalate", "effect": "approval",
             "message": "Confirm before escalating to a human."},
        ],
    ),
    _bundle(
        "sales-outreach",
        "Sales Outreach",
        "Draft cold emails and follow-up sequences.",
        category="sales",
        capabilities=["interactive", "write"],
        setup=[_MODEL_SETUP],
        skills=[
            _skill("cold_email", "Cold Email", "# Cold Email\nSubject, opener, value, CTA; short follow-ups."),
        ],
        agents=[
            _agent_def("sdr", "Outreach Writer", "Write B2B cold emails that get replies.", skills=["cold_email"]),
        ],
        policies=[
            {"key": "approve_outreach", "target": "tool:send_email", "effect": "approval",
             "message": "Approve outreach emails before they send."},
            {"key": "cap_daily_contacts", "target": "actions", "effect": "cap",
             "params": {"count": 200, "period": "day"},
             "message": "Limit to 200 contacts per day."},
        ],
    ),
    _bundle(
        "seo-toolkit",
        "SEO Toolkit",
        "Keyword-to-content recommendations and audits.",
        category="marketing",
        capabilities=["interactive"],
        setup=[_MODEL_SETUP],
        skills=[
            _skill("keyword_intent", "Keyword Intent", "# Keyword Intent\nMap keywords to intent and content type."),
        ],
        agents=[
            _agent_def("seo", "SEO Specialist", "Turn keywords into on-page and content recommendations.", skills=["keyword_intent"]),
        ],
    ),
    _bundle(
        "data-insights",
        "Data Insights",
        "Analyze datasets and explain the method.",
        category="data",
        capabilities=["interactive"],
        setup=[_MODEL_SETUP],
        skills=[
            _skill("analysis_method", "Analysis Method", "# Analysis Method\nState assumptions; show steps; note caveats."),
        ],
        agents=[
            _agent_def("analyst", "Data Analyst", "Answer questions over data and explain reasoning.", skills=["analysis_method"]),
        ],
    ),
    _bundle(
        "inbox-zero",
        "Inbox Zero",
        "Triage your inbox via a connected mail MCP, with a daily summary.",
        category="productivity",
        capabilities=["interactive"],
        setup=[_MODEL_SETUP],
        skills=[
            _skill("triage_rules", "Triage Rules", "# Triage Rules\nGroup by urgency; draft routine replies."),
        ],
        mcps=[
            _url_mcp("mail", "Mail Connector", "https://mcp.example.com/mail"),
        ],
        agents=[
            _agent_def("triager", "Email Triager", "Triage the inbox and surface what needs attention.", skills=["triage_rules"], mcps=["mail"]),
        ],
        automations=[
            {
                "key": "daily_digest",
                "type": "cron",
                "cron": "0 8 * * *",
                "timezone": "UTC",
                "agent": "triager",
                "prompt": "Summarize new email since yesterday and list the top 3 actions.",
                "enabled": False,
            }
        ],
        policies=[
            {"key": "approve_send_email", "target": "tool:send_email", "effect": "approval",
             "message": "Ask before sending any email on your behalf."},
            {"key": "cap_monthly_spend", "target": "spend", "effect": "cap",
             "params": {"amount_usd": 20, "period": "month"},
             "message": "Cap automated spend at $20 / month."},
        ],
    ),
    _bundle(
        "social-scheduler",
        "Social Scheduler",
        "Plan and draft a weekly social content calendar.",
        category="marketing",
        capabilities=["interactive", "write"],
        setup=[_MODEL_SETUP],
        skills=[
            _skill("calendar_plan", "Calendar Plan", "# Calendar Plan\nDraft a weekly posting calendar with hooks."),
        ],
        agents=[
            _agent_def("social", "Social Planner", "Plan and draft social posts for the week.", skills=["calendar_plan"]),
        ],
        automations=[
            {
                "key": "weekly_plan",
                "type": "cron",
                "cron": "0 9 * * 1",
                "timezone": "UTC",
                "agent": "social",
                "prompt": "Draft next week's social calendar.",
                "enabled": False,
            }
        ],
    ),
]


def _validate_bundles(bundles: list[dict[str, Any]]) -> None:
    """Fail loudly if any bundle does not validate against the canonical model."""
    from agentarea_bundles.schemas.bundle import Bundle

    seen: set[str] = set()
    for b in bundles:
        if b["name"] in seen:
            raise ValueError(f"duplicate bundle name: {b['name']}")
        seen.add(b["name"])
        Bundle.model_validate(b)  # raises on any schema violation


def main() -> None:
    _validate_bundles(BUNDLES)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "agents.json").write_text(json.dumps({"agents": AGENTS}, indent=2) + "\n")
    (OUT_DIR / "bundles.json").write_text(json.dumps({"bundles": BUNDLES}, indent=2) + "\n")
    print(f"Wrote {len(AGENTS)} agents and {len(BUNDLES)} bundles to {OUT_DIR}")  # noqa: T201


if __name__ == "__main__":
    main()
