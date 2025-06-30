# AgentArea Documentation

Welcome to the AgentArea documentation hub. This directory contains comprehensive documentation for the AgentArea platform.

## 📚 Documentation Index

### **Getting Started**
- **[Project Overview](./project-overview.md)** - Vision, features, business model, and roadmap
- **[Implementation Status](./implementation-status.md)** - Current technical implementation status and achievements
- **[Current Tasks](./current-tasks.md)** - Development status, active tasks, and next steps
- **[Quick Reference Guide](./quick-reference.md)** - Commands, URLs, and troubleshooting

### **Architecture & Design**
- **[Architecture Insights](./architecture_insights.md)** - Comprehensive analysis of AgentArea's architecture, implementation patterns, and key learnings
- **[Architecture Decisions (ADR)](./architecture-decisions.md)** - Key architectural decisions and rationale
- **[MCP Architecture Overview](./mcp_architecture.md)** - System architecture and components
- **[Agent-to-Agent Communication](./agent_to_agent_communication.md)** - A2A protocol design and implementation

### **Implementation Guides**
- **[MCP Implementation Plan](./mcp-implementation-plan.md)** - Technical implementation roadmap for MCP server management
- **[Task Assignment](./task_assignment.md)** - Task distribution and management patterns
- **[Dependency Injection Patterns](./dependency_injection_patterns.md)** - DI patterns and best practices used throughout the application

### **Archive**
- **[Archive](./archive/)** - Historical documentation and deprecated patterns

---

## 🎯 **Quick Start for New Developers**

If you're new to the project, start here:

1. **[Project Overview](./project-overview.md)** - Understand what AgentArea is and its goals
2. **[Architecture Insights](./architecture_insights.md)** - Get familiar with the overall system design
3. **[Current Tasks](./current-tasks.md)** - See what's being worked on now
4. **[Dependency Injection Patterns](./dependency_injection_patterns.md)** - Learn the coding patterns used

---

## 💡 **Key Concepts**

- **Model Context Protocol (MCP)** - Universal standard for connecting AI agents to tools and data sources
- **Agent-to-Agent Communication** - Protocol for multi-agent collaboration and task distribution
- **Event-Driven Architecture** - Redis-based event bus for service communication
- **Unified Configuration** - `json_spec` pattern for flexible MCP provider configuration
- **Domain Events** - Business-focused events for clean service boundaries
- **Microservices** - AgentArea backend + MCP Infrastructure + supporting services

---

## 📖 **Related Documentation**

- **[Core Module Documentation](../core/docs/)** - Technical documentation for core components
- **[Frontend Documentation](../frontend/)** - UI components and integration guides
- **[MCP Infrastructure](../mcp-infrastructure/)** - Container management and deployment

---

*Documentation last updated: January 2025*
