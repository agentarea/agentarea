# Task Completion Checklist

When completing any development task in AgentArea, ensure you run these commands:

## Code Quality
1. **Format Code**: `make format` or `uv run ruff format`
2. **Lint Check**: `make lint` or `uv run ruff check && uv run pyright`
3. **Fix Linting Issues**: `uv run ruff check --fix`

## Testing
4. **Run Tests**: `make test` or `uv run pytest`
5. **Run Integration Tests**: `pytest -m integration` (if infrastructure changes)
6. **Test Coverage**: Check `htmlcov/` directory after test run

## Dependencies
7. **Sync Dependencies**: `make sync` or `uv sync --all-packages` (if pyproject.toml changed)

## Database
8. **Run Migrations**: `python cli.py migrate` (if model changes)
9. **Generate Migration**: Create new Alembic migration if schema changed

## Pre-commit
10. **Pre-commit Hooks**: Should run automatically on commit
11. **Manual Pre-commit**: `pre-commit run --all-files` (if needed)

## Infrastructure
12. **Docker Build**: Ensure Docker images build successfully
13. **Service Start**: Verify services start correctly with `make up`

## Documentation
14. **Update Documentation**: If API changes, update relevant docs
15. **Type Annotations**: Ensure all new code has proper type hints

## Key Requirements
- All tests must pass
- No linting errors
- Type checking must pass  
- Code must be formatted consistently
- New features need appropriate tests