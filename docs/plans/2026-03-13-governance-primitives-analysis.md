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

## 4. Proposed Architecture — Unified Interceptor Framework

> **Updated 2026-03-15**: Aligned with OpenSpec design decisions (D1-D8). See `openspec/changes/governance-security-interceptors/design.md` for full rationale.

### Scope Clarification

**What we build:** A unified interceptor framework with dynamic registration at every execution boundary.
**What we don't build:** RBAC, auth, identity — handled by Ory (Kratos, Hydra, Keto). No new DB tables for policy storage.

### Design Principles (SOLID)

```
S — Each interceptor has one job (CapabilityGuard ≠ RateLimitGuard ≠ OutputSanitizer)
O — New interceptors added by implementing a Protocol, no existing code modified
L — Any ExecutionInterceptor is substitutable regardless of category
I — One thin protocol with category marker (gate/filter/observer) — not separate hierarchies
D — Execution layer depends on Protocol abstractions; Temporal bridge is an adapter, not the core
```

### Core Abstractions

```python
# ──────────────────────────────────────────────────────────────
# SINGLE PROTOCOL — all interceptor types implement this
# ──────────────────────────────────────────────────────────────

class InterceptorCategory(StrEnum):
    GATE = "gate"          # Pre-action: ALLOW/DENY/WARN/ESCALATE. Short-circuits on DENY.
    FILTER = "filter"      # Content: transforms input/output. Can BLOCK, MODIFY, or PASS.
    OBSERVER = "observer"  # Side-effect only: logging, metrics, billing. Never blocks.

class Phase(StrEnum):
    PRE_LLM_CALL = "pre_llm_call"
    POST_LLM_CALL = "post_llm_call"
    PRE_TOOL_CALL = "pre_tool_call"
    POST_TOOL_CALL = "post_tool_call"
    PRE_DELEGATION = "pre_delegation"
    POST_DELEGATION = "post_delegation"
    TOOL_DISCOVERY = "tool_discovery"

class InterceptorAction(StrEnum):
    ALLOW = "allow"       # Gate: proceed. Filter: content unchanged. Observer: noted.
    DENY = "deny"         # Gate: block action. Filter: block content.
    WARN = "warn"         # Gate: proceed with warning. Filter: proceed with warning.
    ESCALATE = "escalate" # Gate: route to human.
    MODIFY = "modify"     # Filter: content was transformed.

class ExecutionInterceptor(Protocol):
    """Single protocol for all interceptor types — guards, filters, observers."""

    @property
    def name(self) -> str: ...

    @property
    def category(self) -> InterceptorCategory: ...

    async def execute(self, context: InterceptorContext) -> InterceptorResult: ...

@dataclass
class InterceptorContext:
    """Domain object — no Temporal imports."""
    agent_id: UUID
    workspace_id: str
    user_id: str
    phase: Phase
    action_type: str           # "llm_call", "tool_call", "agent_delegation"
    action_name: str           # tool name, model id, target agent id
    action_params: dict[str, Any]
    content: str | None = None # Input/output content for filter phases
    execution_state: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class InterceptorResult:
    action: InterceptorAction
    interceptor_name: str
    reason: str
    modified_content: str | None = None
    findings: list[DetectionFinding] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


# ──────────────────────────────────────────────────────────────
# REGISTRY — dynamic registration with phase + priority
# ──────────────────────────────────────────────────────────────

class InterceptorRegistry:
    def register(
        self,
        interceptor: ExecutionInterceptor,
        phase: Phase,
        priority: int = 500,
        on_deny: Callable | None = None,
        on_warn: Callable | None = None,
        on_escalate: Callable | None = None,
    ) -> None: ...

    def unregister(self, name: str, phase: Phase) -> None: ...
    def get_interceptors(self, phase: Phase) -> list[ExecutionInterceptor]: ...  # sorted by priority


# ──────────────────────────────────────────────────────────────
# PIPELINE — chain of responsibility, infrastructure-agnostic
# ──────────────────────────────────────────────────────────────

class InterceptorPipeline:
    """Executes registered interceptors per phase. Handles gates, filters, observers."""

    def __init__(self, registry: InterceptorRegistry): ...

    async def run(self, phase: Phase, context: InterceptorContext) -> InterceptorResult:
        """Run all interceptors for this phase in priority order.
        - Gates: short-circuit on DENY/ESCALATE, fire callbacks
        - Filters: chain content modifications
        - Observers: fire-and-forget, never block
        """
        ...


# ──────────────────────────────────────────────────────────────
# DETECTION ENGINE — swappable strategy for filter interceptors
# ──────────────────────────────────────────────────────────────

class DetectionEngine(Protocol):
    """HOW to detect. Swap regex for Presidio, LLM judge, external API."""
    async def detect(self, content: str, config: dict[str, Any]) -> list[DetectionFinding]: ...

@dataclass(frozen=True)
class DetectionFinding:
    category: str           # "pii.email", "injection.override", "credential.api_key"
    matched_text: str
    span: tuple[int, int]
    confidence: float       # 0.0–1.0
    engine_name: str
```

