# ADR-006: One Edge Authorization Decision Point (admission), A2A included

**Date:** 2026-07-07
**Status:** Accepted (partially implemented)

## Implementation status

- **Single auth resolver** — `agentarea_common/auth/dependencies.py`
  `resolve_user_context_from_token` (JWT + `aat_` API key + Hydra); `get_optional_user`
  delegates to it.
- **Single edge decision point** — `agentarea_common/auth/access.py`
  `authorize_agent_action(subject, action, agent_workspace_id, agent_id)` with a
  data-driven public-grant hook (`_has_public_grant`, empty today).
- **A2A routed through both** — `a2a_auth.py` `require_a2a_auth` deleted its
  parallel authn + static permission lists; it now resolves the subject via the
  shared resolver and decides via `authorize_agent_action`. Verified live: an
  `aat_` API key that works over REST now executes over A2A (was 403);
  cross-workspace agent is denied (404/403); the A2A-created task runs to
  completion through Temporal.
- **REST execute** still enforces the same policy implicitly (workspace-scoped
  repo + `get_with_catalog` for built-ins). Adopting the explicit
  `authorize_agent_action` call at the REST edge is a low-risk follow-up that
  MUST preserve catalog/built-in execution (ADR-003).

## Context

Authorization at the request edge — "may this caller invoke this agent /
endpoint at all?" — is decided in several unrelated ways today. This is the
"who / per-principal" layer that ADR-005 explicitly **deferred** ("today
authorization is scope-based only; user_id rides in context but no gate reads
it").

Current state, one action ("execute this agent") authorized three different ways:

| Edge | How it authorizes execute today | Source |
|------|--------------------------------|--------|
| REST `POST /v1/agents/{id}/tasks` | workspace scope only (`UserContextDep`); **no execute check** | `apps/api/.../agents_tasks.py` |
| A2A `POST /v1/agents/{id}/a2a/rpc` | its own parallel authn + **hardcoded static lists** `PUBLIC_PERMISSIONS=[agent:read]` / `USER_PERMISSIONS=[…agent:execute…]` | `apps/api/.../a2a_auth.py` |
| MCP tool → agent, triggers | ad-hoc / scope | various |

Two concrete failures this produced (found during CLI QA, 2026-07):

1. **A2A rejects a legitimate caller.** The CLI authenticates with an AgentArea
   API key (`aat_…`). REST accepts it (`agentarea_common/auth/dependencies.py`
   `_validate_api_key`). A2A's `authenticate_bearer_token` does JWT-only
   verification and its `authenticate_api_key` is an unimplemented stub returning
   `None` — so the key fails, the context silently falls back to
   `PUBLIC_PERMISSIONS`, and `agent:execute` yields **403** even for the agent's
   owner. Same token, same user, executes fine over REST.
2. **"Public execution" is not expressible.** A2A's only nod to anonymous access
   is the hardcoded `PUBLIC_PERMISSIONS=[agent:read]` list. There is no way to
   say "this agent's execution is public" as data; and the edge 401s an
   anonymous caller before any policy is consulted, so a public-execute grant
   could never be honored.

The principle we adopt mirrors ADR-005's for governance: **every edge
authorization decision flows through one decision point. Parallel mechanisms are
removed, not kept.** It does not matter whether the engine behind that point is
ReBAC, a grant table, or scope checks — what matters is that there is exactly
**one place the policy is called and the decision is made**, and that every edge
(A2A included) funnels through it.

This ADR covers **admission** (the API/protocol boundary). It composes with, and
does not replace, ADR-005's **in-execution** governance (tools/budget/approval
enforced at the Temporal boundary). Edge decides *may you start*; governance
decides *what may happen while running*.

## Decision

### 1. One authentication seam → a Subject (incl. anonymous)

A single resolver turns a request into a `Subject`, regardless of edge or
credential type. It reuses today's REST path
(`agentarea_common/auth/dependencies.py`): Kratos JWT **and** `aat_` API key are
both resolved here, and it may also yield an **anonymous** subject rather than
raising 401 up front.

- A2A stops parsing auth itself. `a2a_auth.py`'s `extract_auth_from_request` /
  `authenticate_bearer_token` / `authenticate_api_key` and the
  `A2APermissions.*_PERMISSIONS` static lists are **deleted**.
