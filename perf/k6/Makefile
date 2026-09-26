.PHONY: smoke baseline stress env-check

# make imports the shell environment automatically; ?= only fills in a
# default when the var isn't already set (e.g. from ru.env).
AGENTAREA_API_URL ?= https://api.agentarea.ru
WORKSPACE ?= user

# k6 does not read the process environment on its own — every var has to be
# forwarded with -e, even ones already exported in the shell.
K6_ENV = -e AGENTAREA_TOKEN="$(AGENTAREA_TOKEN)" -e AGENTAREA_API_URL="$(AGENTAREA_API_URL)" -e WORKSPACE="$(WORKSPACE)"

env-check:
	@test -n "$(AGENTAREA_TOKEN)" || (echo "AGENTAREA_TOKEN is not set — run: set -a; . ~/.config/agentarea/ru.env; set +a" >&2; exit 1)

smoke: env-check
	@mkdir -p results
	@k6 run $(K6_ENV) scenarios/smoke.js

baseline: env-check
	@mkdir -p results
	@k6 run $(K6_ENV) scenarios/baseline.js

# Never point this at prod — see scenarios/stress.js.
stress: env-check
	@mkdir -p results
	@k6 run $(K6_ENV) -e ALLOW_STRESS=1 scenarios/stress.js