### Temporal Bridge — Native ActivityInboundInterceptor

The bridge uses Temporal's native interceptor API. **Zero changes to existing activity code.**

```python
class GovernanceActivityInterceptor(ActivityInboundInterceptor):
    """Temporal adapter — delegates to InterceptorPipeline."""

    def __init__(self, next: ActivityInboundInterceptor, pipeline: InterceptorPipeline):
        super().__init__(next)
        self._pipeline = pipeline

    async def execute_activity(self, input: ExecuteActivityInput) -> Any:
        activity_name = input.fn.__name__
        pre_phase = self._resolve_pre_phase(activity_name)

        # Run pre-phase interceptors (gates + input filters)
        if pre_phase:
            context = self._build_context(input, pre_phase)
            result = await self._pipeline.run(pre_phase, context)
            if result.action == InterceptorAction.DENY:
                raise GovernanceDenied(result.reason)
            if result.action == InterceptorAction.ESCALATE:
                raise EscalationRequired(result)

        # Execute actual activity (unchanged)
        output = await self.next.execute_activity(input)

        # Run post-phase interceptors (output filters + observers)
        post_phase = self._resolve_post_phase(activity_name)
        if post_phase:
            context = self._build_context(input, post_phase, content=output)
            result = await self._pipeline.run(post_phase, context)
            if result.action == InterceptorAction.MODIFY:
                output = self._apply_modification(output, result)

        return output

# Registration at worker startup:
# Worker(interceptors=[GovernanceWorkerInterceptor(pipeline)])
```

### Concrete Interceptors — What We Build

**Gate interceptors** (category=GATE):

| Interceptor | Phases | What It Does | Config Source |
|-------------|--------|-------------|--------------|
| `CapabilityGuard` | pre_tool_call, pre_delegation | Check agent's allowed/denied tools list | Agent model |
| `CostBudgetGuard` | pre_llm_call, pre_tool_call | USD budget enforcement | Execution request |
| `TokenBudgetGuard` | pre_llm_call | Token usage tracking with warn/stop | Execution request |
| `RateLimitGuard` | pre_tool_call, pre_llm_call | Per-agent token bucket rate limiting | Workspace settings + Redis |
| `SemanticGuard` | pre_tool_call | Block destructive actions (DROP TABLE, rm -rf) | Code-level rules |
| `CircuitBreakerGuard` | pre_tool_call, pre_delegation | Open after N consecutive failures | Redis |
| `EscalationGuard` | pre_tool_call (configurable) | Route sensitive actions to human approval | Agent model |

**Filter interceptors** (category=FILTER, delegate to `DetectionEngine`):

| Interceptor | Phases | What It Does | Engine (v1 → future) |
|-------------|--------|-------------|---------------------|
| `PromptInjectionDetector` | pre_llm_call | Detect override attacks, encoding tricks | Regex → LLM-as-judge |
| `OutputSanitizer` | post_llm_call, post_tool_call | Redact PII, credentials, API keys | Regex → Presidio NER → custom ML |
| `ContentPolicyEnforcer` | pre_llm_call, post_llm_call | Block prohibited content categories | Keyword → embedding similarity |
| `MCPToolSecurityScanner` | tool_discovery | Detect tool poisoning, rug pulls | Regex → heuristic |

**Observer interceptors** (category=OBSERVER, fire-and-forget):

| Interceptor | Phases | What It Does |
|-------------|--------|-------------|
| `MetricsObserver` | all phases | Emit Prometheus counters per interceptor |
| `AuditObserver` | all phases | Emit governance events to EventBroker |
| Future: `BillingObserver` | pre_llm_call | Emit billing/metering events |

