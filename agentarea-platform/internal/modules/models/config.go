package models

import "os"

// LocalHost is AppSettings.local_host: AGENTAREA_LOCAL_HOST when set, else
// host.docker.internal inside a Docker container, else localhost.
func LocalHost(lookup func(string) (string, bool)) string {
	if v, _ := lookup("AGENTAREA_LOCAL_HOST"); v != "" {
		return v
	}
	if _, err := os.Stat("/.dockerenv"); err == nil {
		return "host.docker.internal"
	}
	return "localhost"
}
