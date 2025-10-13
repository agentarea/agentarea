<div align="center">

![AgentArea Logo](images/agentarea-cover.jpg)


**Build, deploy, and manage AI agents at scale**

[![License](https://img.shields.io/badge/license-EPLv2-blue.svg)](LICENSE.md)
[![CI](https://github.com/agentarea/agentarea/workflows/CI/badge.svg)](https://github.com/agentarea/agentarea/actions)
[![Documentation](https://img.shields.io/badge/docs-mintlify-green.svg)](https://docs.agentarea.dev)
[![Discord](https://img.shields.io/discord/YOUR_DISCORD_ID?color=5865F2&label=discord&logo=discord&logoColor=white)](https://discord.gg/93jVZ4Kx)
[![GitHub Stars](https://img.shields.io/github/stars/agentarea/agentarea?style=social)](https://github.com/agentarea/agentarea/stargazers)
[![GitHub Forks](https://img.shields.io/github/forks/agentarea/agentarea?style=social)](https://github.com/agentarea/agentarea/network/members)

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://python.org)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.0+-3178C6?logo=typescript&logoColor=white)](https://typescriptlang.org)
[![Go](https://img.shields.io/badge/Go-1.25+-00ADD8?logo=go&logoColor=white)](https://golang.org)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)](https://docker.com)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-ready-326CE5?logo=kubernetes&logoColor=white)](https://kubernetes.io)

[📖 Documentation](https://docs.agentarea.dev) •
[🚀 Quick Start](#-quick-start) •
[💬 Discord](https://discord.gg/93jVZ4Kx) •
[🐛 Report Bug](https://github.com/agentarea/agentarea/issues/new?template=bug_report.md) •
[✨ Request Feature](https://github.com/agentarea/agentarea/issues/new?template=feature_request.md)

</div>

---

## 🚀 What is AgentArea?

AgentArea is an open-source platform for building, deploying, and managing AI agents at scale. Whether you're creating simple chatbots or complex multi-agent systems, AgentArea provides the tools and infrastructure you need.

### ✨ Key Features

<table>
<tr>
<td width="50%">

#### 🤖 Multi-Agent Communication
Enable agents to collaborate and work together seamlessly. Build complex workflows with multiple specialized agents.

#### 🔌 MCP Integration
Built-in Model Context Protocol support for external tools and services. Extend your agents with custom capabilities.

#### 📈 Scalable Infrastructure
Docker and Kubernetes-ready deployment. Scale from prototype to production effortlessly.

</td>
<td width="50%">

#### 🛠️ Developer-Friendly
RESTful APIs and comprehensive SDKs. Start building in minutes with our quickstart guides.

#### 📊 Real-time Monitoring
Performance analytics and debugging tools. Track agent behavior and optimize performance.

#### 🔒 Enterprise-Ready
Security, compliance, and role-based access control. Production-ready from day one.

</td>
</tr>
</table>

### 🎬 See It In Action

> 📸 *Screenshots and demo GIFs coming soon! [Contribute yours](https://github.com/agentarea/agentarea/discussions)*

## 🏃‍♂️ Quick Start

### Prerequisites

- Docker (v20.10+) & Docker Compose (v2.0+)
- Python 3.11+
- Node.js 18+
- Go 1.25+ (for MCP infrastructure)

### Installation

```bash
# Clone the repository
git clone https://github.com/agentarea/agentarea.git
cd agentarea

# Start the development environment
make dev-up

# Verify installation
curl http://localhost:8000/health
```

### Create Your First Agent

```bash
# Create a simple chatbot agent
curl -X POST http://localhost:8000/v1/agents \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My First Agent",
    "template": "chatbot",
    "model": "gpt-4"
  }'
```

## 📚 Documentation

- **[Getting Started](docs/getting-started.md)** - Complete setup guide
- **[Building Agents](docs/building-agents.md)** - Create and customize AI agents
- **[Agent Communication](docs/agent-communication.md)** - Multi-agent workflows
- **[MCP Integration](docs/mcp-integration.md)** - External tool integration
- **[Deployment](docs/deployment.md)** - Production deployment guide
- **[API Reference](docs/api-reference.md)** - Complete API documentation

## 🛠️ Project Structure

```
agentarea/
├── core/                    # Backend API and services (Python)
│   ├── apps/               # Applications (API, Worker, CLI)
│   └── libs/               # Shared libraries
├── frontend/               # Web interface (React/Next.js)
├── mcp-infrastructure/     # MCP server management (Go)
├── agent-placement/        # Agent orchestration (Node.js)
├── docs/                   # Documentation (Mintlify)
└── scripts/               # Development and deployment scripts
```


## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guide](docs/contributing.md) for details on:

- Development setup
- Code style guidelines
- Pull request process
- Community guidelines

### Quick Contributing Steps

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 🏗️ Architecture

AgentArea follows a microservices architecture with:

- **FastAPI Backend**: RESTful API and business logic
- **React Frontend**: Modern web interface
- **PostgreSQL**: Primary database
- **Redis**: Message queue and caching
- **Go MCP Manager**: External tool integration
- **Docker**: Containerized deployment

For detailed architecture information, see [docs/architecture.md](docs/architecture.md).

## 🚀 Deployment

### Development

```bash
make dev-up      # Start development environment
make dev-down    # Stop development environment
make dev-logs    # View logs
```

### Production

```bash
# Docker Compose
docker-compose -f docker-compose.prod.yml up -d

# Kubernetes
kubectl apply -f k8s/
```

See [docs/deployment.md](docs/deployment.md) for comprehensive deployment guides.

## 📊 Monitoring

AgentArea includes built-in monitoring with:

- **Metrics**: Prometheus + Grafana dashboards
- **Logging**: Structured JSON logging
- **Tracing**: Distributed tracing with Jaeger
- **Health Checks**: Kubernetes-ready health endpoints

## 🛡️ Security

- **Authentication**: JWT-based API authentication
- **Authorization**: Role-based access control (RBAC)
- **Secrets Management**: Vault integration
- **Network Security**: TLS encryption, secure defaults
- **Compliance**: SOC 2 Type II, GDPR ready

## 📈 Roadmap

- [x] Basic agent creation and management
- [x] Multi-agent communication
- [x] MCP protocol integration
- [x] Docker deployment
- [ ] Kubernetes operator
- [ ] Visual agent workflow designer
- [ ] Enterprise SSO integration
- [ ] Advanced analytics dashboard

See our [full roadmap](docs/roadmap.md) for more details.

## 🌟 Community

Join our growing community of AI developers and contributors!

- **💬 Discord**: [Join our Discord server](https://discord.gg/93jVZ4Kx) - Get help, share ideas, and connect with the community
- **💭 GitHub Discussions**: [General discussions, Q&A, and feature requests](https://github.com/agentarea/agentarea/discussions)
- **🐛 Issues**: [Bug reports and feature requests](https://github.com/agentarea/agentarea/issues)
- **🤝 Contributing**: [Contribution guidelines](CONTRIBUTING.md)
- **🐦 Twitter/X**: Follow us for updates [@agentarea](https://twitter.com/agentarea)

### 🎯 Ways to Contribute

- **Code**: Submit pull requests for bug fixes and new features
- **Documentation**: Help improve our docs
- **Community**: Answer questions and help others
- **Feedback**: Share your experience and suggestions
- **Showcase**: Share projects built with AgentArea

### 🌟 Show Your Support

If you find AgentArea helpful, please consider:
- ⭐ Starring the repository
- 🐦 Sharing on social media
- 📝 Writing a blog post or tutorial
- 💬 Joining our Discord community

## 📄 License

This project is licensed under the Eclipse Public License v2.0 (EPLv2) - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

AgentArea is built on top of many excellent open-source projects. See our [NOTICE](NOTICE) file for complete attribution.

---

<div align="center">

### ⭐ Star History

[![Star History Chart](https://api.star-history.com/svg?repos=agentarea/agentarea&type=Date)](https://star-history.com/#agentarea/agentarea&Date)

### 🙌 Built With AgentArea

*Showcase your project here! [Submit via PR](https://github.com/agentarea/agentarea/pulls) or [Discussion](https://github.com/agentarea/agentarea/discussions)*

---

**[⭐ Star us on GitHub](https://github.com/agentarea/agentarea) • [📖 Read the Docs](https://docs.agentarea.dev) • [💬 Join Discord](https://discord.gg/93jVZ4Kx) • [🐦 Follow on Twitter](https://twitter.com/agentarea)**

Made with ❤️ by the AgentArea community

</div>