**Detection engines** (implement `DetectionEngine`, swappable per filter):

| Engine | Speed | Accuracy | When to Use |
|--------|-------|----------|-------------|
| `RegexDetectionEngine` | Fast | Low-Medium | v1 — zero deps, good enough for known patterns |
| `PresidioDetectionEngine` | Medium | High | PII detection — Microsoft Presidio NER models |
| `LLMJudgeDetectionEngine` | Slow | Highest | Semantic analysis — prompt injection, intent classification |
| `ExternalAPIDetectionEngine` | Variable | Variable | Delegate to external service (e.g. Azure AI Content Safety) |
| `CompositeDetectionEngine` | Varies | Highest | Chain multiple engines, merge findings, use confidence scores |

### Package Layout

```
agentarea-platform/libs/governance/agentarea_governance/
├── __init__.py
├── domain/
│   ├── models.py              # InterceptorContext, InterceptorResult, DetectionFinding
│   ├── protocols.py           # ExecutionInterceptor, DetectionEngine protocols
│   ├── enums.py               # InterceptorCategory, Phase, InterceptorAction
│   ├── events.py              # GovernanceViolation, SecurityFinding domain events
│   └── exceptions.py          # GovernanceDenied, SecurityBlocked, EscalationRequired
│
├── registry.py                # InterceptorRegistry (dynamic registration)
├── pipeline.py                # InterceptorPipeline (chain of responsibility)
│
├── interceptors/              # Concrete interceptors (all categories)
│   ├── gates/
│   │   ├── capability_guard.py
│   │   ├── cost_budget_guard.py
│   │   ├── token_budget_guard.py
│   │   ├── rate_limit_guard.py
│   │   ├── semantic_guard.py
│   │   ├── circuit_breaker_guard.py
│   │   └── escalation_guard.py
│   ├── filters/
│   │   ├── prompt_injection_detector.py
│   │   ├── output_sanitizer.py
│   │   ├── content_policy_enforcer.py
│   │   └── mcp_tool_scanner.py
│   └── observers/
│       ├── metrics_observer.py
│       └── audit_observer.py
│
├── engines/                   # Detection engines (swappable per filter)
│   ├── regex_engine.py
│   ├── presidio_engine.py
│   ├── llm_judge_engine.py
│   ├── external_api_engine.py
│   └── composite_engine.py
│
├── bridges/                   # Infrastructure adapters
│   └── temporal_bridge.py     # GovernanceActivityInterceptor (only file with temporalio import)
│
├── infrastructure/
│   └── redis_state.py         # Rate limit + circuit breaker state in Redis
│
└── factory.py                 # Build registry from config, register interceptors
```

### Cloud-Native Considerations

| Concern | Approach |
|---------|----------|
| **Rate limit state** | Redis with TTL — token bucket per agent, shared across workflow replicas |
| **Circuit breaker state** | Redis — failure counts per tool/agent, shared across workers |
| **Token budget** | In-workflow state (Temporal) — per-execution |
| **Metrics** | Emit to existing `EventBroker` + Prometheus counters via `MetricsObserver` |
| **MCP fingerprints** | In-memory hash cache with periodic refresh from tool discovery |
| **Horizontal scaling** | All interceptors stateless or use external state (Redis). Pipeline runs per-request. |
| **Interceptor config** | Each interceptor owns its source: Agent model, workspace settings, code-level defaults, Redis |
| **Auth/RBAC** | **External** — Ory handles auth, roles, permissions. Not our concern. |

---

## 5. Implementation Phases

### Phase 1: Framework + Temporal Bridge (Sprint 1)
> Protocols, registry, pipeline, Temporal adapter — empty pass-through

- [ ] Create `libs/governance/` package
- [ ] Define `ExecutionInterceptor` protocol with `category` marker
- [ ] Define `InterceptorContext`, `InterceptorResult`, `Phase`, `InterceptorAction` models
- [ ] Implement `InterceptorRegistry` (register/unregister with phase + priority + callbacks)
- [ ] Implement `InterceptorPipeline` (chain of responsibility with category-aware execution)
- [ ] Implement `GovernanceActivityInterceptor` (Temporal bridge)
- [ ] Register bridge on `Worker(interceptors=[...])` at startup with empty registry — no-op pass-through
- [ ] Factory to build registry from config

