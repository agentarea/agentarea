# VPC Network View — Design Spec

## Context

Replace the generic React Flow network topology view with a Doubleloop-inspired VPC network visualization. Two tabs: **Organization** (agent hierarchy + capabilities) and **Data Flow** (VPC-style security topology with trust boundaries and risk indicators).

The existing React Flow library (`@xyflow/react`) is retained but restyled to match Doubleloop's visual language: content-rich white cards, thin bezier edges, muted color palette, dot-grid background.

## Goals

1. Show security topology: trust boundaries, ingress/egress points, governance enforcement points
2. Show business topology: which agents are responsible for what, delegation relationships
3. Explicitly surface risks: boundary-crossing connections, unprotected egress, missing governance
4. Look native to the product — Doubleloop-style cards with inline data, not a generic diagram widget

## Non-Goals

- Real-time streaming updates (static fetch + manual refresh)
- Free-form drag-and-drop editing of topology
- Agent-to-agent A2A discovery (no runtime protocol introspection)

---

## Data Model Changes

### New field: `network_scope`

Added to **MCP server instances** and **Skills**:

```
network_scope: "private" | "ingress" | "egress"
```

- **`private`** — fully contained within the VPC. No external connectivity. Default value.
- **`ingress`** — receives traffic from external sources (e.g., webhook trigger receiver, Telegram bot listener).
- **`egress`** — calls out to external services (e.g., GitHub API MCP, Slack MCP, Stripe MCP).

**Triggers** are implicitly classified:
- Triggers with webhook URLs = ingress (external traffic entering the system)
- Scheduled/cron triggers = private (internal clock, no external traffic)

**Agents** are always in the VPC internal zone — they don't directly face external traffic.

### Migration

- Add `network_scope VARCHAR(10) DEFAULT 'private'` to `mcp_server_instances` and `skills` tables
- Add corresponding field to domain models and ORM

### Topology API changes

- Return `network_scope` in node metadata for MCP instances and skills
- Return trigger type in trigger metadata so frontend can infer ingress vs private
- Add `delegation_targets` to agent metadata when an agent references other agents in its tool config

---

## Frontend Architecture

### Page structure

```
/network (page.tsx)
  └── NetworkClient.tsx
        ├── Tab: "Organization" → OrgChartView.tsx
        └── Tab: "Data Flow"   → DataFlowView.tsx
```

### Tab switching

Simple tab UI using existing Shadcn `Tabs` component. Both tabs share the same topology data fetched once.

---

## Data Flow Tab (VPC View)

### Zone layout — left to right

Three data zones plus two inferred label zones, rendered as subtle bordered regions on the canvas:

```
[Public Sources] → GATEWAY (ingress) → VPC INTERNAL (governed) → EGRESS → [External Services]
```

1. **Public Sources** (leftmost) — inferred labels for external sources that send traffic in (e.g., "Telegram", "Slack", "GitHub Webhooks"). Not actual data nodes — decorative labels derived from trigger source metadata. Light red/orange tinted background.

2. **Gateway** — triggers with ingress scope. This is where external traffic first hits governance. Governance interceptor pills shown on the boundary between Public Sources and Gateway.

3. **VPC Internal** — agents + private skills + private MCPs. The governed core. Agents are primary nodes; their private skills and MCPs cluster around them.

4. **Egress** — MCPs and skills with `network_scope: "egress"`. Arrows point outward toward external services. Governance interceptor pills on this boundary too.

5. **External Services** (rightmost) — inferred labels for external APIs that egress MCPs connect to (e.g., "GitHub API", "Stripe"). Decorative labels, not data nodes.

### Node cards (Doubleloop style)

White cards, `rounded-xl`, subtle shadow (`shadow-sm`), 1px `border-zinc-200`:

```
┌─────────────────────────────────┐
│  🤖 Agent              ↗ link  │  ← category icon + type label + external link
│  Customer Support Bot          │  ← entity name, bold
│                                │
│  gpt-4o  ·  3 skills  ·  active│  ← inline metadata
└─────────────────────────────────┘
```

Category labels by entity type:
- `Agent` — blue icon
- `MCP / Private` or `MCP / Egress` — green icon, scope shown
- `Skill / Private` or `Skill / Egress` — purple icon, scope shown
- `Trigger / Ingress` or `Trigger / Private` — amber icon

### Edges

- Thin (`1px`), muted gray (`#d4d4d8`) bezier curves
- Small arrowhead at target end
- Solid for active connections, dashed for inactive/configured-but-disabled
- **Risk edges**: connections crossing zone boundaries get orange/red stroke + small warning icon. Specifically:
  - Public → Gateway (ingress point)
  - VPC Internal → Egress (data leaving the VPC)

### Risk indicators

Explicitly surfaced on the canvas:
- **Unprotected ingress**: trigger receiving external traffic with no governance interceptors → red warning badge on the trigger card
- **Uncontrolled egress**: MCP calling external API with `network_scope: egress` and no capability guard → orange warning badge
- **Missing governance**: enterprise mode with governance overlay disabled → banner at top

### Governance boundary markers

In enterprise mode, governance interceptors appear as small pill badges on zone boundaries:
- Between Public and Gateway: `prompt_injection_detector`, `content_policy_enforcer`
- Between VPC Internal and Egress: `capability_guard`, `mcp_tool_scanner`
- These are rendered as semi-transparent pills positioned on the zone border lines

### Node positioning within zones

