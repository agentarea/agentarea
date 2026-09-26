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

import asyncio
import json
import textwrap
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
    skills: list[str] | None = None,
    triggers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "version": "1.0.0",
        "instruction": textwrap.dedent(instruction).strip(),
        # The catalog is global and model instances are per-workspace, so
        # RegistryService._parse_agents carries `preferred_models` (slugs) and
        # ignores `model_id` — emitting the latter reconciles to no preference.
        "preferred_models": [DEFAULT_MODEL],
        "tools": tools or [],
        "planning": planning,
        "tags": tags or [],
        # Stable catalog skill keys (``<skill>--<source>``, no content hash).
        "skills": skills or [],
        "triggers": triggers or [],
    }


def _code(*names: str) -> list[dict[str, Any]]:
    return [{"type": "code", "name": name} for name in names]


# The toolsets the UI switches on and off together as "Sandbox".
_SANDBOX = ("agentarea/shell", "agentarea/files", "agentarea/workspace_files")

# Presets are catalog agents tagged "preset": the starting points offered on the
# agent-create form. Applying one fills tools, skills, triggers and instruction.
PRESETS: list[dict[str, Any]] = [
    _agent(
        "AgentArea Claw",
        "Personal assistant that works in its own sandbox, remembers context, "
        "checks in on a schedule and answers you in Telegram.",
        """
        You are a personal assistant with your own sandbox, the web, and a memory
        of the workspace. Do the work instead of describing it: run commands,
        write files, look things up.

        Keep HEARTBEAT.md in your workspace files as a short checklist of things
        to watch. On a heartbeat run, work through that checklist; if nothing
        needs attention, finish without doing anything else.

        Before anything destructive or hard to undo, say what you are about to do.
        """,
        tools=_code(*_SANDBOX, "agentarea/web", "agentarea/context"),
        skills=["brainstorming--obra-superpowers", "writing-plans--obra-superpowers"],
        triggers=[
            {
                "name": "Heartbeat",
                "trigger_type": "cron",
                "cron_expression": "*/30 * * * *",
                "timezone": "UTC",
                "task_parameters": {
                    "text": "Heartbeat: read HEARTBEAT.md and work through its checklist."
                },
            },
            {
                "name": "Telegram",
                "trigger_type": "webhook",
                "webhook_type": "telegram",
                "task_parameters": {"text": "Reply to the Telegram message you received."},
            },
        ],
        tags=["preset", "assistant"],
    ),
    _agent(
        "Researcher",
        "Researches a question on the web and writes up cited findings.",
        """
        You are a research assistant. Break the question into parts, search and
        read primary sources, and keep notes in your workspace files. Answer with
        a concise write-up that cites every claim and flags what is uncertain.
        """,
        tools=_code(*_SANDBOX, "agentarea/web", "agentarea/context"),
        skills=["create-plan--openai-skills"],
        tags=["preset", "research"],
        planning=True,
    ),
]


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


def _stdio_mcp(key: str, name: str, command: str, args: list[str]) -> dict[str, Any]:
    """A stdio MCP run in the mcp-bridge container.

    ``command`` must be one of the runtimes the analyzer allows (npx, uvx, …) and
    the package must actually be published — an unresolvable package fails at
    container start, long after the install reports success.
    """
    return {
        "key": key,
        "name": name,
        "json_spec": {"type": "command", "command": command, "args": args},
        "bindings": {},
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
    channels: list[dict[str, Any]] | None = None,
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
    if channels:
        bundle["channels"] = channels
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
        "instruction": textwrap.dedent(instruction).strip(),
    }
    d.update(over)
    return d


_TELEGRAM_TOKEN_SETUP = {
    "key": "telegram_bot_token",
    "label": "Telegram bot token",
    "type": "secret",
    "required": True,
    "help": "From @BotFather. Used so the agent can reply in your Telegram chat.",
}