- Anonymous is a first-class subject, not an error. Whether an anonymous subject
  is allowed is a **decision**, not a precondition — so the 401-before-policy
  behavior is removed for edges that can be public.

### 2. One authorization call → the edge PEP→PDP

Every edge, after resolving the Subject, calls the same function:

```
authorize(subject, action, resource) -> Decision   # ALLOW | DENY(reason)
```

- Called at: REST task submit, A2A `rpc` (`SendMessage`/`GetTask`/…), MCP
  tool-triggered execution, trigger-driven runs. One call site abstraction, one
  place the policy is invoked.
- `action` is a stable verb (`agent:execute`, `agent:read`, `agent:write`).
  A2A's "external permission" (e.g. `agent:execute`) becomes **an input to this
  call**, not a parallel list it checks itself.
- The **engine behind `authorize()` is pluggable and irrelevant to callers**:
  today it can be scope + a grant lookup; ReBAC/Keto/OpenFGA (already wired as
  `GraphClient` in `access_control.py`) when it lands; the governance policy
  engine can contribute. Callers never branch on the backend — mirrors ADR-005's
  "map to existing pieces, don't couple call sites to the engine."

REST **gains** this call on execute (it has none today), so REST and A2A become
identical at the edge.

### 3. Public / external execution is data, evaluated at the one point

"This agent may be executed publicly" is expressed as a **grant** (a ReBAC tuple
like `agent:<id>#executor@everyone`, or an equivalent policy/flag), not as a code
constant. Then:

- an **anonymous** subject is ALLOWed to execute iff the public-execute grant
  exists — decided by `authorize()`, not by a `PUBLIC_PERMISSIONS` list;
- a **keyed/JWT** subject is ALLOWed iff they hold the relation (owner/executor)
  **or** the public grant exists.

This is exactly "if we granted public A2A execution, it must run without a key" —
the edge admits the anonymous subject and the single decision point says yes.

### 4. Relationship to ADR-005 (no overlap)

| Layer | Question | Decision point | This ADR |
|-------|----------|----------------|----------|
| **Edge admission** | may this subject invoke? | `authorize()` PEP at each edge | **ADR-006 (new)** |
| **In-execution governance** | what may the run do (tools/budget/approval)? | policy engine + Temporal interceptor | ADR-005 (unchanged) |

ADR-005 deferred the per-principal "who / grant" algebra
(`granted ∩ within-ceiling \ denied`). ADR-006 **is** that layer for the edge:
default-deny, union of grants, deny-override. It stays out of the ceiling merge
(`PolicyResolver`), consistent with ADR-005's separation.

### 5. Explicit posture when the authz backend is unavailable

No silent fallback. When the grant/ReBAC backend is disabled or unreachable,
`authorize()` returns a **deliberate** decision, configured once, not a degraded
static list:

- **fail-closed** (default): deny non-owner execute; owner-in-workspace still
  allowed via the scope check that always runs. Recommended.
- **fail-open** (opt-in, documented): current workspace-scope behavior.

The choice is a settings decision surfaced in logs, never an implicit
`PUBLIC_PERMISSIONS` shortcut.

## Consequences

- Delete `apps/api/agentarea_api/api/v1/a2a_auth.py`'s permission model and its
  duplicate auth extraction; A2A routes through the shared authn + `authorize()`.
- Introduce the `authorize(subject, action, resource)` seam (thin service over
  the existing `GraphClient` / scope check / grant table) and call it from every
  edge. REST execute gains a real authorization check.
- API keys work uniformly across edges (the reported A2A 403 disappears as a
  class, because there is no second auth path to be missing).
- Public/anonymous execution becomes expressible and safe (data + one decision),
  unblocking A2A/agent-card public use cases.
- One place to audit, test, and reason about "who may do what at the edge."

## Deferred / follow-up

- Exact grant schema for public-execute (`#executor@everyone` tuple vs a policy
  flag) — pick when the ReBAC model for agents is finalized; the `authorize()`
  seam is stable regardless.
- Fine-grained A2A method → action mapping (`GetTask` = read, `SendMessage` =
  execute, push-config = write) — enumerated at the one call site.
- Rate/quota for anonymous public execution (abuse surface) — an execution-time
  governance concern (ADR-005 budget/quotas), not edge admission.
