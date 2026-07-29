"""Seed a demo network: 10 agents, 10 MCP instances, 20 OpenAPI connections.

Agents are linked to a random mix of MCP, OpenAPI, and peer agents via the
``agent.tools`` JSON column so the /network topology endpoint surfaces a
populated graph.

Usage::

    cd agentarea-platform
    uv run python scripts/seed_demo_network.py <workspace_id> [--user <user_id>]

Notes:
- Inserts directly through SQLAlchemy ORM. No event broker / authz wiring.
- Idempotent within a run (uses uuid4 names) — re-running creates more rows.
"""

from __future__ import annotations

import argparse
import asyncio
import random
from uuid import uuid4

from agentarea_agents.domain.models import Agent
from agentarea_common.config.database import db
from agentarea_common.utils.slug import generate_slug
from agentarea_mcp.domain.models import MCPServer
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance
from agentarea_openapi.domain.models import OpenAPIConnection
from agentarea_triggers.infrastructure.orm import TriggerORM

AGENT_NAMES = [
    "orchestrator",
    "planner",
    "researcher",
    "coder",
    "reviewer",
    "data-analyst",
    "writer",
    "scheduler",
    "translator",
    "support-bot",
]

MCP_NAMES = [
    ("filesystem", "private"),
    ("postgres-prod", "private"),
    ("redis-cache", "private"),
    ("vector-store", "private"),
    ("slack", "egress"),
    ("github", "egress"),
    ("notion", "egress"),
    ("jira", "egress"),
    ("linear", "egress"),
    ("stripe", "egress"),
]

OPENAPI_NAMES = [
    "weather-api",
    "currency-api",
    "geocoding-api",
    "search-api",
    "translate-api",
    "speech-api",
    "vision-api",
    "embeddings-api",
    "summarize-api",
    "calendar-api",
    "crm-api",
    "billing-api",
    "shipping-api",
    "tickets-api",
    "monitoring-api",
    "logs-api",
    "metrics-api",
    "alerts-api",
    "auth-api",
    "feature-flags-api",
]


async def main(workspace_id: str, created_by: str) -> None:
    suffix = uuid4().hex[:6]
    rng = random.Random(42)

    async with db.session() as session:
        mcp_rows: list[MCPServerInstance] = []
        for name, scope in MCP_NAMES:
            spec = MCPServer(
                name=f"{name}-spec-{suffix}",
                description=f"Demo MCP server spec: {name}",
                remote_url=f"https://{name}.example/mcp",
                version="1.0.0",
                tags=["demo"],
                is_public=False,
                json_spec={"type": "url", "endpoint_url": f"https://{name}.example/mcp"},
                workspace_id=workspace_id,
                created_by=created_by,
            )
            session.add(spec)
            await session.flush()
            mcp = MCPServerInstance(
                name=f"{name}-{suffix}",
                description=f"Demo MCP server: {name}",
                server_spec_id=str(spec.id),
                json_spec={},
                network_scope=scope,
                workspace_id=workspace_id,
                created_by=created_by,
            )
            session.add(mcp)
            mcp_rows.append(mcp)

        openapi_rows: list[OpenAPIConnection] = []
        for name in OPENAPI_NAMES:
            conn = OpenAPIConnection(
                name=f"{name}-{suffix}",
                base_url=f"https://{name}.example",
                description=f"Demo OpenAPI: {name}",
                available_tools=[
                    {"name": f"{name}_get", "method": "GET", "path": "/v1/items"},
                    {"name": f"{name}_post", "method": "POST", "path": "/v1/items"},
                ],
                status="active",
            )
            conn.workspace_id = workspace_id
            conn.created_by = created_by
            session.add(conn)
            openapi_rows.append(conn)

        await session.flush()

        agent_rows: list[Agent] = []
        agent_records = [(name, f"{name}-{suffix}") for name in AGENT_NAMES]

        for base_name, full_name in agent_records:
            tools: list[dict] = []

            for mcp in rng.sample(mcp_rows, k=rng.randint(1, 3)):
                tools.append(
                    {
                        "type": "mcp",
                        "name": mcp.name,
                        "tool_server_id": str(mcp.id),
                    }
                )

            for conn in rng.sample(openapi_rows, k=rng.randint(1, 3)):
                tools.append(
                    {
                        "type": "openapi",
                        "name": conn.name,
                        "settings": {"openapi_connection_id": str(conn.id)},
                    }
                )

            agent = Agent(
                name=full_name,
                slug=generate_slug(full_name),
                description=f"Demo agent: {base_name}",
                instruction=f"You are the {base_name} demo agent.",
                model_id="gpt-4o-mini",
                tools=tools,
                agent_type="stateless",
                status="active",
            )
            agent.workspace_id = workspace_id
            agent.created_by = created_by
            session.add(agent)
            agent_rows.append(agent)

        await session.flush()

        # Add delegate-to-peer entries so the org chart shows hierarchy.
        # orchestrator delegates to planner, researcher, coder, writer.
        # planner delegates to researcher, data-analyst.
        # coder delegates to reviewer.
        delegations = {
            "orchestrator": ["planner", "researcher", "coder", "writer"],
            "planner": ["researcher", "data-analyst"],
            "coder": ["reviewer"],
            "support-bot": ["translator", "scheduler"],
        }
        by_base = {name: agent for name, agent in zip(AGENT_NAMES, agent_rows)}
        for parent_base, children in delegations.items():
            parent = by_base[parent_base]
            existing = list(parent.tools or [])
            for child_base in children:
                child = by_base[child_base]
                existing.append({"type": "agent", "name": child.name})
            parent.tools = existing

        # --- Triggers: attach a few webhook + cron triggers to specific agents.
        trigger_specs = [
            ("orchestrator", "incoming-webhook", "webhook", None),
            ("orchestrator", "nightly-run", "cron", "0 2 * * *"),
            ("support-bot", "telegram-webhook", "webhook", None),
            ("scheduler", "every-5min", "cron", "*/5 * * * *"),
            ("data-analyst", "weekly-report", "cron", "0 9 * * 1"),
        ]
        trigger_rows: list[TriggerORM] = []
        for agent_base, trig_name, trig_type, cron_expr in trigger_specs:
            owner = by_base[agent_base]
            trig = TriggerORM(
                name=f"{trig_name}-{suffix}",
                description=f"Demo trigger: {trig_name}",
                agent_id=owner.id,
                trigger_type=trig_type,
                cron_expression=cron_expr,
                webhook_id=(uuid4().hex if trig_type == "webhook" else None),
            )
            trig.workspace_id = workspace_id
            trig.created_by = created_by
            session.add(trig)
            trigger_rows.append(trig)

        await session.commit()

        print(
            f"seeded workspace={workspace_id}: "
            f"{len(agent_rows)} agents, {len(mcp_rows)} MCPs, "
            f"{len(openapi_rows)} OpenAPI connections, "
            f"{len(trigger_rows)} triggers"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace_id")
    parser.add_argument("--user", default="demo-seed")
    args = parser.parse_args()
    asyncio.run(main(args.workspace_id, args.user))
