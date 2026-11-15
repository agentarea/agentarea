// Package netguard is the outbound address policy (SSRF guard) and outbound
// TLS trust: AGENTAREA_HTTP_ALLOW_PRIVATE, AGENTAREA_HTTP_PRIVATE_ALLOWLIST,
// AGENTAREA_HTTP_EXTRA_CA_CERTS. It merges three copies of one policy:
// Python utils/url_safety.py, outbound.py and outbound_tls.py, mcp-manager
// egress and event-service egress. Python's is the strictest of the three
// and is the one kept (see Blocked).
//
// A request to a member-supplied URL resolves the host once, checks every
// address, and connects to a checked address (pinned), so DNS rebinding
// cannot swap it after the check. The dialer and clients doing that are in
// profiles/cluster/netguard.
package netguard

import (
	"context"
	"crypto/x509"
	"errors"
	"fmt"
	"net"
	"net/http"
	"net/netip"
	"net/url"
	"regexp"
	"strconv"
	"strings"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/config"
)

// ErrUnsafe is wrapped by every refusal of a destination (UnsafeUrlError).
var ErrUnsafe = errors.New("unsafe outbound destination")

// URLError refuses a URL for its form: scheme or host.
type URLError struct{ Msg string }

func (e *URLError) Error() string { return e.Msg }

// Unwrap makes the error an ErrUnsafe.
func (e *URLError) Unwrap() error { return ErrUnsafe }

// ResolveError is a host that does not resolve (UnsafeUrlError from
// socket.gaierror; callers tell it apart from a refusal).
type ResolveError struct {
	Host string
	Err  error
}

func (e *ResolveError) Error() string { return fmt.Sprintf("Could not resolve host '%s'", e.Host) }

// Unwrap returns ErrUnsafe and the resolver's error.
func (e *ResolveError) Unwrap() []error { return []error{ErrUnsafe, e.Err} }

// BlockedError is an address the policy refuses.
type BlockedError struct {
	Host   string
	Addr   netip.Addr
	Reason string
	// Connect: refused for a raw connection (member_address), not a URL.
	Connect bool
}

func (e *BlockedError) Error() string {
	if e.Connect {
		return fmt.Sprintf("Host '%s' resolves to non-public address %s; refusing to connect", e.Host, e.Addr)
	}
	return fmt.Sprintf("URL host '%s' resolves to non-public address %s; refusing request", e.Host, e.Addr)
}

// Unwrap makes the error an ErrUnsafe.
func (e *BlockedError) Unwrap() error { return ErrUnsafe }

// Policy decides which destinations outbound calls may reach.
type Policy interface {
	// CheckURL validates scheme and host and resolves it; every address must pass.
	CheckURL(ctx context.Context, rawURL string) ([]netip.Addr, error)
	// CheckAddr validates one resolved address.
	CheckAddr(host string, addr netip.Addr) error
}

// Dialer connects only to addresses the policy allows, pinned to the
// address it checked.
type Dialer interface {
	DialContext(ctx context.Context, network, address string) (net.Conn, error)
}

// Trust is the outbound root pool: system roots plus AGENTAREA_HTTP_EXTRA_CA_CERTS.
type Trust interface {
	RootCAs() *x509.CertPool
}

// Resolver looks a host up; *net.Resolver is one.
type Resolver interface {
	LookupNetIP(ctx context.Context, network, host string) ([]netip.Addr, error)
}

// Destination is who decided where a request goes (outbound.py).
type Destination int

const (
	// Member is an address a workspace member set, directly or through a
	// document: every hop is resolved, vetted and pinned.
	Member Destination = iota
	// Vendor is a fixed third-party service: through the deployment's
	// egress proxy when one is configured, with the extra CAs trusted.
	Vendor
	// Internal is a service of the deployment itself: called directly,
	// never through the proxy.
	Internal
)

// Clients hands out the HTTP client for each destination.
type Clients interface {
	Transport(dest Destination) http.RoundTripper
	Dialer() Dialer
}

// Config is HttpSettings (config/http.py).
type Config struct {
	// AllowPrivate admits every private address (AGENTAREA_HTTP_ALLOW_PRIVATE).
	AllowPrivate bool
	// PrivateAllowlist holds host globs and CIDRs a member's URL may reach
	// although private (AGENTAREA_HTTP_PRIVATE_ALLOWLIST).
	PrivateAllowlist []string
	// ExtraCACerts is a PEM file of CAs trusted besides the system roots
	// (AGENTAREA_HTTP_EXTRA_CA_CERTS); one that does not load stops startup.
	ExtraCACerts string
}

// LoadConfig reads Config; a malformed allowlist CIDR fails it.
func LoadConfig(l *config.Loader) Config {
	c := Config{
		AllowPrivate:     l.BoolEnv("AGENTAREA_HTTP_ALLOW_PRIVATE", false),
		PrivateAllowlist: l.ListEnv("AGENTAREA_HTTP_PRIVATE_ALLOWLIST", nil),
		ExtraCACerts:     l.StringEnv("AGENTAREA_HTTP_EXTRA_CA_CERTS", ""),
	}
	if _, err := NewAddressPolicy(c.AllowPrivate, c.PrivateAllowlist); err != nil {
		l.Fail("AGENTAREA_HTTP_PRIVATE_ALLOWLIST", err)
	}
	return c
}