BUNDLES: list[dict[str, Any]] = [
    _bundle(
        "ops-pulse",
        "Ops Pulse",
        "A governed operations assistant: chat with it on Telegram, run a daily "
        "health check, and keep it locked to a safe, explicit set of tools.",
        category="operations",
        capabilities=["interactive", "scheduled", "governed"],
        setup=[_MODEL_SETUP, _TELEGRAM_TOKEN_SETUP],
        skills=[
            _skill("incident_triage", "Incident Triage", "# Incident Triage\nClassify an incident by severity (S1-S4), summarize impact, and propose the next concrete action. Be terse and decisive."),
            _skill("status_digest", "Status Digest", "# Status Digest\nProduce a short daily digest: what changed, what's at risk, and what needs a human. Lead with the one thing that matters most."),
        ],
        mcps=[
            _stdio_mcp("web", "Web Fetch", "uvx", ["mcp-server-fetch"]),
        ],
        agents=[
            _agent_def(
                "watcher",
                "Ops Pulse Watcher",
                "You are an operations watcher. Triage incidents, fetch status pages when asked, and produce crisp digests. Never take destructive actions; if something looks risky, ask for human approval.",
                mcps=["web"],
                skills=["incident_triage", "status_digest"],
            )
        ],
        channels=[
            {
                "key": "telegram_inbox",
                "type": "telegram",
                "name": "Telegram inbox",
                "agent": "watcher",
                "bindings": {"bot_token": "${setup.telegram_bot_token}"},
                "prompt": "Handle the incoming Telegram message: {{ message_text }}",
                "enabled": False,
            }
        ],
        automations=[
            {
                "key": "daily_health_check",
                "type": "cron",
                "cron": "0 9 * * *",
                "timezone": "UTC",
                "agent": "watcher",
                "prompt": "Run the daily health check: review overnight status, fetch any referenced status pages, and write a Status Digest.",
                "enabled": False,
            }
        ],
        policies=[
            {"key": "scope_tools", "subject": "watcher", "target": "tool:fetch", "effect": "allow",
             "message": "Ops Pulse may only use the Web Fetch tool."},
            {"key": "spend_cap", "subject": "workspace", "target": "spend", "effect": "cap",
             "params": {"amount_usd": 100, "period": "month"},
             "message": "Capped at $100 / month."},
            {"key": "approve_writes", "subject": "watcher", "target": "tool:fetch",
             "effect": "approval",
             "message": "Ask a human before fetching external URLs."},
        ],
    ),
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
            {"key": "cap_monthly_spend", "target": "spend", "effect": "cap",
             "params": {"amount_usd": 25, "period": "month"},
             "message": "Cap automated outreach spend at $25 / month."},
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
    _bundle(
        "meeting-companion",
        "Meeting Companion",
        "Turn raw meeting notes into summaries, decisions, and owner-tagged actions, "
        "then chase what is still open every Monday.",
        category="productivity",
        capabilities=["interactive", "scheduled"],
        setup=[_MODEL_SETUP],
        skills=[
            _skill("meeting_summary", "Meeting Summary", "# Meeting Summary\nCondense a transcript into context, decisions, and open questions. Keep it skimmable; quote a line only when the exact wording matters."),
            _skill("action_items", "Action Items", "# Action Items\nExtract every commitment as `owner - action - due`. Mark an item unowned rather than guessing an owner, and drop anything that is only a discussion point."),
        ],
        agents=[
            _agent_def(
                "notetaker",
                "Meeting Companion",
                "You turn meeting notes and transcripts into a summary, the decisions taken, and owner-tagged action items. Never invent an owner or a due date; say 'unassigned' when the notes do not say.",
                skills=["meeting_summary", "action_items"],
            )
        ],
        automations=[
            {
                "key": "weekly_followup",
                "type": "cron",
                "cron": "0 8 * * 1",
                "timezone": "UTC",
                "agent": "notetaker",
                "prompt": "List every action item from last week's notes that is still open, with its owner and how long it has been outstanding. Flag anything older than seven days.",
                "enabled": False,
            }
        ],
    ),
    _bundle(
        "finance-ops",
        "Finance Ops",
        "An invoice and expense assistant that drafts the paperwork but can never move "
        "money on its own.",
        category="finance",
        capabilities=["interactive", "governed"],
        setup=[_MODEL_SETUP],
        skills=[
            _skill("invoice_triage", "Invoice Triage", "# Invoice Triage\nFor each invoice: vendor, amount, due date, and whether it matches an existing PO. Route mismatches to a human instead of approving them."),
            _skill("expense_review", "Expense Review", "# Expense Review\nCheck an expense against policy: category, limit, receipt present, business purpose stated. Report a verdict plus the specific rule you applied."),
        ],
        agents=[
            _agent_def(
                "bookkeeper",
                "Finance Assistant",
                "You triage invoices and review expenses. Show the arithmetic behind every total, cite the policy rule you applied, and escalate anything ambiguous. You never authorize a payment.",
                skills=["invoice_triage", "expense_review"],
            )
        ],
        policies=[
            {"key": "deny_payments", "subject": "bookkeeper", "target": "tool:make_payment",
             "effect": "deny",
             "message": "The assistant may never move money."},
            {"key": "approve_invoices", "subject": "bookkeeper", "target": "tool:send_invoice",
             "effect": "approval",
             "message": "Approve an invoice before it is sent to a customer."},
            {"key": "cap_monthly_spend", "target": "spend", "effect": "cap",
             "params": {"amount_usd": 50, "period": "month"},
             "message": "Cap automated spend at $50 / month."},
        ],
    ),
    _bundle(
        "recruiting-screen",
        "Recruiting Screener",
        "Screen candidates against a role brief with a consistent rubric, and draft the "
        "outreach — with a human in the loop before anything is sent.",
        category="hr",
        capabilities=["interactive", "governed"],
        setup=[_MODEL_SETUP],
        skills=[
            _skill("screening_rubric", "Screening Rubric", "# Screening Rubric\nScore a candidate against the role's must-haves and nice-to-haves. Quote the evidence from the CV for each score, and mark a requirement unverified when the CV is silent - never infer it."),
            _skill("candidate_outreach", "Candidate Outreach", "# Candidate Outreach\nDraft a short, specific first message: why this person, what the role is, and one concrete next step. No superlatives, no filler."),
        ],
        agents=[
            _agent_def(
                "screener",
                "Recruiting Screener",
                "You screen candidates against a role brief and draft outreach. Judge only on evidence in the application, apply the same rubric to everyone, and never infer age, gender, nationality, or any other protected characteristic.",
                skills=["screening_rubric", "candidate_outreach"],
            )
        ],
        policies=[
            {"key": "approve_outreach", "subject": "screener", "target": "tool:send_email",
             "effect": "approval",
             "message": "A human approves every message to a candidate."},
            {"key": "cap_monthly_spend", "target": "spend", "effect": "cap",
             "params": {"amount_usd": 25, "period": "month"},
             "message": "Cap automated spend at $25 / month."},
        ],
    ),
    _bundle(
        "release-radar",
        "Release Radar",
        "Watches the dependencies you care about, posts a daily digest of what shipped "
        "and what looks risky, and answers follow-up questions on Telegram.",
        category="engineering",
        capabilities=["interactive", "scheduled", "governed"],
        setup=[_MODEL_SETUP, _TELEGRAM_TOKEN_SETUP],
        skills=[
            _skill("release_digest", "Release Digest", "# Release Digest\nSummarize what shipped since the last digest: version, headline change, and whether it is breaking. Lead with anything that needs action today."),
            _skill("risk_callout", "Risk Callout", "# Risk Callout\nFor a release note, name the breaking changes, deprecations, and security fixes, and state the upgrade action for each. Say so explicitly when a release carries none."),
        ],
        mcps=[
            _stdio_mcp("web", "Web Fetch", "uvx", ["mcp-server-fetch"]),
        ],
        agents=[
            _agent_def(
                "radar",
                "Release Radar",
                "You track releases of the projects the team depends on. Fetch the release notes, separate breaking changes from routine ones, and state the upgrade action. Quote the version numbers you actually read; if a page cannot be fetched, say so instead of guessing.",
                mcps=["web"],
                skills=["release_digest", "risk_callout"],
            )
        ],
        channels=[
            {
                "key": "telegram_inbox",
                "type": "telegram",
                "name": "Telegram inbox",
                "agent": "radar",
                "bindings": {"bot_token": "${setup.telegram_bot_token}"},
                "prompt": "Answer the release question from Telegram: {{ message_text }}",
                "enabled": False,
            }
        ],
        automations=[
            {
                "key": "daily_digest",
                "type": "cron",
                "cron": "0 7 * * 1-5",
                "timezone": "UTC",
                "agent": "radar",
                "prompt": "Check the release notes of the tracked dependencies and write today's digest: what shipped, what is breaking, and what we should upgrade.",
                "enabled": False,
            }
        ],
        policies=[
            {"key": "cap_monthly_spend", "target": "spend", "effect": "cap",
             "params": {"amount_usd": 20, "period": "month"},
             "message": "Cap automated spend at $20 / month."},
        ],
    ),
]


