// Package egress decides which addresses a member-named host may reach: only
// public ones unless the operator opens private ones, the same policy the
// platform's outbound client applies (AGENTAREA_HTTP_ALLOW_PRIVATE,
// AGENTAREA_HTTP_PRIVATE_ALLOWLIST).
package egress

import (
	"context"
	"fmt"
	"net"
	"net/http"
	"path"
	"strings"
	"syscall"
	"time"
)

// Policy is the operator's allowance for private addresses.
type Policy struct {
	AllowPrivate bool
	hosts        []string
	nets         []*net.IPNet
}

// NewPolicy reads allowlist entries: host globs ("*.svc.cluster.local",
// "localhost") and CIDRs.
func NewPolicy(allowPrivate bool, allowlist []string) (Policy, error) {
	p := Policy{AllowPrivate: allowPrivate}
	for _, entry := range allowlist {
		if strings.Contains(entry, "/") {
			_, ipnet, err := net.ParseCIDR(entry)
			if err != nil {
				return Policy{}, fmt.Errorf("private allowlist entry %q: %w", entry, err)
			}
			p.nets = append(p.nets, ipnet)
			continue
		}
		p.hosts = append(p.hosts, strings.ToLower(entry))
	}
	return p, nil
}

func (p Policy) hostAllowed(host string) bool {
	host = strings.ToLower(strings.TrimSuffix(host, "."))
	for _, pattern := range p.hosts {
		if ok, _ := path.Match(pattern, host); ok {
			return true
		}
	}
	return false
}

func (p Policy) ipAllowed(ip net.IP) bool {
	if !private(ip) {
		return true
	}
	for _, n := range p.nets {
		if n.Contains(ip) {
			return true
		}
	}
	return false
}

func private(ip net.IP) bool {
	return ip.IsLoopback() || ip.IsPrivate() || ip.IsLinkLocalUnicast() || ip.IsLinkLocalMulticast() ||
		ip.IsInterfaceLocalMulticast() || ip.IsMulticast() || ip.IsUnspecified() ||
		cgnat.Contains(ip)
}

var cgnat = &net.IPNet{IP: net.IPv4(100, 64, 0, 0), Mask: net.CIDRMask(10, 32)}

const dialTimeout = 30 * time.Second

// Dialer for a connection to a member's host. The address is checked at
// connect time, after resolution, so a name that resolves to a private address
// is refused too.
func (p Policy) Dialer(host string) *net.Dialer {
	d := &net.Dialer{Timeout: dialTimeout}
	if p.AllowPrivate || p.hostAllowed(host) {
		return d
	}
	d.Control = func(_, address string, _ syscall.RawConn) error {
		h, _, err := net.SplitHostPort(address)
		if err != nil {
			return err
		}
		ip := net.ParseIP(h)
		if ip == nil || !p.ipAllowed(ip) {
			return &PrivateAddressError{Host: host}
		}
		return nil
	}
	return d
}

// PrivateAddressError is the refusal of a member's host that resolved to a
// private address.
type PrivateAddressError struct{ Host string }

func (e *PrivateAddressError) Error() string {
	return fmt.Sprintf("%s resolves to a private address; set AGENTAREA_HTTP_PRIVATE_ALLOWLIST to allow it", e.Host)
}

// Transport for member hosts. It uses no proxy, so the address check applies
// to the host itself.
func (p Policy) Transport() *http.Transport {
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.Proxy = nil
	transport.DialContext = func(ctx context.Context, network, addr string) (net.Conn, error) {
		host, _, err := net.SplitHostPort(addr)
		if err != nil {
			return nil, err
		}
		return p.Dialer(host).DialContext(ctx, network, addr)
	}
	return transport
}
