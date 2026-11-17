//go:build suite

package harness

import (
	"os"
	"strings"
)

// StackURL is a test server's URL as the stack reaches it. A stack whose
// roles run in containers sets SUITE_STACK_HOST (host.docker.internal), since
// 127.0.0.1 there is the container itself; a stack on the host leaves it unset.
func StackURL(u string) string {
	host := os.Getenv("SUITE_STACK_HOST")
	if host == "" {
		return u
	}
	return strings.Replace(u, "://127.0.0.1:", "://"+host+":", 1)
}
