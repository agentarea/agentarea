# ADR-004: Plan Entitlement Enforcement via Governance Pipeline Gate

**Date:** 2026-03-19
**Status:** Accepted

## Context

AgentArea Cloud/Enterprise needs to enforce plan-based access controls on LLM usage:

- Only workspaces on qualifying plans should be able to call certain models (e.g. GPT-4o, Claude Opus)
- Monthly token quotas must be enforced per workspace
- This logic must not exist in the OSS codebase — OSS users should have unrestricted access

Three placement options were considered:

1. **LLM infrastructure layer** — check inside `LLMClient` before each provider call
2. **API layer** — check in FastAPI endpoints when a task is submitted
3. **Governance pipeline gate** — check via `PRE_LLM_CALL` interceptor

Additionally, a standalone LLM proxy (e.g. LiteLLM) was evaluated as an alternative enforcement point.

## Decision

Enforce plan entitlements as a **governance pipeline gate** (`PlanEntitlementGuard`) at `PRE_LLM_CALL`, priority 120.

The guard is **enterprise-only**: it is registered exclusively via the `ExtensionRegistry` plugin mechanism using Python entry points (`agentarea.extensions`). When the enterprise package is not installed, no entitlement gate exists in the pipeline — OSS behavior is fully unrestricted without any no-op stub.

The guard calls an external **billing service** (`POST /entitlements/check`) and returns `DENY` on plan violations (`model_not_in_plan`, `quota_exceeded`). On billing service unavailability it fails open to avoid taking down agent execution.

A standalone LLM proxy was rejected at this stage.

## Rationale

**Governance pipeline over LLM layer:**
The pipeline already intercepts every LLM call regardless of which provider or service initiates it. Placing checks in `LLMClient` would require duplicating logic across providers and would tightly couple billing to infrastructure. The `PRE_LLM_CALL` phase is the canonical enforcement boundary — `CostBudgetGuard` and `TokenBudgetGuard` already live there.

**Governance pipeline over API layer:**
API-layer checks run once at task submission but cannot enforce mid-execution model switches or sub-agent delegations that spawn new LLM calls with different models.

**Extension registry over OSS stub:**
A no-op pass-through registered in OSS would be dead code with a misleading name. The cleaner contract is: if `ExtensionRegistry.has("entitlement_guard")` is false, the feature does not exist. OSS code has zero awareness of entitlements.

**Fails open on billing unavailability:**
Billing service downtime should not cause agent execution failures. The guard logs the error and allows the call. Quota overages in this window are acceptable — they can be reconciled post-hoc by the billing system.

**LLM proxy rejected (for now):**
A proxy (LiteLLM, custom) would be appropriate once multiple independent services make LLM calls. Currently only the Temporal worker does. A proxy would add a network hop, another service to operate, and would require the same workspace/plan context that lives in the application DB — forcing a callback to the app anyway. Revisit when a second LLM-calling service is introduced.

## Consequences

- `agentarea_governance.factory` imports `ExtensionRegistry` from `agentarea_common` — the only cross-lib dependency added to the governance library
- Billing service must implement `POST /entitlements/check` returning `{allowed, reason, code}`
- Enterprise deployment requires `BILLING_URL` (and optionally `BILLING_API_KEY`) in environment
- OSS pipeline registration count is unchanged (no extra interceptor slot)
- Future quota enforcement (rate limiting, burst caps) follows the same pattern: new gate in enterprise package, zero OSS changes
