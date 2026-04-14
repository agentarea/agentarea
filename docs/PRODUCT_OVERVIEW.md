# AgentArea — Product Overview

> Полное описание продукта для использования в документации, маркетинге и коммуникации

---

## 🎯 Product Vision

**AgentArea** — open-core платформа для построения **governed agentic networks** с VPC-inspired архитектурой. 

### Mission

Enable **Zero Human Organization** — мир, где AI-агенты автономно выполняют сложные задачи, требующие минимального участия человека. Агенты работают в сетях с governance controls, оплачивают свои действия и взаимодействуют через стандартизированные протоколы.

### Core Philosophy

1. **Networks First** — агенты не изолированы, они работают в сетях
2. **Governance Built-In** — контроль, approval, audit из коробки
3. **Protocol-Native** — все взаимодействия через открытые стандарты
4. **Zero Human** — автоматизация там, где возможно, human-in-the-loop там, где нужно

---

## 🌟 What Makes AgentArea Different

### vs Single-Agent Frameworks

| Single-Agent Frameworks | AgentArea |
|------------------------|-----------|
| Один изолированный агент | Сети взаимодействующих агентов |
| Нет governance | Tool permissions, approvals, audit |
| Custom protocols | Open standards (MCP, A2A, x402) |
| No payment model | Built-in wallet & payments |

### vs Other Agent Platforms

| Other Platforms | AgentArea |
|-----------------|-----------|
| Proprietary protocols | Open standards |
| SaaS-only | Self-hosted + cloud |
| No network isolation | VPC-inspired architecture |
| Limited governance | Full governance suite |

---

## 🏗️ Architecture Overview

### Multi-Protocol Platform

AgentArea построен на открытых протоколах, обеспечивающих интероперабельность:

```
┌─────────────────────────────────────────────────────────────────┐
│                        PROTOCOLS LAYER                          │
├─────────────┬─────────────┬─────────────┬─────────────┬────────┤
│    MCP      │    A2A      │    A2UI     │    x402     │  MPP   │
│  (Tools)    │ (Agent-2-   │ (Agent-2-   │ (Payments)  │ (Multi │
│             │   Agent)    │    User)    │             │ Party) │
└─────────────┴─────────────┴─────────────┴─────────────┴────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      AGENTIC NETWORK                            │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐                  │
│  │ Agent A  │◄──►│ Agent B  │◄──►│ Agent C  │                  │
│  │ (Chat)   │    │ (Task)   │    │ (Deleg.) │                  │
│  └──────────┘    └──────────┘    └──────────┘                  │
│       │               │               │                         │
│       └───────────────┴───────────────┘                         │
│                       │                                          │
│              Network Policies                                    │
│              Governance Controls                                 │
│              Budget Management                                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    INFRASTRUCTURE                               │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐            │
│  │ Temporal│  │  MCP    │  │ Sandbox │  │  Warm   │            │
│  │Workflow │  │ Manager │  │Executor │  │  Pool   │            │
│  └─────────┘  └─────────┘  └─────────┘  └─────────┘            │
└─────────────────────────────────────────────────────────────────┘
```

### Technology Stack

| Layer | Technology |
|-------|------------|
| **Frontend** | Next.js 14+, React, Tailwind CSS |
| **Backend API** | FastAPI (Python 3.11+), async/await |
| **Workflow Engine** | Temporal.io |
| **MCP Orchestration** | Go microservice |
| **Database** | PostgreSQL 15+ |
| **Cache/Events** | Redis 7+ |
| **Object Storage** | MinIO (S3-compatible) |
| **Auth** | Ory Kratos + Hydra |
| **Authorization** | Ory Keto (ReBAC) |
| **Deployment** | Docker, Kubernetes, Helm |

---

## 🔗 Protocols Deep-Dive

### MCP — Model Context Protocol

**Назначение:** Стандарт для подключения инструментов и контекста к AI-агентам.

**Возможности:**
- Агенты получают доступ к external tools (APIs, databases, file systems)
- Platform as MCP Server — внешние системы подключаются к AgentArea как к MCP серверу
- Managed MCP servers — платформа хостит и управляет MCP контейнерами
- Remote MCP servers — подключение к внешним MCP endpoints
- Compound MCPs — объединение нескольких MCP в один interface
- Warm Pool — pre-warmed контейнеры для ~1.3s cold start

**Use Cases:**
- Подключение web search, file operations, database access
- Интеграция с SaaS сервисами (Slack, GitHub, Jira)
- Кастомные инструменты для специфичных задач

