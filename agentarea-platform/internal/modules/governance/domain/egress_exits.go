package domain

import (
	"errors"
	"fmt"
	"net/netip"
	"sort"
	"strconv"
	"strings"
	"time"
)

// ManagedByPlatform marks an exit the operator writes into the platform workspace.
const ManagedByPlatform = "platform"

// EgressExit is an egress_exits row (egress_exit_model.py): a proxy an MCP
// instance may leave through. PasswordSecretID references the password in
// the secret catalog; the row never holds it.
type EgressExit struct {
	ID                        string
	Name                      string
	Description               *string
	UpstreamURL               *string
	Username                  *string
	PasswordSecretID          *string
	Via                       *string
	RemoteDNS                 bool
	AllowPlaintextCredentials bool
	ManagedBy                 *string
	WorkspaceID               string
	CreatedBy                 string
	CreatedAt                 time.Time
	UpdatedAt                 time.Time
}

// IsPlatform is is_platform: the operator's, never changed through the API.
func (e EgressExit) IsPlatform() bool { return e.ManagedBy != nil && *e.ManagedBy == ManagedByPlatform }

func upstreamSchemes() []string { return []string{"http", "https", "socks5"} }

var errUpstreamForm = errors.New("upstream_url must be scheme://host:port")

// ValidateUpstreamURL is validate_upstream_url: scheme://host:port and
// nothing else, read as urllib.parse.urlsplit reads it.
func ValidateUpstreamURL(raw string) (string, error) {
	u, err := urlsplit(raw)
	if err != nil {
		return "", errUpstreamForm
	}
	if _, err := u.port(); err != nil {
		return "", errUpstreamForm
	}
	known := false
	for _, s := range upstreamSchemes() {
		known = known || u.scheme == s
	}
	if !known {
		return "", errors.New("upstream_url scheme must be http, https or socks5")
	}
	if strings.Contains(u.netloc, "@") {
		return "", errors.New("upstream_url must not carry credentials; set username and password_secret_id")
	}
	port, _ := u.port()
	if u.hostname() == "" || port < 0 {
		return "", errors.New("upstream_url needs an explicit host:port")
	}
	if (u.path != "" && u.path != "/") || u.query != "" || u.fragment != "" {
		return "", errors.New("upstream_url must be scheme://host:port with no path, query or fragment")
	}
	return u.scheme + "://" + u.netloc, nil
}

// CredentialErrors is credential_errors: what the egress proxy would refuse
// about these credentials, said at save time.
func CredentialErrors(upstreamURL, username, passwordSecretID *string, allowPlaintext bool) []string {
	var errs []string
	hasUser := username != nil && *username != ""
	if passwordSecretID != nil && !hasUser {
		errs = append(errs, "password_secret_id needs a username")
	}
	credentials := hasUser || passwordSecretID != nil
	if credentials && upstreamURL == nil {
		errs = append(errs, "credentials need an upstream_url")
	}
	if credentials && upstreamURL != nil && !allowPlaintext {
		if u, err := urlsplit(*upstreamURL); err != nil || u.scheme != "https" {
			errs = append(errs, "credentials to an http or socks5 proxy travel unencrypted; use https or set allow_plaintext_credentials")
		}
	}
	return errs
}

// AuditChanges is @audited's _compute_changes over two to_dict snapshots:
// every column but the stamps, by name, compared as str(); a credential's
// value masked.
func AuditChanges(before, after EgressExit) []map[string]any {
	b, a := auditColumns(before), auditColumns(after)
	names := make([]string, 0, len(b))
	for k := range b {
		names = append(names, k)
	}
	sort.Strings(names)
	out := []map[string]any{}
	for _, k := range names {
		old, cur := b[k], a[k]
		if pyStr(old) == pyStr(cur) {
			continue
		}
		if k == "allow_plaintext_credentials" {
			old, cur = "***", "***"
		}
		out = append(out, map[string]any{"field": k, "before": old, "after": cur})
	}
	return out
}