### Phase 2: Core Gate Interceptors (Sprint 2)
> First real enforcement — capabilities + budgets

- [ ] `CapabilityGuard` — allowed/denied tools per agent
- [ ] `CostBudgetGuard` — extract from existing `BudgetTracker` into interceptor protocol
- [ ] `TokenBudgetGuard` — track token usage per execution with warn/stop
- [ ] `RateLimitGuard` — Redis-backed token bucket per agent/workspace
- [ ] `MetricsObserver` + `AuditObserver` — emit events/metrics for all interceptor decisions

### Phase 3: Filter Interceptors + Detection Engines (Sprint 3)
> Input/output content filtering with swappable engines

- [ ] `DetectionEngine` protocol + `RegexDetectionEngine` (v1)
- [ ] `PromptInjectionDetector` — screen inputs for override/encoding attacks
- [ ] `OutputSanitizer` — redact PII, credentials, API keys from responses
- [ ] `MCPToolSecurityScanner` — tool poisoning + rug-pull detection at discovery time

### Phase 4: Advanced Gates + Escalation (Sprint 4)
> Semantic analysis, circuit breaking, human approval

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

- Execution Rings (agent trust tiers → different registry configs per tier)
- Trust Scoring (compliance history → dynamic priority adjustment)
- Kill Switch + Quarantine (governance-level agent termination)
- Supervisor Hierarchy + Trust Root (deterministic approval chains)
- Memory Guard (when we add persistent agent memory)
- Advanced detection engines: `PresidioDetectionEngine`, `LLMJudgeDetectionEngine`, `ExternalAPIDetectionEngine`
- Payment/billing interceptors
- Replay Debugging (execution recording for governance audits)

---

## 6. Key Design Decisions

### Q: Why one protocol with categories instead of separate protocol hierarchies?
**A:** Earlier design had `GovernanceInterceptor` + `SecurityProcessor` as separate protocols. But payments, compliance, metrics don't fit neatly into either. A single `ExecutionInterceptor` with `category` (gate/filter/observer) means the pipeline knows HOW to execute each (gates short-circuit, filters transform, observers fire-and-forget) without needing N protocol types. See design doc D1.

### Q: Why use Temporal's native ActivityInboundInterceptor?
**A:** Zero changes to existing activity code — interception is transparent. Activities don't need to know about governance. The `InterceptorPipeline` itself has zero Temporal imports — the bridge is the only Temporal-aware code. Consistent with how Temporal's own OpenTelemetry tracing works. See design doc D4.

### Q: Why dynamic registry instead of static pipeline construction?
**A:** New interceptor types (payments, NER, compliance, third-party gates) must be addable without modifying existing code. `registry.register(interceptor, phase, priority)` at startup — open-source, commercial, or custom implementations all plug in the same way.

### Q: Why not adopt microsoft/agent-governance-toolkit directly?
**A:** Their toolkit is Python middleware for single-process agents. We run distributed (Temporal + K8s + MCP containers). We need:
- State in Redis/PostgreSQL, not in-memory
- Enforcement at Temporal activity boundaries, not function decorators
- Workspace-scoped config, not global
- Integration with our event system
We adopt their **concepts and patterns**, not their code.

### Q: How do interceptors compose?
**A:** Per-phase priority ordering. Lower number = runs first. DENY always wins (fail-closed). Callbacks (on_deny, on_warn, on_escalate) fire as side-effects at registration, not inside interceptors.

### Q: What about auth/RBAC?
**A:** Handled by Ory (Kratos, Hydra, Keto). Our interceptors enforce **agent-level execution constraints** (what can this agent do), not user-level permissions (what can this user access).

---

## 7. References

- [Microsoft Agent Governance Toolkit](https://github.com/microsoft/agent-governance-toolkit)
- [OWASP Agentic Top 10](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/)
- [Temporal Python SDK — Interceptors](https://github.com/temporalio/sdk-python#interceptors)
- OpenSpec design: `openspec/changes/governance-security-interceptors/design.md`
- Existing plans: `2026-03-10-security-proxy-typing-design.md`, `2026-03-10-a2a-spec-compliance.md`
- Existing execution: `agentarea_execution.activities.agent_execution_activities.make_agent_activities()`