**Пример:**
```yaml
agent:
  mcp_tools:
    - name: web_search
      type: managed
      template: brave-search
    - name: company_api
      type: remote
      endpoint: https://api.company.com/mcp
```

---

### A2A — Agent-to-Agent Protocol

**Назначение:** Стандартизированная коммуникация между агентами.

**Возможности:**
- Direct messaging между агентами
- Task delegation — передача задач от одного агента другому
- Broadcast messages — широковещательные сообщения
- Agent Discovery через well-known endpoints (/agent.json)
- Agent Cards с описанием capabilities
- JWT authentication для secure communication

**Network Topologies:**
- **Hierarchical** — Manager → Workers (task distribution)
- **Peer-to-Peer** — Collaborative agents with shared context
- **Pipeline** — Sequential processing chain
- **Mesh** — Full interconnection для complex workflows

**Use Cases:**
- Manager agent координирует specialist agents
- Research agent передаёт данные Writer agent
- Multi-step workflows с разными агентами на каждом этапе

**Пример:**
```json
// Agent Card
{
  "name": "Data Analyst",
  "description": "Analyzes datasets and generates reports",
  "capabilities": {
    "streaming": true,
    "push_notifications": true
  },
  "skills": ["analyze", "visualize", "report"]
}
```

---

### A2UI — Agent-to-User Interface

**Назначение:** Динамические UI компоненты, генерируемые агентами для пользователя.

**Возможности:**
- Интерактивные forms, tables, charts
- Real-time updates через SSE
- Custom components per agent
- User input collection
- Progress indicators
- Approval interfaces

**Use Cases:**
- Agent запрашивает данные через форму
- Agent показывает результаты в таблице/графике
- Approval workflow с кнопками Approve/Deny
- Multi-step wizard для сложных задач

**Пример:**
```typescript
// Agent генерирует A2UI компонент
{
  type: "form",
  fields: [
    { name: "report_type", type: "select", options: ["daily", "weekly"] },
    { name: "recipients", type: "multiselect", source: "/api/users" }
  ],
  actions: [
    { label: "Generate Report", type: "submit" }
  ]
}
```

---

### x402 — Payment Protocol

**Назначение:** Стандарт для оплаты выполнения задач агентами.

**Возможности:**
- HTTP 402 Payment Required implementation
- Wallet-based payments для каждого агента
- Cost tracking per task
- Payment requests и settlements
- Integration с external payment systems

**Use Cases:**
- Agent оплачивает API calls (OpenAI, Anthropic)
- Agent платит за premium tools
- Cost attribution per task/project
- Budget enforcement

**Пример:**
```yaml
agent:
  wallet:
    balance: 100.00  # USD
    auto_recharge: true
    low_balance_threshold: 10.00
  
  payment_policy:
    max_per_task: 5.00
    require_approval_above: 1.00
```

---

### MPP — Machine Payments Protocol

**Назначение:** Автоматические платежи от машин (агентов) без участия человека.

**Возможности:**
- Machine-to-machine payments
- Автономные транзакции
- Payment authorization policies
- Integration с payment providers
- Cryptocurrency support (planned)

**Use Cases:**
- Agent оплачивает API calls автоматически
- Agent-to-agent payments за services
- Autonomous budget spending
- Subscription payments за tools

**Пример:**
```yaml
agent:
  payment_policy:
    auto_approve_below: 1.00  # USD
    require_approval_above: 1.00
    max_daily_spend: 50.00
    allowed_payment_types:
      - api_calls
      - tool_subscriptions
      - agent_services
```

---

## 🛡️ Governance Framework

### Why Governance Matters

AI-агенты могут выполнять действия с реальными последствиями. Governance обеспечивает:
- **Compliance** — SOC 2, GDPR, HIPAA
- **Security** — предотвращение unauthorized actions
- **Cost Control** — предотвращение runaway execution
- **Audit** — полная история всех действий

### Tool Permissions

```yaml
agent:
  tools:
    # Auto-approved
    - name: web_search
      enabled: true
      requires_approval: false
    
    # Requires human approval
    - name: send_email
      enabled: true
      requires_approval: true
      approval_timeout: 300  # seconds
    
    # Disabled
    - name: database_write
      enabled: false
```

### Approval Workflow

```
Agent → Request Tool → Check Permissions → 
  If requires_approval:
    → Notify Human → Wait for Decision → Execute/Deny
  Else:
    → Execute immediately
```

### Tool Delegation & Permissions

**Концепция:** Возможность делегировать конкретные инструменты определённым агентам или пользователям.

