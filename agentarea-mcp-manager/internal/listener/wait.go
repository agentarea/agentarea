// Package listener waits for a started workload to accept connections.
package listener

import (
	"context"
	"fmt"
	"net"
	"net/url"
	"time"
)

// Wait blocks until the workload at internalURL accepts a TCP connection, or
// the deadline passes.
//
// "Running" is the container's state, not the server's. A freshly started MCP
// image reports running while its process is still binding (or, on mcp-base,
// still installing its package and initializing its stdio server), and
// proxying into that window returns a bare connection-refused to the caller —
// indistinguishable from a broken instance.
func Wait(ctx context.Context, internalURL string, deadline time.Time) error {
	target, err := url.Parse(internalURL)
	if err != nil || target.Host == "" {
		return fmt.Errorf("instance address %q is not usable", internalURL)
	}

	dialer := &net.Dialer{Timeout: 2 * time.Second}
	for {
		conn, err := dialer.DialContext(ctx, "tcp", target.Host)
		if err == nil {
			conn.Close()
			return nil
		}
		if time.Now().After(deadline) {
			return fmt.Errorf("instance at %s never accepted a connection: %w", target.Host, err)
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(250 * time.Millisecond):
		}
	}
}