async def _validate_bundles(bundles: list[dict[str, Any]]) -> None:
    """Fail loudly if a bundle would not install, or would install a dead rule.

    Schema validation catches a malformed entry; running the same analyzer the
    import wizard runs catches everything else — a dangling key reference, a
    policy the governance compiler would silently skip. A BLOCK issue means the
    catalog would ship a bundle nobody can install.
    """
    from agentarea_bundles.application.analyzer import BundleAnalyzer
    from agentarea_bundles.schemas.bundle import Bundle
    from agentarea_bundles.schemas.preview import IssueSeverity

    problems: list[str] = []
    seen: set[str] = set()
    for raw in bundles:
        name = raw["name"]
        if name in seen:
            raise ValueError(f"duplicate bundle name: {name}")
        seen.add(name)

        bundle = Bundle.model_validate(raw)  # raises on any schema violation

        preview = await BundleAnalyzer().analyze(bundle)
        problems += [
            f"{name}: {issue.message}"
            for issue in preview.issues
            if issue.severity is IssueSeverity.BLOCK
        ]

    if problems:
        raise SystemExit("catalog is invalid:\n  " + "\n  ".join(problems))


def _validate_presets(presets: list[dict[str, Any]]) -> None:
    """Fail the build if a preset would not load on the agent-create form."""
    from agentarea_agents.schemas.import_export import TOOL_CONFIG_ADAPTER
    from agentarea_agents_sdk.tools.code_tools_loader import get_code_tools_metadata
    from agentarea_triggers.schemas.dto import TriggerSpec

    toolsets = get_code_tools_metadata()
    problems: list[str] = []
    for preset in presets:
        name = preset["name"]
        for tool in preset["tools"]:
            TOOL_CONFIG_ADAPTER.validate_python(tool)
            if tool["type"] == "code" and tool["name"] not in toolsets:
                problems.append(f"{name}: unknown toolset {tool['name']!r}")
        for trigger in preset["triggers"]:
            TriggerSpec.model_validate(trigger)
        for key in preset["skills"]:
            if key.count("--") != 1:
                problems.append(f"{name}: skill key {key!r} is not '<skill>--<source>'")
    if problems:
        raise SystemExit("presets are invalid:\n  " + "\n  ".join(problems))


def main() -> None:
    asyncio.run(_validate_bundles(BUNDLES))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _validate_presets(PRESETS)
    agents = [*PRESETS, *AGENTS]
    (OUT_DIR / "agents.json").write_text(json.dumps({"agents": agents}, indent=2) + "\n")
    (OUT_DIR / "bundles.json").write_text(json.dumps({"bundles": BUNDLES}, indent=2) + "\n")
    print(f"Wrote {len(agents)} agents and {len(BUNDLES)} bundles to {OUT_DIR}")  # noqa: T201


if __name__ == "__main__":
    main()
