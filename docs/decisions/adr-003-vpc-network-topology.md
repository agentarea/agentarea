# ADR-003: VPC-Style Network Topology View

**Date:** 2026-03-18
**Status:** Accepted

## Context

The platform manages agents, skills, MCP instances, and triggers across a workspace. As workspaces grow, operators need to understand two things simultaneously:

1. **Security topology** — what has external access, where trust boundaries are, what data can leave the governed environment, and where governance policies are enforced
2. **Business topology** — which agents are responsible for what, what capabilities they have, and how they relate to each other

The initial network view was a plain React Flow graph: all entities as flat nodes with generic edges. This failed to communicate trust boundaries or security risk. It also looked like a third-party widget rather than part of the product.

## Decision

We model the workspace as a **VPC (Virtual Private Cloud)** and represent it visually in two complementary tabs:

### `network_scope` field

MCP instances and skills gain a `network_scope: "private" | "ingress" | "egress"` field (default: `"private"`):

- **`private`** — fully contained within the VPC. No external connectivity.
- **`ingress`** — receives traffic from external sources (e.g., webhook trigger).
- **`egress`** — calls out to external services (e.g., an MCP connecting to GitHub API).

Triggers are classified automatically by type: `webhook` triggers are ingress, all others are private.

### Data Flow tab (VPC diagram)

Three visual zones rendered left-to-right:

```
Gateway (Ingress) → VPC Internal (Governed) → Egress
```

- Entities are placed into zones by their `network_scope`
- Edges crossing zone boundaries (Internal → Egress) are highlighted in orange with a ⚠ risk indicator
- Zone containers use dashed borders with tinted backgrounds

### Organization tab

A dagre top-to-bottom tree showing agents as primary nodes with their skills, MCPs, and triggers as children. Represents business ownership and capability structure.

### Visual style

Replaced the generic React Flow aesthetic with Doubleloop-inspired cards:
- White `rounded-xl` cards with subtle shadow and 1px border
- Category labels (`MCP / egress`, `Trigger / Ingress`) communicating scope inline
- Thin bezier edges (`#d4d4d8`), risk edges orange (`#f97316`)
- Dot-grid background, muted color accents

## Consequences

**Positive:**
- Operators can immediately see what has external access and where trust boundaries are
- Risk indicators surface ungoverned egress connections without requiring a separate audit
- `network_scope` becomes a foundation for future policy enforcement (e.g., "agents in this workspace may only use `private` MCPs")
- The visual style is native to the product rather than a dropped-in diagram widget
- Governance interceptors can later be rendered as pills on zone boundaries in enterprise mode

**Negative:**
- `network_scope` requires user intent at MCP/skill creation time — defaults to `private`, which is safe but may not reflect reality for existing MCPs
- The zone layout is static (not draggable) — sufficient for most workspaces but may become crowded at very high entity counts
- A2A delegation relationships between agents are not yet detected (requires explicit delegation metadata on agents)
