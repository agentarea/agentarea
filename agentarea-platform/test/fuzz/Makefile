AGENTAREA_API_URL ?= http://localhost:8000
AGENTAREA_AUTH_KRATOS_ADMIN_URL ?= http://localhost:4434
AGENTAREA_AUTH_KRATOS_URL ?= http://localhost:4433
export AGENTAREA_API_URL AGENTAREA_AUTH_KRATOS_ADMIN_URL AGENTAREA_AUTH_KRATOS_URL

# Exit 5 means both modules skipped at import (the stack is unreachable): a
# fuzz run that exercised nothing fails instead of passing empty.
test:
	@uv run --locked python -m pytest test_openapi_fuzz.py test_stateful_fuzz.py; \
	status=$$?; \
	if [ "$$status" -eq 5 ]; then \
		echo "The fuzz suite collected nothing: both modules skipped at import (reason above)." >&2; \
		exit 1; \
	fi; \
	exit $$status

collect:
	uv run --locked python -m pytest --collect-only -q

.PHONY: test collect
