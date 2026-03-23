# ADR-001: Agent Context Strategy

**Date:** 2026-03-19
**Status:** Accepted

## Context

Long-running agent workflows face a fundamental tension: LLM context windows are finite,
but agent sessions can generate large volumes of tool outputs, message history, and tool
definitions. Naively passing everything into every LLM call leads to:

- Token limit errors on long sessions
- Degraded model performance when the context is noisy
- Unnecessary cost from repeated large payloads

We need a mechanism to gate how aggressively the runtime manages context — and it must be
configurable per model, because weaker models can't reliably use advanced patterns like
progressive tool disclosure.

## Decision

We introduce a **ContextStrategy** enum with three tiers:

| Strategy  | Output offloading | History preservation | Tool progressive disclosure |
|-----------|------------------|---------------------|-----------------------------|
| `static`  | off              | off                 | off                         |
| `hybrid`  | on               | on                  | off                         |
| `dynamic` | on               | on                  | on                          |

### Resolution order

```
agent.context_strategy
  → model_spec.default_context_strategy
    → system default: "hybrid"
```

An agent can pin its own strategy. If it doesn't, the model spec carries a
`default_context_strategy` field set explicitly by an operator. If that is also unset,
the system falls back to `"hybrid"`.

### System default: `hybrid`

`hybrid` is the safest production default: it offloads large tool outputs to MinIO and
preserves full message history across continue-as-new compaction, without requiring the
model to understand the `activate_tool_source` tool call pattern.

`dynamic` (full progressive disclosure) is opt-in — it requires the model to reliably
call `activate_tool_source` when it needs a tool that isn't in the active set. Weak or
narrow-domain models tend to ignore this instruction. Operators should enable `dynamic`
only after validating the specific model handles it correctly.

`static` is for models that cannot tolerate any context management side effects
(e.g., local models where MinIO is unavailable, or models under strict determinism
requirements).

## What we explicitly decided NOT to do

**Auto-inference from model name.** An earlier draft of this feature included a
`_infer_context_strategy(model_name)` function that pattern-matched strings like
`"claude-3.5"`, `"llama"`, `"gpt-4o"` to assign strategies automatically at model spec
creation time.

This was rejected because:

1. **It's fragile.** Model naming conventions change across providers and versions.
   A new model name that doesn't match any pattern silently gets the wrong strategy.
2. **It obscures operator intent.** When something goes wrong it's not clear whether the
   strategy came from an explicit decision or from a pattern match on a string.
3. **It doesn't scale to private/self-hosted models.** Internal model names give no
   signal about capability.

The field `model_spec.default_context_strategy` is nullable. When null, the system uses
`"hybrid"`. Operators set it explicitly via the admin API when they want a different
strategy for a specific model.

## Consequences

- New model specs start with `default_context_strategy = null` → effective strategy is
  `"hybrid"`.
- Operators can upgrade a model spec to `"dynamic"` via `PATCH /model-specs/{id}` once
  they've validated the model handles progressive disclosure correctly.
- Agent-level overrides remain available for agents that need a different strategy
  regardless of the model used.
- No backfill needed for existing model specs: null resolves to `"hybrid"` which matches
  the pre-feature behavior.

## Key files

- `libs/execution/agentarea_execution/workflows/context_strategy.py` — StrEnum + guard functions
- `libs/execution/agentarea_execution/workflows/context_store.py` — MinIO storage
- `libs/agentarea-agents-sdk/agentarea_agents_sdk/tools/tool_catalog.py` — progressive disclosure catalog
- `libs/agentarea-agents-sdk/agentarea_agents_sdk/tools/tool_provider.py` — ToolProvider protocol
- `libs/llm/agentarea_llm/domain/models.py` — `ModelSpec.default_context_strategy` column
- `apps/api/agentarea_api/api/v1/model_specs.py` — CRUD API
- Migration: `aa1ec6b67387_add_default_context_strategy_to_model_specs.py`
