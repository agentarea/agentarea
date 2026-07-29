package config

import "os"

// backendEnvironment reads the operator's choice of execution backend.
//
// BACKEND_TYPE is the name the Helm chart has always shipped — and nothing read
// it. The code looked only at BACKEND_ENVIRONMENT, so a deployment declaring
// `BACKEND_TYPE: kubernetes` got whatever auto-detection guessed instead. That
// guess is right in-cluster, which is why it went unnoticed; anywhere else the
// declaration was silently discarded. In particular a manager running outside a
// cluster could not be pointed at one, which is exactly what targeting a
// separate execution cluster requires.
//
// Both names select the same thing. BACKEND_TYPE takes precedence because it is
// the one already deployed; BACKEND_ENVIRONMENT stays working so existing
// installs keep their behaviour.
//
// Empty means "detect", which is the documented behaviour rather than a
// fallback: nothing was declared to fall back from. An unrecognised value is
// rejected downstream by the environment detector.
func backendEnvironment() string {
	if backendType := os.Getenv("BACKEND_TYPE"); backendType != "" {
		return backendType
	}
	return os.Getenv("BACKEND_ENVIRONMENT")
}
