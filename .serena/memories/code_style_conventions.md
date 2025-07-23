# Code Style and Conventions

## Python Code Style

### Tools Used
- **Ruff**: Primary linter and formatter
- **Pyright**: Type checking
- **Pre-commit**: Git hooks for code quality

### Key Conventions

1. **Python Version**: Requires Python 3.12+
2. **Type Hints**: Extensive use of type hints throughout
3. **Async/Await**: All I/O operations are asynchronous
4. **Pydantic**: Used for data validation and serialization
5. **SQLAlchemy**: Modern async patterns with mapped_column

### Naming Conventions
- **Files**: Snake_case (e.g., `agent_service.py`)
- **Classes**: PascalCase (e.g., `AgentService`)
- **Functions/Variables**: Snake_case (e.g., `create_agent`)
- **Constants**: UPPER_SNAKE_CASE

### Architecture Patterns
- **Domain-Driven Design**: Clear separation of domain, application, infrastructure layers
- **Repository Pattern**: Abstract data access
- **Dependency Injection**: Constructor-based injection
- **Event-Driven**: Domain events for cross-service communication

## Package Structure

Each library follows this structure:
```
agentarea-{name}/
├── domain/
│   ├── models.py      # Domain entities
│   ├── interfaces.py  # Abstract interfaces  
│   └── events.py      # Domain events
├── application/
│   └── {name}_service.py  # Business logic services
└── infrastructure/
    ├── repository.py  # Data access implementation
    └── di_container.py # DI configuration
```

## Documentation Style
- **Docstrings**: Use for public APIs
- **Type Annotations**: Required for all function signatures
- **Comments**: Explain business logic, not implementation details