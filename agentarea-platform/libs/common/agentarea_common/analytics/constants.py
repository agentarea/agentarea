"""Where analytics goes, and what the operator is told about it."""

COLLECTOR_URL = "https://analytics.agentarea.ai"
# An append-only Pulse key: it can only add events to the agentarea product, which it
# pins, so it is safe to ship in every installation. Infra provisions the real key.
COLLECTOR_KEY = "pc_agentarea_placeholder"

DOCS_URL = "https://docs.agentarea.ai/self-host/analytics"

NOTICE = (
    f"Anonymous usage analytics is on (what is sent: {DOCS_URL}). "
    "Turn it off with AGENTAREA_ANALYTICS_ENABLED=false."
)
