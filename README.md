# AgentMesh

An open-core platform for building, testing, and running automation agents. AgentMesh provides a simple way to create and experiment with AI agents locally, while offering enterprise features for production deployments.

## 🚀 Quick Start

Run your first agent in minutes:

```bash
# Clone the repository
git clone https://github.com/your-org/agentmesh.git
cd agentmesh

# Set up your environment
cp .env.example .env
docker-compose up
```

## 🧪 Test Your First Agent

1. Create a simple agent spec in `examples/hello-world.yaml`:
```yaml
name: hello-world
description: A simple agent that responds to greetings
actions:
  - type: respond
    pattern: "hello|hi|hey"
    response: "Hello! I'm your first AgentMesh agent!"
```

2. Deploy and test your agent:
```bash
# Deploy the agent
agentmesh deploy examples/hello-world.yaml

# Test the agent
agentmesh test hello-world "hey there!"
```

## 🔧 Core Features

- **Local Development**: Run and test agents on your machine
- **Simple YAML Specs**: Define agents using easy-to-write YAML configurations
- **Built-in Testing**: Test agents with a simple CLI interface
- **Extensible**: Add custom actions and integrations
- **Open Source**: Full access to the core platform

## 🏗️ Project Structure

- `core/`: Core agent runtime and execution engine
- `protocols/`: Standard protocols for agent communication
- `examples/`: Sample agents to learn from and modify
- `app/`: Web interface for managing agents (optional)

## 📚 Documentation

- [Getting Started Guide](docs/getting-started.md)
- [Agent Specification](docs/agent-spec.md)
- [API Reference](docs/api.md)
- [Contributing Guide](.github/CONTRIBUTING.md)

## 🤝 Community

- Join our [Discord](https://discord.gg/agentmesh) for help and discussions
- Check out [awesome-agentmesh](https://github.com/agentmesh/awesome-agentmesh) for community-built agents
- Follow [@agentmesh](https://twitter.com/agentmesh) for updates

## 📄 License

AgentMesh is open source under the MIT License. See [LICENSE](LICENSE) for details.