**Возможности:**
- Выбор ответственного за конкретный tool
- Per-tool delegation policies
- Delegation chains (Manager → Worker → Tool)
- Responsibility tracking — кто отвечал за action
- Escalation paths — куда эскалировать если нужно
- Override policies для admins

**Use Cases:**
- Email tool делегирован Communications Agent
- Database write требует DBA approval
- Payment tool делегирован Finance Agent
- Critical operations эскалируются manager

**Пример:**
```yaml
agent:
  tool_delegation:
    - tool: send_email
      delegated_to: communications-agent
      fallback: human-approval
      
    - tool: database_write
      delegated_to: dba-team
      escalation: cto
      
    - tool: payment
      delegated_to: finance-agent
      max_amount: 100.00
      above_max: cfo-approval
```

**Delegation Flow:**
```
Agent A → Request Tool X → 
  Check Delegation Policy →
    If delegated:
      → Route to Delegated Agent/User
      → Track Responsibility
    Else:
      → Execute with default permissions
```

### Budget Controls

| Control | Description |
|---------|-------------|
| Max tokens | Лимит токенов per agent/task |
| Max cost USD | Максимальная стоимость выполнения |
| Max iterations | Лимит циклов agent loop |
| Timeout | Максимальное время выполнения |

### Audit Trails

- **Event Sourcing** — все действия как events
- **Persistent Storage** — PostgreSQL для history
- **Real-time Streaming** — Redis для live updates
- **Compliance Ready** — SOC 2, GDPR, HIPAA

---

## 🌐 Agentic Networks

### VPC-Inspired Architecture

```
┌─────────────────────────────────────────────────┐
│                   WORKSPACE A                    │
│  ┌─────────────────────────────────────────┐   │
│  │          NETWORK: Production            │   │
│  │  ┌────────┐  ┌────────┐  ┌────────┐    │   │
│  │  │Manager │──│Worker 1│──│Worker 2│    │   │
│  │  └────────┘  └────────┘  └────────┘    │   │
│  │       │                              │   │
│  │       └──────────────────────────────┘   │
│  │              Network Policies            │   │
│  └─────────────────────────────────────────┘   │
│                                                  │
│  ┌─────────────────────────────────────────┐   │
│  │          NETWORK: Development           │   │
│  │  ┌────────┐  ┌────────┐                │   │
│  │  │ Dev    │──│ Test   │                │   │
│  │  └────────┘  └────────┘                │   │
│  └─────────────────────────────────────────┘   │
└─────────────────────────────────────────────────┘
                        │
                        │ Isolated
                        ▼
┌─────────────────────────────────────────────────┐
│                   WORKSPACE B                    │
│  ...                                             │
└─────────────────────────────────────────────────┘
```

### Network Policies

```yaml
network_policy:
  rules:
    # Allow manager to communicate with workers
    - from: manager-agent
      to: worker-*
      action: allow
    
    # Deny cross-network communication
    - from: production-*
      to: development-*
      action: deny
    
    # Allow external API access
    - from: "*"
      to: external:api
      action: allow
      rate_limit: 100/minute
```

---

## 📦 Skills System

### Progressive Disclosure

Традиционный подход загружает все навыки в system prompt сразу. AgentArea использует progressive disclosure:

| Tier | What | Tokens |
|------|------|--------|
| **Catalog** | Skill names + descriptions | ~75 per skill |
| **Activation** | Full instructions on demand | ~3000 per skill |
| **Execution** | Run scripts in sandbox | Variable |

**Savings:** 10 skills = ~9000 tokens (eager) vs ~3225 tokens (progressive) = **64% savings**

### Skill Package Structure

```
skill-package.zip
├── SKILL.md           # Instructions (shown on activate)
├── analyze.py         # Bundled script
├── helpers.py         # Supporting code
└── requirements.txt   # Dependencies
```

### Skill Versioning

```yaml
agent:
  skills:
    - name: data-analyzer
      version: "2.1.0"  # Pin to specific version
      auto_update: false
```

---

## 📊 Observability

### Real-time Monitoring

- **SSE Streaming** — live task events
- **Task Progress** — iteration-by-iteration tracking
- **Agent Health** — status checks

### Metrics

| Metric | Description |
|--------|-------------|
| Response time | Latency per LLM call |
| Success rate | % of successful tasks |
| Token usage | Tokens consumed per task |
| Cost per task | USD spent |

### Logging

- Structured JSON logs
- Error tracking with stack traces
- Performance profiling
- Distributed tracing (OpenTelemetry)

---

## 🚀 Deployment

### Development

