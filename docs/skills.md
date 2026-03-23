---
title: "Skills"
description: "Progressive skill disclosure, bundled script execution, and the activate_skill workflow"
---

# Skills

<Info>
Skills are reusable instruction packages that agents load on demand. An agent with 10 skills pays the token cost of only the ones it activates — not all 10 upfront.
</Info>

## Overview

Skills follow the [agentskills.io](https://agentskills.io) progressive disclosure pattern:

1. **Tier 1 — Catalog**: Agent sees a compact list of skill names + descriptions (~75 tokens per skill)
2. **Tier 2 — Activation**: Agent calls `activate_skill` to load full instructions when a task matches
3. **Tier 3 — Execution**: Agent calls `run_skill_script` to execute bundled scripts in a sandbox

```
System prompt:
  "Available Skills:
   - math-methodology: Step-by-step math problem solving
   - js-formatter: Format JavaScript code with Prettier"

Agent thinks: "This is a math task → activate math-methodology"
Agent calls: activate_skill("math-methodology")
Agent receives: Full skill instructions (loaded on demand)
Agent calls: run_skill_script("math-methodology", "calculator.py", "42 * 17")
Agent receives: "42 * 17 = 714"
```

---

## Token Savings

Without progressive disclosure, all skill content is injected into the system prompt at iteration 1:

| Approach | 3 skills × ~3000 tokens | If agent needs 1 |
|----------|------------------------|-------------------|
| **Eager (old)** | ~9000 tokens in prompt | ~9000 tokens (all loaded) |
| **Progressive (new)** | ~225 tokens catalog + ~3000 activated | ~3225 tokens (64% savings) |

---

## Creating Skills

### Content-only Skill (Markdown)

```bash
curl -X POST /v1/skills/ \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "name": "code-review",
    "description": "Review code for quality, security, and performance issues",
    "content": "---\nname: code-review\ndescription: Review code for quality\n---\n\n## Instructions\n1. Check for security vulnerabilities\n2. Review error handling\n3. Assess performance implications\n4. Suggest improvements"
  }'
```

### ZIP Package (with scripts)

```bash
curl -X POST /v1/skills/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@skill-package.zip" \
  -F "name=data-analyzer" \
  -F "description=Analyze datasets with Python"
```

ZIP structure:
```
skill-package.zip
├── SKILL.md           # Instructions (shown on activate_skill)
├── analyze.py         # Bundled script (run via run_skill_script)
├── helpers.py         # Supporting code
└── requirements.txt   # Dependencies (future: auto-installed)
```

---

## Attaching Skills to Agents

```bash
curl -X POST /v1/agents/ \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "name": "Data Agent",
    "instruction": "You are a data analysis agent.",
    "model_id": "model-instance-uuid",
    "skill_ids": ["skill-uuid-1", "skill-uuid-2"]
  }'
```

The agent's system prompt will contain a **catalog** of these skills, not their full content.

---

## Agent Tools

When an agent has skills, two built-in tools are automatically registered:

### `activate_skill`

Loads full skill instructions on demand. The skill name is constrained to an enum of attached skills — the LLM cannot hallucinate skill names.

```json
{
  "name": "activate_skill",
  "parameters": {
    "skill_name": {
      "type": "string",
      "enum": ["code-review", "data-analyzer"]
    }
  }
}
```

Response is wrapped in `<skill_content>` tags for compaction protection:

```xml
<skill_content name="code-review">
## Instructions
1. Check for security vulnerabilities
2. Review error handling
...

Skill files:
- analyze.py
- helpers.py
</skill_content>
```

### `run_skill_script`

Executes a script bundled with an activated skill in an isolated sandbox.

```json
{
  "name": "run_skill_script",
  "parameters": {
    "skill_name": "data-analyzer",
    "script_name": "analyze.py",
    "args": "--input /workspace/data.csv"
  }
}
```

The workflow validates:
1. The skill has been activated (prevents running scripts from non-activated skills)
2. The script exists in the skill's S3 package
3. Routes execution through the MCP Manager to a sandbox container

---

## Execution Architecture

```
Agent calls run_skill_script("data-analyzer", "analyze.py", args)
        │
        ▼
┌─────────────────────────────┐
│  Temporal Workflow            │
│  1. Validate skill activated │
│  2. Fetch script from S3     │
│  3. Call execute activity     │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│  MCP Manager                 │
│  POST /sandbox/execute       │
│  Routes to warm pool or      │
│  sandbox-executor container  │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│  Sandbox Executor            │
│  - Isolated container        │
│  - Python + Node runtimes    │
│  - Temp workspace per exec   │
│  - Returns stdout/stderr     │
└─────────────────────────────┘
```

**Separation of concerns:**
- **Temporal** knows "execute this script" — calls MCP Manager API
- **MCP Manager** knows "route to a sandbox" — finds a pod or container
- **Sandbox** knows "run this subprocess" — executes and returns output

Each layer only knows about the layer below it.

---

## Compaction Protection

Activated skill content is protected from context window compaction. When the context manager needs to free tokens, it skips messages containing skill content (detected by tool name `activate_skill` or `<skill_content>` tags).

This ensures skill instructions persist through the entire conversation, even in long-running tasks.

---

## Execution Engine

Skills work with both execution engines:

| Engine | Config | How skills execute |
|--------|--------|-------------------|
| **Temporal** (default) | `WORKFLOW__EXECUTION_ENGINE=temporal` | Via workflow activities → MCP Manager → sandbox |
| **Direct** (dev/CLI) | `WORKFLOW__EXECUTION_ENGINE=direct` | In-process agent loop, same skill activation |

Both use the same `activate_skill` tool and skill catalog. The execution path differs but the agent experience is identical.

---

## Security: Cross-Skill Isolation (Planned)

When an agent activates multiple skills, each skill's scripts run in a **separate sandbox**. Data passes between skills only through S3, controlled by the workflow:

```
Skill A sandbox ──outputs──→ S3 ──inputs──→ Skill B sandbox
                  (workflow controls what flows between them)
```

- Skill A never sees Skill B's secrets
- Scripts can't plant persistent processes across sandbox boundaries
- The workflow (Temporal) is the trust boundary, not the sandbox

See [Skill Sandboxing](/skill-sandboxing) for container isolation details.

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `WORKFLOW__EXECUTION_ENGINE` | `temporal` | `temporal` or `direct` |
| `SANDBOX_EXECUTOR_URL` | — | URL of sandbox executor (dev mode, set in MCP Manager) |

---

## Next Steps

<CardGroup cols={2}>
  <Card title="Skill Sandboxing" icon="shield-halved" href="/skill-sandboxing">
    Container isolation and security model
  </Card>
  <Card title="Warm Pool" icon="bolt" href="/warm-pool">
    Pre-warmed pods for fast script execution
  </Card>
  <Card title="Building Agents" icon="robot" href="/building-agents">
    Create agents with skills and tools
  </Card>
  <Card title="API Reference" icon="code" href="/api-reference">
    Skills API endpoints
  </Card>
</CardGroup>
