package config

import "os"

// backendEnvironment reads the operator's choice of execution backend.
//
// AGENTAREA_MCP_BACKEND is the name the Helm chart has always shipped — and nothing read
// it. The code looked only at AGENTAREA_ENV, so a deployment declaring
// `AGENTAREA_MCP_BACKEND: kubernetes` got whatever auto-detection guessed instead. That
// guess is right in-cluster, which is why it went unnoticed; anywhere else the
// declaration was silently discarded. In particular a manager running outside a
// cluster could not be pointed at one, which is exactly what targeting a
// separate execution cluster requires.
//
// Both names select the same thing. AGENTAREA_MCP_BACKEND takes precedence because it is
// the one already deployed; AGENTAREA_ENV stays working so existing
// installs keep their behaviour.
//
// Empty means "detect", which is the documented behaviour rather than a
// fallback: nothing was declared to fall back from. An unrecognised value is
// rejected downstream by the environment detector.
func backendEnvironment() string {
	if backendType := os.Getenv("AGENTAREA_MCP_BACKEND"); backendType != "" {
		return backendType
	}
	return os.Getenv("AGENTAREA_ENV")
}
