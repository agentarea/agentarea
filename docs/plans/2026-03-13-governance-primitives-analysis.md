# Agent Governance Primitives — Gap Analysis & Integration Plan

**Date:** 2026-03-13
**Source:** [microsoft/agent-governance-toolkit](https://github.com/microsoft/agent-governance-toolkit)
**Goal:** Identify governance primitives worth adopting, map to our architecture, plan cloud-native integration with SOLID principles.

---

## 1. Full Capability Map

### Microsoft Toolkit Packages

| Package | Purpose | Key Primitives |
|---------|---------|---------------|
| **agent-os** | Policy engine core | PolicyEngine, CapabilityModel, MuteAgent, ContextBudget, ConstraintGraph, MemoryGuard, MCPSecurity, PromptInjection, Sandbox, Supervisor/TrustRoot, SemanticPolicy, RBAC, RateLimiter, TokenBudget, Escalation, Metrics |
| **agent-mesh** | Inter-agent trust | Ed25519 Identity, SPIFFE creds, TrustScoring (0-1000), A2A/MCP bridges, Namespace isolation, Delegation chains, Credential rotation, Marketplace signing |
| **agent-hypervisor** | Execution runtime | Execution Rings (4-tier), Saga orchestration, Kill switch, Quarantine, Liability ledger, Causal tracing, Session isolation, Vector clocks, Breach detection |
| **agent-sre** | Reliability | SLO engine, Error budgets, Circuit breakers, Chaos engineering, Replay debugging, Progressive delivery, Anomaly/rogue detection, Cost guard |
| **agent-compliance** | Regulatory | GDPR/HIPAA/SOX audit, Integrity verification |
| **agent-marketplace** | Plugin lifecycle | Discover, install, verify, sign plugins |
| **agent-lightning** | RL training gov | Governed runners, Policy rewards |

---

## 2. What We Already Have

| Capability | AgentArea Implementation | Coverage |
|-----------|------------------------|----------|
| **Workspace isolation** | `WorkspaceScopedMixin` + `WorkspaceScopedRepository` | **Strong** — all data scoped |
| **Audit trail** | `AuditLogger` (CREATE/UPDATE/DELETE/READ) | **Partial** — informational only, no enforcement |
| **Budget tracking** | `BudgetTracker` + `constants.py` ($10 default, 80% warn) | **Partial** — USD only, global defaults |
| **Execution timeouts** | Temporal activity timeouts (2min LLM, 3min tool) | **Strong** — enforced by Temporal |
| **Iteration limits** | `MAX_ITERATIONS=50`, `MAX_TOOL_CALLS_PER_ITERATION=10` | **Partial** — hard-coded, not per-agent |
| **Container security** | MCP Manager: image validation, command sanitization, registry whitelist | **Strong** — comprehensive input validation |
| **Container resources** | `MaxContainers`, `DefaultMemoryLimit`, `DefaultCPULimit` | **Partial** — global, not per-workspace |
| **Event system** | `DomainEvent` → Redis pub/sub + DB + SSE | **Strong** — full event pipeline |
| **Error classification** | `_is_auth_error()`, `_is_rate_limit_error()`, etc. | **Partial** — classification exists, no automated response |
| **Human approval** | `requires_human_approval` flag + `HumanApprovalRequested` event | **Partial** — flag exists, no approval workflow |
| **Auth context** | `UserContext(user_id, workspace_id, roles)` | **Partial** — roles field unused |
| **Context management** | `CONTEXT_COMPACT_THRESHOLD=0.75` | **Partial** — compaction exists, no token budgeting |

---

## 3. Gap Analysis — What We DON'T Have

### Tier 1: High Value, Natural Fit (integrate first)

| # | Primitive | MS Toolkit Source | Why We Need It | Integration Effort |
|---|-----------|------------------|----------------|-------------------|
| 1 | **Policy Engine** | `agent_os.policies` | Replace hard-coded constants with declarative YAML policies per agent/workspace. Foundation for everything else. | **Medium** — new `libs/governance/` domain |
| 2 | **Capability Model** | `agent_os.integrations.base.GovernancePolicy` | Define per-agent allowed/denied tools, token limits, cost limits. Currently any agent can call any attached tool. | **Medium** — extend Agent model + enforce at activity boundary |
| 3 | **Rate Limiting** | `agent_os.integrations.rate_limiter` | Per-agent/per-workspace tool call rate limits. Token bucket algorithm. Currently no rate limiting. | **Low** — standalone, plug into execution activities |
| 4 | **Token Budget Tracker** | `agent_os.integrations.token_budget` + `context_budget.py` | Track token usage per agent with SIGWARN/SIGSTOP signals. We only track USD cost. | **Low** — extend `BudgetTracker`, LLM responses already include token counts |
| 5 | **Output Sanitization (Mute)** | `agent_os.mute_agent` | Redact PII/credentials from agent output before returning to user. Currently no output filtering. | **Low** — post-processing step, no model changes |
| 6 | **MCP Tool Security Scanner** | `agent_os.mcp_security` | Detect tool poisoning, rug pulls, description injection in MCP tool definitions. We validate images but not tool schemas. | **Medium** — integrate into MCP Manager tool discovery |
| 7 | **Escalation Workflow** | `agent_os.integrations.escalation` | Full human-in-the-loop with timeout+default action. We have the flag but no workflow. | **Medium** — needs approval queue + Temporal signal handling |

### Tier 2: Medium Value, Strategic Investment

| # | Primitive | MS Toolkit Source | Why We Need It | Integration Effort |
|---|-----------|------------------|----------------|-------------------|
| 8 | **Prompt Injection Detection** | `agent_os.prompt_injection` | Screen user inputs for override attacks, encoding attacks, jailbreaks. | **Low** — pre-processing step before LLM call |
| 9 | **Semantic Policy** | `agent_os.semantic_policy` | Intent-based classification (DESTRUCTIVE_DATA, PRIVILEGE_ESCALATION, etc.) instead of brittle string matching. | **Medium** — integrates with policy engine |
| 10 | **RBAC** | `agent_os.integrations.rbac` | Role-based access control (READER/WRITER/ADMIN/AUDITOR) with per-role policies. `UserContext.roles` already exists. | **Low** — wire up existing unused field |
| 11 | **Constraint Graph** | `agent_os.constraint_graph` | DAG-based resource ACL — allow/deny rules with conditions for tool access. More flexible than flat allow-lists. | **Medium** — replaces simple tool lists |
| 12 | **Memory Guard** | `agent_os.memory_guard` | Hash integrity + injection detection for agent memory/context. | **Medium** — relevant when we add persistent agent memory |
| 13 | **Governance Metrics** | `agent_os.metrics` | Track policy checks, violations, approvals, blocked calls with latency. Foundation for SLO. | **Low** — emit to existing event system + Prometheus |
| 14 | **Circuit Breaker** | `agent_sre.cascade.circuit_breaker` | Prevent cascading failures in agent-to-agent delegation and external tool calls. | **Low** — well-understood pattern, wraps tool execution |

### Tier 3: Future / Advanced

| # | Primitive | MS Toolkit Source | Why We Need It | Integration Effort |
|---|-----------|------------------|----------------|-------------------|
| 15 | **Execution Rings** | `hypervisor.rings` | 4-tier privilege system (Ring 0=kernel, Ring 3=untrusted). Classify agents by trust level. | **High** — architectural change to execution model |
| 16 | **Trust Scoring** | `agentmesh.trust` | Score agents 0-1000 based on compliance history. Decay + reward system. | **High** — needs history aggregation + scoring pipeline |
| 17 | **Kill Switch** | `hypervisor.security.kill_switch` | Emergency agent termination. We have Temporal cancellation but no governance-level kill. | **Medium** — extend Temporal workflow signals |
| 18 | **Quarantine** | `hypervisor.liability.quarantine` | Isolate misbehaving agents. Block execution, retain for investigation. | **Medium** — agent status field + enforcement |
| 19 | **Supervisor Hierarchy** | `agent_os.supervisor` + `trust_root` | Layered supervision with deterministic (non-LLM) trust root. | **High** — changes agent delegation architecture |
| 20 | **Saga Orchestration** | `hypervisor.saga` | Multi-step transactions with compensation. We use Temporal workflows but no saga pattern. | **Medium** — Temporal already supports saga natively |
| 21 | **Causal Tracing** | `hypervisor.observability.causal_trace` | Track cause-effect chains across agent delegations. | **Medium** — extend event system with causal IDs |
| 22 | **SLO Engine** | `agent_sre.slo` | Define SLOs for agent performance (latency, success rate, cost). Error budgets. | **Medium** — needs metric aggregation |
| 23 | **Chaos Engineering** | `agent_sre.chaos` | Inject failures to test agent resilience. | **Medium** — test tooling, not production code |
| 24 | **Replay Debugging** | `agent_sre.replay` | Capture and replay agent executions for debugging. | **High** — needs execution recording infrastructure |
| 25 | **Rogue Agent Detection** | `agent_sre.anomaly.rogue_detector` | Detect anomalous agent behavior patterns. | **High** — needs baseline + ML pipeline |
| 26 | **Agent Identity (Ed25519)** | `agentmesh.identity` | Cryptographic agent identity with SPIFFE. | **High** — infrastructure change |
| 27 | **Marketplace Signing** | `agent_marketplace.signing` | Verify plugin/skill integrity with signatures. | **Medium** — extends registry system |
| 28 | **Progressive Delivery** | `agent_sre.delivery` | Blue/green, canary rollouts for agent updates. | **High** — deployment infrastructure |
| 29 | **Cost Guard** | `agent_sre.cost` | Cost anomaly detection + optimizer. | **Medium** — extends budget tracking |

---

## 4. Proposed Architecture — Execution Boundary Interceptors

### Scope Clarification

**What we build:** Interceptors at every action boundary within our execution engine.
**What we don't build:** RBAC, auth, identity — handled by external systems (Ory, etc.).

Two distinct concerns, two separate abstractions:
1. **Governance** — pre-action gates: *"Should this action proceed?"* (budget, rate limits, capabilities, escalation)
2. **Security** — input/output processing: *"Is this content safe?"* (injection detection, PII redaction, tool poisoning)

### Design Principles (SOLID)

```
S — Each interceptor has one job (CapabilityGuard ≠ RateLimitGuard ≠ OutputSanitizer)
O — New interceptors added by implementing a Protocol, no existing code modified
L — Any GovernanceInterceptor is substitutable; any SecurityProcessor is substitutable
I — Two thin interfaces, not one fat one (governance ≠ security)
D — Execution layer depends on Protocol abstractions, injected via DI container
```

### Core Abstractions

```python
# ──────────────────────────────────────────────────────────────
# GOVERNANCE — Pre-action gates (should this proceed?)
# ──────────────────────────────────────────────────────────────

class GovernanceAction(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    WARN = "warn"
    ESCALATE = "escalate"  # Route to human approval

@dataclass(frozen=True)
class GovernanceDecision:
    action: GovernanceAction
    reason: str
    guard_name: str
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class GovernanceContext:
    """Everything a guard needs to make a decision."""
    agent_id: UUID
    workspace_id: str
    user_id: str
    action_type: str          # "tool_call", "llm_call", "agent_delegation"
    action_name: str          # tool name, model id, target agent id
    action_params: dict[str, Any]
    execution_state: dict[str, Any]  # iteration count, budget used, etc.

class GovernanceInterceptor(Protocol):
    """Single governance check. Implement this to add new governance rules."""

    @property
    def name(self) -> str: ...

    async def check(self, context: GovernanceContext) -> GovernanceDecision: ...


class GovernancePipeline:
    """Chain of Responsibility — composes interceptors, short-circuits on DENY/ESCALATE."""

    def __init__(
        self,
        interceptors: list[GovernanceInterceptor],
        event_broker: EventBroker,
    ):
        self._interceptors = interceptors
        self._event_broker = event_broker

    async def evaluate(self, context: GovernanceContext) -> GovernanceDecision:
        for interceptor in self._interceptors:
            decision = await interceptor.check(context)
            match decision.action:
                case GovernanceAction.DENY | GovernanceAction.ESCALATE:
                    await self._emit_event(decision, context)
                    return decision
                case GovernanceAction.WARN:
                    await self._emit_event(decision, context)
                    # Continue — warning is informational
        return GovernanceDecision(
            action=GovernanceAction.ALLOW,
            reason="all checks passed",
            guard_name="pipeline",
        )


# ──────────────────────────────────────────────────────────────
# SECURITY — Content processing (is this safe?)
# ──────────────────────────────────────────────────────────────

class SecurityVerdict(StrEnum):
    CLEAN = "clean"
    MODIFIED = "modified"    # Content was sanitized
    BLOCKED = "blocked"      # Content rejected entirely

@dataclass(frozen=True)
class SecurityResult:
    verdict: SecurityVerdict
    original_content: str | None   # None if not modified
    processed_content: str | None  # The cleaned/modified content
    findings: list[str]            # What was detected
    processor_name: str

class DetectionEngine(Protocol):
    """Swappable detection strategy — the HOW behind security checks.

    Start with regex, swap to ML model or external API later.
    The SecurityProcessor delegates to this — processors define WHAT
    to check, engines define HOW to check it.
    """

    async def detect(
        self, content: str, patterns: dict[str, Any]
    ) -> list[DetectionFinding]: ...

@dataclass(frozen=True)
class DetectionFinding:
    category: str           # "pii.email", "injection.override", "credential.api_key"
    matched_text: str
    start: int
    end: int
    confidence: float       # 0.0–1.0
    engine_name: str        # "regex", "ml_classifier", "llm_judge", "presidio"


class SecurityProcessor(Protocol):
    """Content processor for input or output. Implement to add new security checks.

    Each processor uses a DetectionEngine internally. The engine is
    injected at construction — swap regex for ML, external API, or
    LLM-as-judge without changing the processor or the pipeline.

    Example evolution:
        v1: RegexDetectionEngine     — pattern matching (fast, no deps)
        v2: PresidioDetectionEngine  — Microsoft Presidio NER-based PII
        v3: LLMJudgeDetectionEngine  — use an LLM to classify intent
        v4: CompositeEngine          — chain multiple engines, merge findings
    """

    @property
    def name(self) -> str: ...

    async def process(
        self,
        content: str,
        context: GovernanceContext,
        direction: Literal["input", "output"],
    ) -> SecurityResult: ...


class SecurityPipeline:
    """Composes security processors — each can modify or block content."""

    def __init__(
        self,
        input_processors: list[SecurityProcessor],
        output_processors: list[SecurityProcessor],
        event_broker: EventBroker,
    ):
        self._input_processors = input_processors
        self._output_processors = output_processors
        self._event_broker = event_broker

    async def process_input(
        self, content: str, context: GovernanceContext
    ) -> SecurityResult:
        """Run all input processors (prompt injection, encoding attacks, etc.)"""
        current = content
        all_findings = []
        for processor in self._input_processors:
            result = await processor.process(current, context, "input")
            if result.verdict == SecurityVerdict.BLOCKED:
                await self._emit_event(result, context)
                return result
            if result.verdict == SecurityVerdict.MODIFIED:
                current = result.processed_content
            all_findings.extend(result.findings)
        return SecurityResult(
            verdict=SecurityVerdict.MODIFIED if current != content else SecurityVerdict.CLEAN,
            original_content=content if current != content else None,
            processed_content=current,
            findings=all_findings,
            processor_name="pipeline",
        )

    async def process_output(
        self, content: str, context: GovernanceContext
    ) -> SecurityResult:
        """Run all output processors (PII redaction, credential scrubbing, etc.)"""
        current = content
        all_findings = []
        for processor in self._output_processors:
            result = await processor.process(current, context, "output")
            if result.verdict == SecurityVerdict.BLOCKED:
                await self._emit_event(result, context)
                return result
            if result.verdict == SecurityVerdict.MODIFIED:
                current = result.processed_content
            all_findings.extend(result.findings)
        return SecurityResult(
            verdict=SecurityVerdict.MODIFIED if current != content else SecurityVerdict.CLEAN,
            original_content=content if current != content else None,
            processed_content=current,
            findings=all_findings,
            processor_name="pipeline",
        )
```

### Where They Hook In — Execution Boundary Map

These interceptors wrap every action boundary in our Temporal execution flow:

```
AgentExecutionWorkflow.run()
│
├─ BOUNDARY 1: Agent Delegation (before calling child agents)
│   ├─ GovernancePipeline.evaluate(action_type="agent_delegation")
│   └─ SecurityPipeline.process_input(delegation_goal)
│
├─ BOUNDARY 2: LLM Call (call_llm_activity)
│   ├─ PRE:  GovernancePipeline.evaluate(action_type="llm_call")
│   ├─ PRE:  SecurityPipeline.process_input(user_messages)
│   ├─       ──── actual LLM call ────
│   └─ POST: SecurityPipeline.process_output(llm_response)
│
├─ BOUNDARY 3: Tool Execution (execute_mcp_tool_activity)
│   ├─ PRE:  GovernancePipeline.evaluate(action_type="tool_call")
│   ├─       ──── actual tool call ────
│   └─ POST: SecurityPipeline.process_output(tool_result)
│
├─ BOUNDARY 4: Tool Discovery (discover_available_tools_activity)
│   └─ POST: MCPToolSecurityScanner.scan(tool_definitions)
│
└─ BOUNDARY 5: Human Approval (when escalated)
    └─ GovernancePipeline returned ESCALATE → Temporal signal wait
```

### How It Integrates With Existing Code

The pipelines inject into `ActivityDependencies` (our existing DI for Temporal activities):

```python
# interfaces.py — extended
@dataclass
class ActivityDependencies:
    settings: "Settings"
    event_broker: "EventBroker"
    secret_manager_factory: "SecretManagerFactory"
    # NEW: governance + security pipelines
    governance_pipeline: "GovernancePipeline"
    security_pipeline: "SecurityPipeline"


# In make_agent_activities() — wrapping existing activities:

@activity.defn
async def call_llm_activity(request: LLMCallRequest) -> LLMCallResult:
    context = GovernanceContext(
        agent_id=request.agent_id,
        workspace_id=request.workspace_id,
        action_type="llm_call",
        action_name=request.model_id,
        ...
    )

    # GOVERNANCE: Should this LLM call proceed?
    decision = await dependencies.governance_pipeline.evaluate(context)
    if decision.action == GovernanceAction.DENY:
        raise GovernanceDenied(decision.reason)
    if decision.action == GovernanceAction.ESCALATE:
        raise EscalationRequired(decision)

    # SECURITY: Screen input content
    input_result = await dependencies.security_pipeline.process_input(
        request.messages[-1]["content"], context
    )
    if input_result.verdict == SecurityVerdict.BLOCKED:
        raise SecurityBlocked(input_result.findings)

    # ──── actual LLM call (existing code, unchanged) ────
    result = await _do_llm_call(request)

    # SECURITY: Sanitize output content
    output_result = await dependencies.security_pipeline.process_output(
        result.content, context
    )
    if output_result.verdict == SecurityVerdict.MODIFIED:
        result.content = output_result.processed_content

    return result
```

### Concrete Interceptors — What We Build

**Governance interceptors** (implement `GovernanceInterceptor`):

| Interceptor | Boundaries | What It Does |
|-------------|-----------|-------------|
| `CapabilityGuard` | tool_call, agent_delegation | Check agent's allowed/denied tools list |
| `CostBudgetGuard` | llm_call, tool_call | USD budget enforcement (extract from existing `BudgetTracker`) |
| `TokenBudgetGuard` | llm_call | Token usage tracking with warn/stop thresholds |
| `RateLimitGuard` | tool_call, llm_call | Per-agent token bucket rate limiting |
| `SemanticGuard` | tool_call | Intent classification — block destructive actions (DROP TABLE, rm -rf) |
| `CircuitBreakerGuard` | tool_call, agent_delegation | Prevent cascading failures (open after N consecutive failures) |
| `EscalationGuard` | tool_call (configurable) | Route sensitive actions to human approval |

**Security processors** (implement `SecurityProcessor`, delegate to `DetectionEngine`):

| Processor | Direction | What It Does | Engine (v1 → future) |
|-----------|-----------|-------------|---------------------|
| `PromptInjectionDetector` | input | Detect override attacks, encoding tricks, jailbreaks | Regex → LLM-as-judge |
| `OutputSanitizer` | output | Redact PII (email, phone, SSN), credentials, API keys | Regex → Presidio NER → custom ML |
| `ContentPolicyEnforcer` | input + output | Block prohibited content categories | Keyword → embedding similarity |

**Detection engines** (implement `DetectionEngine`, swappable per processor):

| Engine | Speed | Accuracy | When to Use |
|--------|-------|----------|-------------|
| `RegexDetectionEngine` | Fast | Low-Medium | v1 — zero deps, good enough for known patterns |
| `PresidioDetectionEngine` | Medium | High | PII detection — Microsoft Presidio NER models |
| `LLMJudgeDetectionEngine` | Slow | Highest | Semantic analysis — prompt injection, intent classification |
| `ExternalAPIDetectionEngine` | Variable | Variable | Delegate to external service (e.g. Azure AI Content Safety) |
| `CompositeDetectionEngine` | Varies | Highest | Chain multiple engines, merge findings, use confidence scores |

**Standalone scanner** (separate from pipeline, runs at tool discovery):

| Scanner | When | What It Does |
|---------|------|-------------|
| `MCPToolSecurityScanner` | discover_available_tools | Detect tool poisoning, rug pulls, description injection |

### Package Layout

```
agentarea-platform/libs/governance/agentarea_governance/
├── __init__.py
├── domain/
│   ├── models.py              # GovernanceContext, GovernanceDecision, SecurityResult
│   ├── events.py              # GovernanceViolation, SecurityFinding events
│   └── exceptions.py          # GovernanceDenied, SecurityBlocked, EscalationRequired
│
├── pipeline/                  # The two core abstractions
│   ├── governance_pipeline.py # GovernanceInterceptor protocol + pipeline
│   └── security_pipeline.py   # SecurityProcessor protocol + pipeline
│
├── governance/                # Governance interceptors (pre-action gates)
│   ├── capability_guard.py
│   ├── cost_budget_guard.py
│   ├── token_budget_guard.py
│   ├── rate_limit_guard.py
│   ├── semantic_guard.py
│   ├── circuit_breaker_guard.py
│   └── escalation_guard.py
│
├── security/                  # Security processors (content filtering)
│   ├── prompt_injection_detector.py
│   ├── output_sanitizer.py
│   ├── content_policy_enforcer.py
│   └── mcp_tool_scanner.py
│
├── engines/                   # Detection engines (HOW to detect — swappable)
│   ├── base.py                # DetectionEngine protocol + DetectionFinding
│   ├── regex_engine.py        # v1: Pattern matching (zero deps, fast)
│   ├── presidio_engine.py     # v2: Microsoft Presidio NER-based PII
│   ├── llm_judge_engine.py    # v3: LLM-as-judge for semantic analysis
│   ├── external_api_engine.py # v4: Delegate to external service
│   └── composite_engine.py    # Chain engines, merge findings by confidence
│
├── infrastructure/
│   ├── policy_repository.py   # DB persistence for governance policies
│   └── redis_state.py         # Rate limit + circuit breaker state in Redis
│
└── factory.py                 # Build pipelines from workspace config
```

### Cloud-Native Considerations

| Concern | Approach |
|---------|----------|
| **Policy storage** | PostgreSQL — workspace-scoped `governance_policy` table |
| **Rate limit state** | Redis with TTL — token bucket per agent, shared across workflow replicas |
| **Circuit breaker state** | Redis — failure counts per tool/agent, shared across workers |
| **Token budget** | In-workflow state (Temporal) — per-execution; aggregated in DB for history |
| **Metrics** | Emit to existing `EventBroker` + Prometheus counters per guard |
| **MCP fingerprints** | PostgreSQL — tool definition hashes for rug-pull detection |
| **Horizontal scaling** | All interceptors are stateless; external state in Redis/DB |
| **Configuration** | Per-workspace policy config in DB, editable via API, versioned |
| **Auth/RBAC** | **External** — Ory handles auth, roles, permissions. Not our concern. |

---

## 5. Implementation Phases

### Phase 1: Abstractions + Foundation (Sprint 1)
> Protocol definitions, pipeline infrastructure, inject into execution

- [ ] Create `libs/governance/` package
- [ ] Define `GovernanceInterceptor` and `SecurityProcessor` protocols
- [ ] Implement `GovernancePipeline` and `SecurityPipeline`
- [ ] Define `GovernanceContext`, `GovernanceDecision`, `SecurityResult` models
- [ ] Extend `ActivityDependencies` with pipeline injection
- [ ] Wire empty pipelines into all 5 execution boundaries (no-op pass-through)
- [ ] `GovernancePolicy` DB model + migration (workspace-scoped)
- [ ] Factory to build pipelines from workspace config

### Phase 2: Core Governance Guards (Sprint 2)
> First real enforcement — capabilities + budgets

- [ ] `CapabilityGuard` — allowed/denied tools per agent
- [ ] `CostBudgetGuard` — extract from existing `BudgetTracker` into guard protocol
- [ ] `TokenBudgetGuard` — track token usage per execution with warn/stop
- [ ] `RateLimitGuard` — Redis-backed token bucket per agent/workspace
- [ ] Governance events emitted to existing event system
- [ ] Governance metrics (Prometheus counters: checks, denials, warnings)

### Phase 3: Security Processors (Sprint 3)
> Input/output content filtering

- [ ] `PromptInjectionDetector` — screen inputs for override/encoding attacks
- [ ] `OutputSanitizer` — redact PII, credentials, API keys from responses
- [ ] `MCPToolSecurityScanner` — tool poisoning + rug-pull detection at discovery time
- [ ] Integration with MCP Manager tool discovery flow

### Phase 4: Advanced Governance (Sprint 4)
> Semantic analysis, circuit breaking, escalation

- [ ] `SemanticGuard` — intent classification for dangerous tool calls
- [ ] `CircuitBreakerGuard` — open after N failures, prevent cascading
- [ ] `EscalationGuard` — route to human approval via Temporal signals
- [ ] Full escalation workflow with timeout + default action

### Phase 5: Observability & Dashboard (Sprint 5+)
> Make governance visible

- [ ] Governance dashboard in webapp (violations, budgets, rate limits)
- [ ] Audit log enforcement (violations → notifications/webhooks)
- [ ] SLO foundation — track governance latency, false positive rates

### Future Considerations (Design Only)
> Items to track but not implement yet

- Execution Rings (agent trust tiers → different pipeline configs)
- Trust Scoring (compliance history → dynamic policy adjustment)
- Kill Switch + Quarantine (governance-level agent termination)
- Supervisor Hierarchy + Trust Root (deterministic approval chains)
- Memory Guard (when we add persistent agent memory)
- Replay Debugging (execution recording for governance audits)
- Chaos Engineering (test governance resilience)

---

## 6. Key Design Decisions

### Q: Why two protocols (Governance + Security) instead of one?
**A:** They solve fundamentally different problems:
- **Governance** is a gate — binary allow/deny decision, short-circuits on deny.
- **Security** is a filter — transforms content, may redact but still pass through.
Merging them would violate ISP and make guards harder to reason about.

### Q: Why not adopt microsoft/agent-governance-toolkit directly?
**A:** Their toolkit is Python middleware for single-process agents. We run distributed (Temporal + K8s + MCP containers). We need:
- State in Redis/PostgreSQL, not in-memory
- Enforcement at Temporal activity boundaries, not function decorators
- Workspace-scoped policies, not global config
- Integration with our event system
We adopt their **concepts and patterns**, not their code.

### Q: Why inject into ActivityDependencies instead of using Temporal interceptors?
**A:** Temporal's built-in interceptor API is for cross-cutting concerns at the SDK level (tracing, auth). Our governance is **business logic** — it needs access to agent config, workspace policies, and domain context. Injecting via our existing DI (`ActivityDependencies` → `ActivityContext`) keeps it in the domain layer where it belongs.

### Q: How do policies compose?
**A:** Workspace default → Agent-specific override. DENY always wins (fail-closed). Each guard evaluates independently — the pipeline composes decisions.

### Q: What about auth/RBAC?
**A:** Auth, roles, and permissions are handled by Ory (external). Our governance layer trusts the `UserContext` provided by the API layer. We don't duplicate identity or access control — we enforce **agent-level** policies (what can this agent do), not **user-level** permissions (what can this user access).

---

## 7. References

- [Microsoft Agent Governance Toolkit](https://github.com/microsoft/agent-governance-toolkit)
- [OWASP Agentic Top 10](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/)
- Existing plans: `2026-03-10-security-proxy-typing-design.md`, `2026-03-10-a2a-spec-compliance.md`
- Existing DI: `agentarea_execution.interfaces.ActivityDependencies`
- Existing execution: `agentarea_execution.activities.agent_execution_activities.make_agent_activities()`
