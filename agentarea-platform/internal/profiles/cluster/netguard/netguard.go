// Package netguard is the outbound HTTP clients and dialer of
// kernel/netguard: a member's address resolved, vetted and pinned on every
// hop (url_safety.py PinnedSender), a vendor's through the environment's
// proxy, an internal service's direct; all trusting the system roots plus
// AGENTAREA_HTTP_EXTRA_CA_CERTS (outbound_tls.py).
package netguard

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"net/netip"
	"net/url"
	"os"
	"strconv"
	"strings"
	"syscall"
	"time"

	"golang.org/x/net/http/httpproxy"

	kernel "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
)

// Trust is the outbound root pool.
type Trust struct{ pool *x509.CertPool }

// RootCAs implements kernel.Trust.
func (t *Trust) RootCAs() *x509.CertPool { return t.pool }

// LoadTrust is the system roots plus the PEM file at extra; a file that
// does not load is an error naming the variable, so startup stops on it.
func LoadTrust(extra string) (*Trust, error) {
	pool, err := x509.SystemCertPool()
	if err != nil {
		pool = x509.NewCertPool()
	}
	extra = strings.TrimSpace(extra)
	if extra == "" {
		return &Trust{pool: pool}, nil
	}
	pem, err := os.ReadFile(extra)
	if err == nil && !pool.AppendCertsFromPEM(pem) {
		err = errors.New("no PEM certificate in the file")
	}
	if err != nil {
		return nil, fmt.Errorf("AGENTAREA_HTTP_EXTRA_CA_CERTS=%s names no readable PEM file of CA certificates: %w", extra, err)
	}
	return &Trust{pool: pool}, nil
}

// Outbound hands out the client of each destination.
type Outbound struct {
	guard    *kernel.Guard
	public   *kernel.Guard
	trust    *Trust
	log      *slog.Logger
	proxy    func(*url.URL) (*url.URL, error)
	member   *http.Transport
	vendor   *http.Transport
	internal *http.Transport
	dial     func(ctx context.Context, network, address string) (net.Conn, error)
}

// Options configure New.
type Options struct {
	// Resolver defaults to net.DefaultResolver.
	Resolver kernel.Resolver
	// Proxy is the environment's proxy choice; nil reads HTTP_PROXY,
	// HTTPS_PROXY and NO_PROXY.
	Proxy func(*url.URL) (*url.URL, error)
	// Dial defaults to a net.Dialer with a 30s timeout.
	Dial func(ctx context.Context, network, address string) (net.Conn, error)
}

// New builds the clients from the policy configuration.
func New(cfg kernel.Config, trust *Trust, log *slog.Logger, opts Options) (*Outbound, error) {
	policy, err := kernel.NewAddressPolicy(cfg.AllowPrivate, cfg.PrivateAllowlist)
	if err != nil {
		return nil, err
	}
	if opts.Resolver == nil {
		opts.Resolver = net.DefaultResolver
	}
	if opts.Proxy == nil {
		opts.Proxy = httpproxy.FromEnvironment().ProxyFunc()
	}
	if opts.Dial == nil {
		opts.Dial = (&net.Dialer{Timeout: 30 * time.Second, KeepAlive: 30 * time.Second}).DialContext
	}
	publicPolicy, err := kernel.NewAddressPolicy(false, nil)
	if err != nil {
		return nil, err
	}
	o := &Outbound{
		guard:  &kernel.Guard{Policy: policy, Resolver: opts.Resolver},
		public: &kernel.Guard{Policy: publicPolicy, Resolver: opts.Resolver},
		trust:  trust, log: log, proxy: opts.Proxy, dial: opts.Dial,
	}
	o.vendor = o.transport(func(r *http.Request) (*url.URL, error) { return o.proxy(r.URL) }, opts.Dial)
	o.internal = o.transport(nil, opts.Dial)
	o.member = o.transport(memberProxy, o.dialPinned)
	return o, nil
}

func (o *Outbound) transport(proxy func(*http.Request) (*url.URL, error), dial func(context.Context, string, string) (net.Conn, error)) *http.Transport {
	t := http.DefaultTransport.(*http.Transport).Clone()
	t.Proxy = proxy
	t.DialContext = dial
	t.TLSClientConfig = &tls.Config{RootCAs: o.trust.RootCAs(), MinVersion: tls.VersionTLS12}
	return t
}

