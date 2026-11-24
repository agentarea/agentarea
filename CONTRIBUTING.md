# Contributing to AgentArea

## 🎯 Welcome Contributors

Thank you for your interest in contributing to AgentArea! This guide will help you understand our development process, coding standards, and how to submit contributions effectively.

## 🚀 Quick Start for Contributors

### 1. Development Setup
```bash
# Fork and clone the repository
git clone https://github.com/agentarea/agentarea.git
cd agentarea

# Set up development environment
make up-dev   # creates .env from .env.example with local secrets, builds, starts

# Verify setup
curl http://localhost:8000/health
```

### 2. Create Feature Branch
```bash
# Create and switch to feature branch
git checkout -b feature/your-feature-name

# Or for bug fixes
git checkout -b fix/issue-description
```

### 3. Make Changes
- Follow our [coding standards](#coding-standards)
- Write tests for new functionality
- Update documentation as needed

### 4. Submit Pull Request
- Push your branch to your fork
- Create a pull request with clear description
- Ensure all checks pass

## 📋 Development Workflow

### Branch Naming Convention
```
feature/feature-name        # New features
fix/bug-description         # Bug fixes
refactor/component-name     # Code refactoring
docs/documentation-update   # Documentation changes
chore/maintenance-task      # Maintenance tasks
```

### Commit Message Format
```
type(scope): brief description

[optional body]

[optional footer]
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, etc.)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

**Examples:**
```
feat(agents): add streaming chat support

Implement server-sent events for real-time chat responses.
Includes WebSocket fallback for older browsers.

Closes #123
```

```
fix(mcp): resolve server startup race condition

Ensure MCP servers wait for database connection before starting.
```

### Pull Request Process

1. **Pre-submission Checklist:**
   - [ ] Code follows style guidelines
   - [ ] Tests pass locally
   - [ ] Documentation updated
   - [ ] No merge conflicts
   - [ ] Descriptive commit messages

2. **PR Description Template:**
   ```markdown
   ## Description
   Brief description of changes
   
   ## Type of Change
   - [ ] Bug fix
   - [ ] New feature
   - [ ] Breaking change
   - [ ] Documentation update
   
   ## Testing
   - [ ] Unit tests pass
   - [ ] Integration tests pass
   - [ ] Manual testing completed
   
   ## Related Issues
   Closes #issue-number
   ```

3. **Review Process:**
   - At least one code review required
   - All CI checks must pass
   - Documentation review for user-facing changes
   - Security review for auth/permission changes

## 🔧 Coding Standards

### Go Code Style

The backend is one Go module, `agentarea-platform/`. `gofmt` formats it;
`golangci-lint` (version pinned in `agentarea-platform/Makefile`) lints it and
enforces the layering that `tools/archgen` generates into `.golangci.yml`.

```bash
make -C agentarea-platform check   # exactly what CI's go-check runs
make -C agentarea-platform archgen # after adding a module to tools/archgen
```

- A module imports the kernel, itself and other modules' `api` only.
- SQL lives in a module's `store/` (sqlc) and `internal/kernel/db`.
- Errors are returned, or logged with their cause; never dropped.
- Required config fails the process at startup and names the variable.

### Database Patterns

**Migrations** are goose files in `agentarea-platform/internal/schema/migrations/`,
applied by `agentarea migrate`. Add the next number (`NNNNN_<slug>.sql`); never
edit a file that has shipped. Schema-backed tests run against a disposable
Postgres:

```bash
make db-test-up      # prints the AGENTAREA_DB_TEST_URL to export
make check-db
make db-test-down
```

### Frontend Code Style (Future)

**TypeScript/React:**
- Use TypeScript for all new code
- Follow React functional component patterns
- Use React hooks for state management
- Implement proper error boundaries

## 🧪 Testing Guidelines

### Test Structure
```
agentarea-platform/
├── **/*_test.go        # unit and schema-backed tests, next to the code
├── test/suite/         # behaviour suite against a running stack (go test -tags suite)
└── test/fuzz/          # schemathesis fuzz of a running stack (Python)
```

### Writing Tests
- A test must fail on the regression it claims to guard.
- Tests that need Postgres skip without `AGENTAREA_DB_TEST_URL`; `make check-db` runs them.
- The behaviour suite runs on `deploy/suite/stack.sh up`; see `agentarea-platform/test/suite/README.md`.

### Running Checks
Every stack has one entrypoint, and CI calls the same one.
```bash
make check        # all non-DB checks, every stack
make check-db     # migrations + schema-backed suites (make db-test-up first, export what it prints)

# One stack
make -C agentarea-platform check
pnpm -C agentarea-webapp run check

# A single package or test
cd agentarea-platform && go test ./internal/modules/agents/... -run TestName

# Fuzz a running stack (defaults to localhost:8000 and Kratos on :4433/:4434)
make -C agentarea-platform test-api-fuzz
```

## 📚 Documentation Standards

### Code Documentation
- Doc comments on exported identifiers state the contract, not the mechanics
- Document complex algorithms and business logic
- Keep comments up-to-date with code changes

### API Documentation
- The spec is `agentarea-webapp/src/api/openapi.json`; the binary serves its copy at `/openapi.json`
- Provide clear endpoint descriptions
- Include request/response examples
- Document error conditions

### User Documentation
- Write clear, concise instructions
- Include code examples
- Provide troubleshooting steps
- Keep documentation current with features

## 🔒 Security Guidelines

### Authentication & Authorization
- Never commit secrets or API keys
- Use environment variables for configuration
- Implement proper input validation
- Follow principle of least privilege

### Data Protection
- Sanitize user inputs
- Use parameterized queries
- Implement rate limiting
- Log security events

### Code Security
```go
// Good: parameterized query
rows, err := s.Q().Query(ctx, "SELECT id FROM agents WHERE created_by = $1", userID)

// Bad: string interpolation (SQL injection risk)
rows, err := s.Q().Query(ctx, "SELECT id FROM agents WHERE created_by = '"+userID+"'")
```

## 🚀 Performance Guidelines

### Database Optimization
- Use appropriate indexes
- Implement query pagination
- Avoid N+1 query problems
- Use database connection pooling

### API Performance
- Implement caching where appropriate
- Use async/await for I/O operations
- Optimize serialization
- Monitor response times

### Resource Management
- Clean up resources properly
- Use context managers
- Implement proper error handling
- Monitor memory usage

## 🔄 Release Process

### Version Numbering
- Follow Semantic Versioning (SemVer)
- Format: `MAJOR.MINOR.PATCH`
- Tag releases in Git

### Release Checklist
- [ ] All tests pass
- [ ] Documentation updated
- [ ] Migration scripts tested
- [ ] Security review completed
- [ ] Performance impact assessed
- [ ] Rollback plan prepared

## 🆘 Getting Help

### Resources
- **[Getting Started](GETTING_STARTED.md)** - Setup guide
- **[API Reference](API_REFERENCE.md)** - API documentation
- **[Troubleshooting](TROUBLESHOOTING.md)** - Common issues
- **[Architecture Docs](../core/docs/SYSTEM_ARCHITECTURE.md)** - Technical details

### Support Channels
- **Code Reviews**: Submit pull requests
- **Questions**: Create GitHub issues
- **Discussions**: Team chat/meetings
- **Documentation**: Update relevant docs

## 📋 Contributor Recognition

We appreciate all contributions to AgentArea! Contributors will be:
- Listed in project documentation
- Recognized in release notes
- Invited to contributor discussions
- Eligible for maintainer roles

---

*Contributing guidelines last updated: January 2025*
*Thank you for helping make AgentArea better! 🚀*