// AddressPolicy is OutboundPolicy: public addresses always, private ones
// when allowed outright, by host glob or by CIDR.
type AddressPolicy struct {
	allowPrivate bool
	hosts        []*regexp.Regexp
	nets         []netip.Prefix
}

// NewAddressPolicy splits the allowlist into CIDRs (an entry with "/";
// host bits may be set) and host globs.
func NewAddressPolicy(allowPrivate bool, allowlist []string) (*AddressPolicy, error) {
	p := &AddressPolicy{allowPrivate: allowPrivate}
	for _, entry := range allowlist {
		if strings.Contains(entry, "/") {
			prefix, err := netip.ParsePrefix(entry)
			if err != nil {
				return nil, fmt.Errorf("private allowlist entry %q: %w", entry, err)
			}
			p.nets = append(p.nets, prefix.Masked())
			continue
		}
		p.hosts = append(p.hosts, compileGlob(strings.ToLower(entry)))
	}
	return p, nil
}

// AllowPrivate reports the blanket opt-out.
func (p *AddressPolicy) AllowPrivate() bool { return p.allowPrivate }

// Permits is OutboundPolicy.permits.
func (p *AddressPolicy) Permits(host string, addr netip.Addr) bool {
	if _, blocked := Blocked(addr); !blocked || p.allowPrivate {
		return true
	}
	h := strings.ToLower(host)
	for _, pattern := range p.hosts {
		if pattern.MatchString(h) {
			return true
		}
	}
	addr = addr.WithZone("")
	for _, n := range p.nets {
		if n.Addr().Is4() == addr.Is4() && n.Contains(addr) {
			return true
		}
	}
	return false
}

// CheckAddr refuses an address Permits does not admit.
func (p *AddressPolicy) CheckAddr(host string, addr netip.Addr) error {
	if p.Permits(host, addr) {
		return nil
	}
	reason, _ := Blocked(addr)
	return &BlockedError{Host: host, Addr: addr.WithZone(""), Reason: reason}
}

// Guard is a Policy over an AddressPolicy and a Resolver.
type Guard struct {
	Policy   *AddressPolicy
	Resolver Resolver
}

// CheckURL is validate_outbound_url with a policy: an http(s) URL with a
// host, every address of it admitted. An IP literal is not resolved. With
// AllowPrivate nothing is resolved and no address is returned.
func (g *Guard) CheckURL(ctx context.Context, rawURL string) ([]netip.Addr, error) {
	u, err := url.Parse(rawURL)
	if err != nil {
		return nil, &URLError{Msg: "URL has no host"}
	}
	scheme := strings.ToLower(u.Scheme)
	if scheme != "http" && scheme != "https" {
		return nil, &URLError{Msg: fmt.Sprintf("URL scheme '%s' is not allowed; use http or https", u.Scheme)}
	}
	host := strings.ToLower(u.Hostname())
	if host == "" {
		return nil, &URLError{Msg: "URL has no host"}
	}
	if g.Policy.allowPrivate {
		return nil, nil
	}
	return g.Vet(ctx, host, false)
}

// CheckAddr implements Policy.
func (g *Guard) CheckAddr(host string, addr netip.Addr) error { return g.Policy.CheckAddr(host, addr) }

// Addresses is an IP literal itself, else every address host resolves to.
func (g *Guard) Addresses(ctx context.Context, host string) ([]netip.Addr, error) {
	if a, err := netip.ParseAddr(host); err == nil {
		return []netip.Addr{a.WithZone("")}, nil
	}
	addrs, err := g.Resolver.LookupNetIP(ctx, "ip", host)
	if err != nil {
		return nil, &ResolveError{Host: host, Err: err}
	}
	if len(addrs) == 0 {
		return nil, &URLError{Msg: fmt.Sprintf("Host '%s' has no address", host)}
	}
	out := make([]netip.Addr, len(addrs))
	for i, a := range addrs {
		out[i] = a.WithZone("")
	}
	return out, nil
}

// Vet resolves host and checks every address; connect picks
// member_address's wording over the URL check's.
func (g *Guard) Vet(ctx context.Context, host string, connect bool) ([]netip.Addr, error) {
	addrs, err := g.Addresses(ctx, host)
	if err != nil {
		return nil, err
	}
	for _, a := range addrs {
		if !g.Policy.Permits(host, a) {
			reason, _ := Blocked(a)
			return nil, &BlockedError{Host: host, Addr: a, Reason: reason, Connect: connect}
		}
	}
	return addrs, nil
}

var _ Policy = (*Guard)(nil)

// DefaultPort is the port a URL without one dials.
func DefaultPort(u *url.URL) int {
	if p := u.Port(); p != "" {
		if n, err := strconv.Atoi(p); err == nil {
			return n
		}
	}
	if strings.EqualFold(u.Scheme, "https") {
		return 443
	}
	return 80
}
