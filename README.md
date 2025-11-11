<div align="center">

![AgentArea Logo](images/agentarea-cover.jpg)

## The Enterprise Platform for Governed Agentic Networks

Build production-grade multi-agent systems with built-in governance, compliance controls, and network-level isolation.

[![License](https://img.shields.io/badge/license-EPLv2-blue.svg)](LICENSE.md)
[![CI](https://github.com/agentarea/agentarea/actions/workflows/ci.yml/badge.svg)](https://github.com/agentarea/agentarea/actions/workflows/ci.yml)
[![GitHub Stars](https://img.shields.io/github/stars/agentarea/agentarea?style=social)](https://github.com/agentarea/agentarea/stargazers)
[![Discord](https://img.shields.io/discord/1375237948982821005?color=5865F2&label=discord&logo=discord&logoColor=white)](https://discord.gg/5tduPwheYQ)
[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)]() [![TypeScript](https://img.shields.io/badge/TypeScript-5.0+-blue.svg)]() [![Go](https://img.shields.io/badge/Go-1.24+-blue.svg)]()

[📖 Docs](https://docs.agentarea.ai) •
[🚀 Quick Start](#-quick-start) •
[🔗 Architecture](#-architecture) •
[💬 Discord](https://discord.gg/5tduPwheYQ) •
[🐛 Report Bug](https://github.com/agentarea/agentarea/issues/new?template=bug_report.md) •
[✨ Request Feature](https://github.com/agentarea/agentarea/issues/new?template=feature_request.md)

---

## The Governance Gap

Traditional agent frameworks (LangChain, AutoGPT, CrewAI) were designed for single-agent prototypes. **When deploying to production**, you face a critical gap:

- ❌ No native approval workflows for sensitive operations
- ❌ No network-level isolation between agent groups
- ❌ No built-in RBAC or secret boundaries

**AgentArea is purpose-built to close this gap.** We combine agentic orchestration with enterprise governance—not as an add-on, but as core architecture.

---

## What Makes AgentArea Different

<table>
<tr>
<td width="50%">

### 🌐 Agentic Networks First
VPC-inspired architecture where agents communicate via A2A protocol with granular network permissions. Build isolated agent groups that control who talks to whom.

### 🛡️ Governance Built-In
Approve sensitive tool calls before execution. Enforce role-based access control. Governance is native—not a plugin.

### 🔗 A2A Protocol
Native agent-to-agent communication standard. Agents discover, connect, and collaborate securely. Enable agent teams and hierarchical structures natively.

### 📊 Compliance-Ready
Permission boundaries by design. Secret management with multiple backends (Vault, Infisical, AWS). Ready for healthcare, finance, regulated industries.

</td>
<td width="50%">

### ⚡ Production Infrastructure
Temporal-based durable execution. Kubernetes-native architecture. Edge deployment support. Multi-LLM via LiteLLM proxy. Built to scale.

### 🔌 MCP Server Management
Create, host, and manage MCP servers. Add remote MCPs with hash verification. Extend agent capabilities securely with external tools.

### 🤖 Flexible Agent Creation
Custom instructions and tool configurations. Long-running tasks with flexible termination. Human-in-the-loop workflows for critical decisions.

### 🏗️ Open Core, Enterprise Options
Core platform is 100% open source (EPLv2). Enterprise features for air-gapped deployment, advanced RBAC, SLA support available for organizations at scale.

</td>
</tr>
</table>

---

## 🎯 Built for Production

AgentArea is purpose-built for regulated industries and enterprise deployments:

### Healthcare & Life Sciences
"Deploy automated clinical workflows with physician approval workflows. Sensitive decisions require human sign-off before execution."

**Features used:** Approval workflows, Secret management

### Financial Services
"Multi-agent trading, loan processing, and fraud detection with compliance guardrails. Network isolation prevents information leakage between agent teams."

**Features used:** Agent networks, Tool permissions, RBAC

### Regulated Document Processing
"Legal, insurance, and government document automation with approval queues."

**Features used:** Approval workflows, A2A protocol for document routing

### Enterprise Data Operations
"Deploy agent networks for ETL, reporting, and analytics with permission boundaries by design. Prevent unauthorized data access across agent groups."

**Features used:** Agentic networks, Permission boundaries, MCP extensions

---

## 📊 Capability Comparison

How AgentArea compares to traditional agent frameworks:

| Capability | Traditional Frameworks | AgentArea |
|---|---|---|
| **Single Agent Support** | ✅ Full | ✅ Full |
| **Multi-Agent Networks** | ⚠️ Basic loops | ✅ Network-native (A2A) |
| **Approval Workflows** | ❌ Custom code | ✅ Built-in |
| **Tool Permissions** | ❌ Not enforced | ✅ Granular RBAC |
| **Network Isolation** | ❌ None | ✅ VPC-inspired |
| **Governance** | ❌ Not designed for | ✅ Core feature |
| **Production Execution** | ⚠️ Temporal plug-in | ✅ Native integration |

---

## 🚀 Quick Start

### Prerequisites

- **Docker & Docker Compose** (v2.0+)
- **8GB RAM** minimum, **16GB recommended**
- **10GB free disk space**

### Installation (2 minutes)

```bash
# Clone the repository
git clone https://github.com/agentarea/agentarea.git
cd agentarea

# Start the platform
make up

# Platform is ready at http://localhost:3000
```

### Verify Installation

```bash
# Check all services are running
docker compose ps

# Expected output:
# NAME                      STATUS
# agentarea-api            Up 2 minutes
# agentarea-worker         Up 2 minutes
# agentarea-webapp         Up 2 minutes
# agentarea-mcp-manager    Up 2 minutes
# postgresql               Up 2 minutes
# redis                    Up 2 minutes
# temporal                 Up 2 minutes
```

### First Agent (10 lines)

```python
from agentarea import Agent, Tool, Network

# Create a network with governance
network = Network(name="customer_support", approval_required=True)

# Define an agent with controlled tools
agent = Agent(
    name="support_agent",
    instructions="Help customers with their issues",
    tools=[Tool(name="refund", requires_approval=True)],
    network=network
)

# Run the agent
result = agent.run("Process refund for order #123")
# → Approval request created (human review required)
```

**What's Next?** [Building Your First Agent](docs/getting-started.md) • [Multi-Agent Networks](docs/agent-communication.md) • [Production Deployment](docs/deployment.md)

---

## 🏗️ Architecture

AgentArea combines agentic orchestration with enterprise governance:

```
┌─────────────────────────────────────────────────────────────┐
│                    Web Interface (Next.js)                  │
│                  http://localhost:3000                      │
└─────────────┬───────────────────────────────────────────────┘
              │
┌─────────────▼───────────────────────────────────────────────┐
│                   API Gateway (FastAPI)                     │
│              Authentication • Authorization                 │
└─────────────┬───────────────────────────────────────────────┘
              │
    ┌─────────┼─────────────┬──────────────┐
    │         │             │              │
┌───▼──┐  ┌──▼──────┐  ┌───▼────┐  ┌────▼──────┐
│ Task │  │ Secrets │  │Approval│  │  Audit    │
│Queue │  │ Manager │  │ Queue  │  │  Trail    │
└───┬──┘  └──┬──────┘  └───┬────┘  └────┬──────┘
    │        │             │            │
┌───▼────────▼─────────────▼────────────▼───┐
│         Agent Networks Layer               │
│  • VPC-inspired Isolation                 │
│  • A2A Protocol Communication             │
│  • Granular Permissions (ReBAC)           │
│  • Event-Driven Triggers                  │
└───────┬──────────────────────────┬────────┘
        │                          │
    ┌───▼──────┐            ┌─────▼──────┐
    │ Temporal  │            │    MCP     │
    │ Executor  │            │  Manager   │
    │(Workflows)│            │ (Go/Podman)│
    └───┬──────┘            └─────┬──────┘
        │                         │
    ┌───▼──────────────────────────▼──┐
    │  PostgreSQL • Redis • Temporal   │
    │      (Event sourcing layer)      │
    └────────────────────────────────┘
```

**Key Components:**
- **Agent Networks:** VPC-inspired isolation with granular permissions
- **A2A Protocol:** Native agent-to-agent communication
- **Temporal:** Distributed workflow orchestration for long-running agent tasks
- **Approval Queue:** Human-in-the-loop for sensitive operations
- **MCP Manager:** External tool management with security controls

For detailed architecture, see [docs/architecture.md](docs/architecture.md).

---

## 📚 Documentation

- **[Getting Started](docs/getting-started.md)** - Installation, first agent
- **[Building Agents](docs/building-agents.md)** - Agent creation and customization
- **[Agentic Networks](docs/agent-networks.md)** - Network architecture and isolation
- **[Agent Communication](docs/agent-communication.md)** - A2A protocol and multi-agent workflows
- **[Governance & Approvals](docs/governance.md)** - Approval workflows
- **[MCP Integration](docs/mcp-integration.md)** - External tool integration
- **[Deployment](docs/deployment.md)** - Docker, Kubernetes, production
- **[API Reference](docs/api-reference.md)** - Complete API documentation
- **[Architecture](docs/architecture.md)** - Deep dive on system design

---

## 🛠️ Project Structure

```
agentarea/
├── agentarea-platform/          # Backend (Python monorepo)
│   ├── apps/
│   │   ├── api/                 # FastAPI REST API
│   │   ├── worker/              # Temporal workflow execution
│   │   └── cli/                 # Python CLI
│   └── libs/                    # Shared libraries (agents, mcp, execution, etc.)
│
├── agentarea-webapp/            # Web UI (Next.js + React)
│   └── src/
│       ├── app/                 # App router pages
│       ├── components/          # React components
│       └── services/            # API clients
│
├── agentarea-mcp-manager/       # MCP server orchestration (Go)
│   └── cmd/                     # Main service
│
├── agentarea-cli/               # Terminal CLI (Node.js/TypeScript)
│   └── src/
│
├── agentarea-bootstrap/         # Initialization service
│   └── code/                    # Database setup, seeding
│
├── docs/                        # Documentation (Mintlify)
├── scripts/                     # Development & deployment scripts
└── docker-compose.yaml          # Full stack orchestration
```

---

## 🌟 Enterprise & Scale

### Evaluating for Production?

AgentArea is production-ready with Temporal, Kubernetes, and enterprise features:

- ✅ **Self-hosted** - Deploy to your infrastructure with Docker or Kubernetes
- ✅ **Air-gapped** - Run fully offline with no cloud connectivity required
- ✅ **Compliance** - HIPAA-ready architecture with secret management
- ✅ **Scale** - Built on Temporal for long-running, resilient agent tasks

**[Schedule a technical walkthrough →](https://calendly.com/agentarea/enterprise)**

### Open Core Model

**Open Source (EPLv2):**
- Full platform and all core features
- Agentic networks with A2A protocol
- Governance and approval workflows
- Community support via Discord

**Enterprise Add-ons** (optional, for organizations at scale):
- Advanced RBAC with custom policies
- SSO/SAML integration
- Priority support & SLAs
- Air-gapped deployment assistance
- Custom security reviews

[Learn more about Enterprise →](https://docs.agentarea.ai/enterprise)

---

## 📈 Roadmap

- [x] Core agent framework with governance
- [x] Multi-agent communication (A2A protocol)
- [x] Approval workflows
- [x] MCP protocol integration
- [x] Docker and Kubernetes support
- [ ] Visual workflow designer
- [ ] Advanced RBAC (relationship-based)
- [ ] Enterprise SAML/SSO
- [ ] Analytics dashboard
- [ ] Edge agent deployment

[View full roadmap →](docs/roadmap.md)

---

## 💬 Community & Support

Join engineers building governed agent systems:

- **[Discord Community](https://discord.gg/5tduPwheYQ)** - Get help, share ideas, discuss approaches
- **[GitHub Discussions](https://github.com/agentarea/agentarea/discussions)** - Q&A, feature requests, use cases
- **[GitHub Issues](https://github.com/agentarea/agentarea/issues)** - Bug reports and feature requests
- **[Documentation](https://docs.agentarea.ai)** - Guides, API docs, examples

**For Enterprise Teams:**
- **[Schedule Technical Walkthrough](https://calendly.com/agentarea/enterprise)** - Architecture review, compliance discussion
- **[Security Review](mailto:security@agentarea.ai)** - SOC 2, penetration testing, compliance questions

---

## ❓ FAQ for Enterprise Teams

**Q: Can AgentArea run in air-gapped (offline) environments?**
A: Yes. AgentArea is fully self-hosted. Deploy to your VPC with no cloud connectivity required.

**Q: What compliance standards does AgentArea support?**
A: Built-in features for HIPAA, SOC 2, and general compliance: secret management, RBAC, encryption at rest/transit.

**Q: How does governance compare to building approval systems ourselves?**
A: Governance is core architecture—not a plugin. Approval workflows and permissions are native, integrated with agent execution from day one.

**Q: Can we integrate AgentArea with our existing LLM infrastructure?**
A: Yes. Multi-LLM support via LiteLLM proxy. Works with OpenAI, Claude, Llama, and other providers.

**Q: What's the difference between open source and enterprise editions?**
A: Core platform is fully open (EPLv2). Enterprise features add advanced RBAC, SSO, and priority support for large organizations.

**Q: How does it handle long-running agent tasks?**
A: Native Temporal integration. Agents can run for hours/days with automatic retry, durable state, and resilience built-in.

---

## 📄 License

Licensed under the Eclipse Public License v2.0 (EPLv2). Commercial licensing available. See [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

AgentArea is built on excellent open-source projects. See [NOTICE](NOTICE) file for complete attribution.

---

<div align="center">

### ⭐ Star History

[![Star History Chart](https://api.star-history.com/svg?repos=agentarea/agentarea&type=Date)](https://star-history.com/#agentarea/agentarea&Date)

---

**Building governed agent systems?** [Try AgentArea →](https://docs.agentarea.ai/getting-started) • [Star us on GitHub →](https://github.com/agentarea/agentarea) • [Join Discord →](https://discord.gg/5tduPwheYQ)

Made with ❤️ by the AgentArea community

</div>