```bash
# Docker Compose
git clone https://github.com/agentarea/agentarea
cd agentarea
make up-dev

# Access at http://localhost:3000
```

### Production (Kubernetes)

```bash
# Helm chart
helm repo add agentarea https://charts.agentarea.ai
helm install agentarea agentarea/agentarea \
  --set postgresql.enabled=true \
  --set redis.enabled=true \
  --set temporal.enabled=true
```

### Infrastructure Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| PostgreSQL | 15+ | Managed (RDS, Cloud SQL) |
| Redis | 7+ | Managed (ElastiCache) |
| Temporal | Latest | Cloud or self-hosted |
| Compute | 4 CPU, 8GB | 8+ CPU, 16+ GB |

---

## 🎯 Target Audiences

### 1. Platform Developers
**Goal:** Build AI agents on AgentArea

**What they need:**
- API documentation
- SDK guides
- Protocol specifications
- Best practices

**Key features:**
- Agent creation APIs
- MCP integration
- A2A communication
- Skills development

---

### 2. Agent Builders
**Goal:** Configure and deploy agents

**What they need:**
- How-to guides
- Configuration examples
- Troubleshooting

**Key features:**
- Agent configuration
- Tool setup
- Trigger configuration
- Governance settings

---

### 3. End Users
**Goal:** Use agents to accomplish tasks

**What they need:**
- UI guides
- Quick start
- Common workflows

**Key features:**
- Workplace interface
- Chat with agents
- Task history
- Projects

---

### 4. Workspace Admins
**Goal:** Manage workspace and users

**What they need:**
- Admin guides
- Configuration
- Security

**Key features:**
- User management
- Provider configuration
- API keys
- Billing
- Audit logs

---

### 5. DevOps Engineers
**Goal:** Deploy and maintain platform

**What they need:**
- Deployment guides
- Infrastructure
- Monitoring

**Key features:**
- Helm charts
- Kubernetes configs
- Observability
- Scaling strategies

---

## 📈 Use Cases

### 1. Customer Support Automation

```
User Query → Support Agent → 
  ├─ Knowledge Base (MCP)
  ├─ CRM Lookup (MCP)
  ├─ Escalate to Human (Approval)
  └─ Send Response (A2UI)
```

### 2. Data Pipeline Automation

```
Trigger (Schedule) → Data Collector Agent →
  ├─ Fetch Data (MCP: API)
  ├─ Process (Skill: Python)
  ├─ Quality Check (Agent: Validator)
  └─ Report (A2UI: Dashboard)
```

### 3. Multi-Agent Research

```
Research Manager Agent →
  ├─ Web Search Agent (MCP)
  ├─ Data Analysis Agent (Skill)
  ├─ Report Writer Agent (A2A delegation)
  └─ Review Agent (Approval workflow)
```

### 4. Autonomous Operations

```
Event Trigger → Operations Agent →
  ├─ Check Status (MCP: Monitoring)
  ├─ Diagnose Issue (LLM)
  ├─ Fix Problem (MCP: Tools)
  ├─ Payment (x402/MPP)
  └─ Notify (A2UI)
```

---

## 🏆 Competitive Advantages

| Feature | AgentArea | Competitors |
|---------|-----------|-------------|
| **Network Architecture** | VPC-inspired, isolated | Single agent focus |
| **Governance** | Built-in, enterprise-ready | Limited or none |
| **Protocols** | Open standards (MCP, A2A, x402) | Proprietary |
| **Payments** | Native wallet, multi-party | Not supported |
| **Deployment** | Self-hosted + cloud | Cloud-only |
| **License** | Apache 2.0 open source | Proprietary |
| **Skills** | Progressive disclosure, versioned | All-or-nothing |

---

## 📚 Documentation Structure (Planned)

```
docs/
├── getting-started/          # Quick start для всех
├── user-guide/               # End users
├── agent-guide/              # Agent builders
│   └── protocols/            # MCP, A2A, A2UI, x402, MPP
├── admin-guide/              # Workspace admins
├── reference/                # API, configuration
│   └── protocols-spec/       # Protocol specifications
└── operations/               # DevOps
```

---

## 🔮 Roadmap Highlights

### Near-term
- Full A2UI component library
- x402 payment integration
- MPP multi-party settlements
- Enhanced governance dashboard

### Medium-term
- Advanced network topologies
- Agent marketplace
- Community skills registry
- Enterprise SSO integration

### Long-term
- Federated networks
- Cross-workspace A2A
- AI-powered governance
- Zero-knowledge proofs for audit

---

*This document serves as the foundation for all AgentArea documentation and communication.*
