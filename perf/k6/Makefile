.PHONY: smoke baseline stress env-check journey-smoke journey-nightly journey-stress

# No default: a wrong-but-plausible slug silently hits someone else's
# workspace instead of failing loudly (the old default, "user", stopped being
# the owner's workspace once it was renamed to "jamakase54").
#
# AGENTAREA_TOKEN and AGENTAREA_API_URL are deliberately NOT passed via -e:
# `k6 run` forwards the whole process environment into __ENV on its own
# (--include-system-env-vars defaults to true), so exporting them is enough —
# putting a secret in -e would put it in argv, which `ps`/`pgrep -fl` show in
# plaintext to anyone with local process-list access. -e stays reserved for
# non-secret knobs like WORKSPACE.
env-check:
	@test -n "$(AGENTAREA_TOKEN)" || (echo "AGENTAREA_TOKEN is not set — run: set -a; . ~/.config/agentarea/ru.env; set +a" >&2; exit 1)
	@test -n "$(WORKSPACE)" || (echo "WORKSPACE is not set — pass it explicitly: WORKSPACE=<slug> make smoke" >&2; exit 1)

smoke: env-check
	@mkdir -p results
	@k6 run -e WORKSPACE="$(WORKSPACE)" scenarios/smoke.js

baseline: env-check
	@mkdir -p results
	@k6 run -e WORKSPACE="$(WORKSPACE)" scenarios/baseline.js

# Never point this at prod — see scenarios/stress.js.
stress: env-check
	@mkdir -p results
	@k6 run -e WORKSPACE="$(WORKSPACE)" -e ALLOW_STRESS=1 scenarios/stress.js

# Journey suite (scenarios/journeys/) — write journeys only run when
# WORKSPACE=perf-k6; against anything else these are read-only.
journey-smoke: env-check
	@k6 run -e WORKSPACE="$(WORKSPACE)" scenarios/journeys/smoke.js

journey-nightly: env-check
	@k6 run -e WORKSPACE="$(WORKSPACE)" scenarios/journeys/nightly.js

# Never point this at prod — see scenarios/journeys/stress.js.
journey-stress: env-check
	@k6 run -e WORKSPACE="$(WORKSPACE)" -e ALLOW_STRESS=1 scenarios/journeys/stress.js