- Nodes are positioned automatically using React Flow with dagre layout, but constrained to their zone's x-range
- Zone x-ranges are calculated based on node count per zone
- Vertical positioning within a zone follows dagre's ranking

---

## Organization Tab

### Layout

Top-to-bottom tree hierarchy using dagre `TB` direction.

### Structure

- **Agents** as primary cards (largest, top tier)
- **Skills, MCPs, Triggers** as smaller cards below their parent agent, connected by edges
- **Agent-to-agent delegation**: when Agent A's tool config references Agent B, draw a delegation edge between them (solid, labeled "delegates_to")
- **A2A external connections**: if detected, shown with egress risk indicator

### Cards

Same Doubleloop card style as Data Flow tab. Agent cards are slightly larger with more metadata:

```
┌─────────────────────────────────┐
│  🤖 Agent              ↗ link  │
│  Customer Support Bot          │
│                                │
│  Model: gpt-4o                 │
│  Skills: 3  ·  MCPs: 2        │
│  Triggers: 1  ·  Status: active│
└─────────────────────────────────┘
```

Skill/MCP/Trigger cards are compact:

```
┌──────────────────────┐
│  ⚡ Skill / Private   │
│  Text Summarizer     │
└──────────────────────┘
```

---

## Shared Visual Style

### Background
- Subtle dot grid on light gray (`bg-zinc-50` / `#fafafa`)
- Dark mode: `bg-zinc-900` with dimmed dot grid

### Cards
- `bg-white rounded-xl shadow-sm border border-zinc-200`
- Dark mode: `bg-zinc-800 border-zinc-700`
- Category label: `text-xs text-muted-foreground` with colored icon (blue/green/purple/amber)
- Entity name: `text-sm font-semibold`
- Metadata: `text-xs text-muted-foreground`

### Edges
- Default: `stroke: #d4d4d8`, `stroke-width: 1.5`, bezier curve
- Risk: `stroke: #f97316` (orange-500), `stroke-width: 2`
- Inactive: `stroke-dasharray: 5,5`

### Color palette (icons and accents only — not card backgrounds)
- Agent: `blue-500`
- MCP: `green-500`
- Skill: `purple-500`
- Trigger: `amber-500`
- Risk: `orange-500` / `red-500`
- Governance: `slate-400`

### Zone containers (Data Flow tab only)
- Subtle bordered regions: `border border-dashed border-zinc-300 rounded-2xl`
- Faint tinted backgrounds per zone:
  - Public: `bg-red-50/30`
  - Gateway: `bg-amber-50/30`
  - VPC Internal: `bg-blue-50/30`
  - Egress: `bg-orange-50/30`
- Zone label: `text-xs font-medium text-muted-foreground uppercase tracking-wider` at top of zone

---

## File Structure

### New files
```
agentarea-webapp/src/app/(main)/network/
  NetworkClient.tsx              # Refactored: tab switcher + shared data fetch
  views/
    DataFlowView.tsx             # VPC zone layout with React Flow
    OrgChartView.tsx             # Tree hierarchy with React Flow
  components/
    nodes/
      AgentNode.tsx              # Restyled Doubleloop-style card
      MCPNode.tsx                # With network_scope label
      SkillNode.tsx              # With network_scope label
      TriggerNode.tsx            # With inferred ingress/private
    edges/
      DataFlowEdge.tsx           # Bezier with risk indicator support
    ZoneContainer.tsx            # SVG/HTML zone region for Data Flow
    GovernancePill.tsx           # Small interceptor badge on zone boundary
    RiskBadge.tsx                # Warning badge on cards/edges
    NodeCard.tsx                 # Shared Doubleloop-style card wrapper
    NetworkToolbar.tsx           # Filters, refresh, tab-specific controls
    NodeDetailPanel.tsx          # Click-to-open detail panel
```

### Modified files
```
agentarea-platform/libs/mcp/agentarea_mcp/domain/mpc_server_instance_model.py  # Add network_scope field+column
agentarea-platform/libs/agents/agentarea_agents/domain/skill_models.py         # Add network_scope field+column
agentarea-platform/apps/api/.../network.py          # Return network_scope in metadata
alembic migration                                   # Add network_scope columns
```

### Removed files (old React Flow components)
```
agentarea-webapp/src/app/(main)/network/components/edges/RelationshipEdge.tsx
agentarea-webapp/src/app/(main)/network/components/GovernanceSidebar.tsx
```

---

## Backend API

No new endpoints. The existing `GET /v1/network/topology` is extended:

- Node metadata includes `network_scope` for MCPs and skills
- Node metadata includes `trigger_type` for triggers (so frontend can infer ingress vs private)
- Node metadata includes `delegation_targets: string[]` for agents that reference other agents via tool entries where `tool_server_id` / `server_id` points to another agent's ID (future: explicit delegation field on agent model)

Response schema unchanged — `NetworkNode.metadata` dict carries the new fields.

---

## Verification

1. **Data Flow tab**: entities placed in correct zones based on `network_scope` / trigger type
2. **Risk edges**: boundary-crossing connections highlighted in orange with warning icon
3. **Org tab**: agents shown with their skills/MCPs/triggers as children; delegation edges drawn
4. **Cards**: Doubleloop style — white, rounded, content-rich, muted color accents
5. **Zones**: subtle bordered regions with tinted backgrounds and labels
6. **Governance pills**: visible only in enterprise mode, positioned on zone boundaries
7. **Dark mode**: cards, zones, edges all adapt correctly
8. **Empty state**: graceful when no entities exist
9. **Tab persistence**: switching tabs preserves topology data (single fetch)
