// Command exec-supervisor runs inside the sandbox image beside untrusted code.
// It supervises processes and nothing else: no database client, no secrets,
// no API code; the standard library and sandbox/supervisor only (lint list
// exec-supervisor). It moves here from agentarea-mcp-manager in phase 4.
package main

import (
	"fmt"
	"os"
)

func main() {
	_, _ = fmt.Fprintln(os.Stderr, "exec-supervisor: not implemented in agentarea-go yet; the agentarea-mcp-manager build is the one in use")
	os.Exit(1)
}
