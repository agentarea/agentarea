"""Where analytics goes, and what the operator is told about it."""

# Installations send no key: our edge in front of Pulse adds the agentarea product's
# key for this host, so the key never ships and can change without a release.
COLLECTOR_URL = "https://analytics.agentarea.ai"

DOCS_URL = "https://docs.agentarea.ai/self-host/analytics"

NOTICE = (
    f"Anonymous usage analytics is on (what is sent: {DOCS_URL}). "
    "Turn it off with AGENTAREA_ANALYTICS_ENABLED=false."
)