// Transport implements kernel.Clients.
func (o *Outbound) Transport(dest kernel.Destination) http.RoundTripper {
	switch dest {
	case kernel.Member:
		return &pinned{o: o, guard: o.guard}
	case kernel.Public:
		return &pinned{o: o, guard: o.public}
	case kernel.Vendor:
		return o.vendor
	case kernel.Internal:
		return o.internal
	}
	return o.internal
}

// Client is an http.Client for dest; a member's client vets every redirect hop.
func (o *Outbound) Client(dest kernel.Destination, timeout time.Duration) *http.Client {
	return &http.Client{Transport: o.Transport(dest), Timeout: timeout}
}

// Dialer implements kernel.Clients: member_connection for a host a member
// set over a protocol other than HTTP.
func (o *Outbound) Dialer() kernel.Dialer { return memberDialer{o: o} }

// Guard is the policy the clients enforce.
func (o *Outbound) Guard() *kernel.Guard { return o.guard }

var _ kernel.Clients = (*Outbound)(nil)

type vettedKey struct{}

// vetted is what RoundTrip decided for one request: the host, its checked
// addresses, and the proxy it goes through (then pinning is the proxy's).
type vetted struct {
	host  string
	addrs []netip.Addr
	proxy *url.URL
}

type pinned struct {
	o     *Outbound
	guard *kernel.Guard
}

// RoundTrip is PinnedSender.send.
func (p *pinned) RoundTrip(req *http.Request) (*http.Response, error) {
	u := req.URL
	if u.Scheme != "http" && u.Scheme != "https" {
		return nil, &kernel.URLError{Msg: fmt.Sprintf("URL scheme '%s' is not allowed", u.Scheme)}
	}
	host := strings.ToLower(u.Hostname())
	if host == "" {
		return nil, &kernel.URLError{Msg: "URL has no host"}
	}
	addrs, err := p.guard.Vet(req.Context(), host, false)
	if err != nil {
		return nil, err
	}
	proxy, err := p.o.proxy(u)
	if err != nil {
		return nil, err
	}
	v := &vetted{host: host, addrs: addrs, proxy: proxy}
	return p.o.member.RoundTrip(req.WithContext(context.WithValue(req.Context(), vettedKey{}, v)))
}

func memberProxy(r *http.Request) (*url.URL, error) {
	if v, ok := r.Context().Value(vettedKey{}).(*vetted); ok {
		return v.proxy, nil
	}
	return nil, errors.New("member request was not vetted")
}

// dialPinned connects to the vetted addresses in order; only a refused
// connection moves on to the next. A dial to the proxy is not pinned.
func (o *Outbound) dialPinned(ctx context.Context, network, address string) (net.Conn, error) {
	v, ok := ctx.Value(vettedKey{}).(*vetted)
	if !ok {
		return nil, errors.New("member connection was not vetted")
	}
	if v.proxy != nil {
		return o.dial(ctx, network, address)
	}
	_, port, err := net.SplitHostPort(address)
	if err != nil {
		return nil, err
	}
	return o.dialInOrder(ctx, network, v.host, v.addrs, port)
}

func (o *Outbound) dialInOrder(ctx context.Context, network, host string, addrs []netip.Addr, port string) (net.Conn, error) {
	var lastErr error
	for i, a := range addrs {
		conn, err := o.dial(ctx, network, net.JoinHostPort(a.String(), port))
		if err == nil {
			return conn, nil
		}
		lastErr = err
		if i == len(addrs)-1 || !errors.Is(err, syscall.ECONNREFUSED) {
			break
		}
		if o.log != nil {
			o.log.WarnContext(ctx, fmt.Sprintf("%s refused a connection at %s; trying its next address", host, a), "error", err.Error())
		}
	}
	return nil, lastErr
}

type memberDialer struct{ o *Outbound }

// DialContext is member_connection: host vetted with member_address's
// wording, then connected at a vetted address.
func (d memberDialer) DialContext(ctx context.Context, network, address string) (net.Conn, error) {
	host, port, err := net.SplitHostPort(address)
	if err != nil {
		return nil, err
	}
	if _, err := strconv.Atoi(port); err != nil {
		return nil, fmt.Errorf("port %q: %w", port, err)
	}
	host = strings.ToLower(host)
	addrs, err := d.o.guard.Vet(ctx, host, true)
	if err != nil {
		return nil, err
	}
	return d.o.dialInOrder(ctx, network, host, addrs, port)
}