func auditColumns(e EgressExit) map[string]any {
	opt := func(p *string) any {
		if p == nil {
			return nil
		}
		return *p
	}
	return map[string]any{
		"id": e.ID, "name": e.Name, "description": opt(e.Description), "upstream_url": opt(e.UpstreamURL),
		"username": opt(e.Username), "password_secret_id": opt(e.PasswordSecretID), "via": opt(e.Via),
		"remote_dns": e.RemoteDNS, "allow_plaintext_credentials": e.AllowPlaintextCredentials,
		"managed_by": opt(e.ManagedBy), "workspace_id": e.WorkspaceID, "created_by": e.CreatedBy,
	}
}

func pyStr(v any) string {
	switch x := v.(type) {
	case nil:
		return "None"
	case bool:
		if x {
			return "True"
		}
		return "False"
	case string:
		return x
	}
	return fmt.Sprint(v)
}

// splitURL is a urllib.parse.SplitResult.
type splitURL struct{ scheme, netloc, path, query, fragment string }

const schemeChars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+-."

// urlsplit is CPython 3.12's urllib.parse.urlsplit, raising where it raises.
func urlsplit(url string) (splitURL, error) {
	url = strings.TrimLeft(url, "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f ")
	url = strings.NewReplacer("\t", "", "\r", "", "\n", "").Replace(url)
	var u splitURL
	if i := strings.IndexByte(url, ':'); i > 0 && isASCIIAlpha(url[0]) {
		valid := true
		for _, c := range url[:i] {
			valid = valid && strings.ContainsRune(schemeChars, c)
		}
		if valid {
			u.scheme, url = strings.ToLower(url[:i]), url[i+1:]
		}
	}
	if strings.HasPrefix(url, "//") {
		end := len(url)
		for _, c := range "/?#" {
			if i := strings.IndexRune(url[2:], c); i >= 0 && i+2 < end {
				end = i + 2
			}
		}
		u.netloc, url = url[2:end], url[end:]
		open, closed := strings.Contains(u.netloc, "["), strings.Contains(u.netloc, "]")
		if open != closed {
			return splitURL{}, errors.New("Invalid IPv6 URL") //nolint:staticcheck // CPython's message
		}
		if open {
			if err := checkBracketedNetloc(u.netloc); err != nil {
				return splitURL{}, err
			}
		}
	}
	if before, after, ok := strings.Cut(url, "#"); ok {
		url, u.fragment = before, after
	}
	if before, after, ok := strings.Cut(url, "?"); ok {
		url, u.query = before, after
	}
	u.path = url
	return u, nil
}

func isASCIIAlpha(c byte) bool { return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') }

// checkBracketedNetloc is _check_bracketed_netloc: the bracketed host is an
// IPv6 address or an IPvFuture one.
func checkBracketedNetloc(netloc string) error {
	hostinfo := netloc[strings.LastIndex(netloc, "@")+1:]
	_, bracketed, _ := strings.Cut(hostinfo, "[")
	host, _, _ := strings.Cut(bracketed, "]")
	if strings.HasPrefix(host, "v") {
		return nil
	}
	if a, err := netip.ParseAddr(host); err != nil || !a.Is6() {
		return errors.New("Invalid IPv6 URL") //nolint:staticcheck // CPython's message
	}
	return nil
}

// hostinfo is SplitResult._hostinfo: the hostname and the port text, port
// "" when absent.
func (u splitURL) hostinfo() (string, string) {
	info := u.netloc[strings.LastIndex(u.netloc, "@")+1:]
	if _, bracketed, open := strings.Cut(info, "["); open {
		host, rest, _ := strings.Cut(bracketed, "]")
		_, port, _ := strings.Cut(rest, ":")
		return host, port
	}
	host, port, _ := strings.Cut(info, ":")
	return host, port
}

func (u splitURL) hostname() string {
	h, _ := u.hostinfo()
	return strings.ToLower(h)
}

// port is SplitResult.port: -1 when absent, an error when not 0-65535.
func (u splitURL) port() (int, error) {
	_, p := u.hostinfo()
	if p == "" {
		return -1, nil
	}
	for _, c := range p {
		if c < '0' || c > '9' {
			return 0, fmt.Errorf("port could not be cast to integer value as %q", p)
		}
	}
	n, err := strconv.Atoi(p)
	if err != nil || n > 65535 {
		return 0, errors.New("port out of range 0-65535")
	}
	return n, nil
}
