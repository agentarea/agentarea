package domain

import (
	"slices"
	"strings"
	"testing"
	"time"
)

func TestAnUpstreamIsSchemeHostAndPort(t *testing.T) {
	for in, want := range map[string]string{
		"http://proxy.example.com:3128":  "http://proxy.example.com:3128",
		"https://proxy.example.com:443":  "https://proxy.example.com:443",
		"socks5://1.2.3.4:1080":          "socks5://1.2.3.4:1080",
		"HTTPS://Proxy.Example.com:443/": "https://Proxy.Example.com:443",
		"http://[::1]:3128":              "http://[::1]:3128",
	} {
		got, err := ValidateUpstreamURL(in)
		if err != nil || got != want {
			t.Errorf("%q: %q, %v", in, got, err)
		}
	}
}

func TestAnUpstreamWithAnythingElseIsRefused(t *testing.T) {
	for in, want := range map[string]string{
		"ftp://proxy.example.com:21":              "upstream_url scheme must be http, https or socks5",
		"http://proxy.example.com":                "upstream_url needs an explicit host:port",
		"http://user:pass@proxy.example.com:3128": "upstream_url must not carry credentials; set username and password_secret_id",
		"http://proxy.example.com:3128/path":      "upstream_url must be scheme://host:port with no path, query or fragment",
		"http://proxy.example.com:3128?x=1":       "upstream_url must be scheme://host:port with no path, query or fragment",
		"http://proxy.example.com:3128#f":         "upstream_url must be scheme://host:port with no path, query or fragment",
		"proxy.example.com:3128":                  "upstream_url scheme must be http, https or socks5",
		"http://proxy.example.com:99999":          "upstream_url must be scheme://host:port",
		"http://proxy.example.com:port":           "upstream_url must be scheme://host:port",
		"http://[::1:3128":                        "upstream_url must be scheme://host:port",
		"http://:3128":                            "upstream_url needs an explicit host:port",
	} {
		if _, err := ValidateUpstreamURL(in); err == nil || err.Error() != want {
			t.Errorf("%q: %v, want %q", in, err, want)
		}
	}
}

func TestCredentialsToAPlaintextProxyNeedAnExplicitOptIn(t *testing.T) {
	s := func(v string) *string { return &v }
	secret := s("6b0e7c1d-2a3f-4b5c-8d9e-0f1a2b3c4d5e")
	if errs := CredentialErrors(s("http://p.example.com:3128"), s("u"), secret, false); len(errs) != 1 || !strings.Contains(errs[0], "unencrypted") {
		t.Fatalf("plaintext: %v", errs)
	}
	if errs := CredentialErrors(s("http://p.example.com:3128"), s("u"), secret, true); len(errs) != 0 {
		t.Fatalf("opted in: %v", errs)
	}
	if errs := CredentialErrors(s("https://p.example.com:443"), s("u"), secret, false); len(errs) != 0 {
		t.Fatalf("https: %v", errs)
	}
	if errs := CredentialErrors(s("https://p.example.com:443"), nil, secret, false); !slices.Equal(errs, []string{"password_secret_id needs a username"}) {
		t.Fatalf("password alone: %v", errs)
	}
	if errs := CredentialErrors(nil, s("u"), nil, false); !slices.Equal(errs, []string{"credentials need an upstream_url"}) {
		t.Fatalf("no upstream: %v", errs)
	}
	if errs := CredentialErrors(s("socks5://p:1080"), s(""), nil, false); len(errs) != 0 {
		t.Fatalf("an empty username is none: %v", errs)
	}
}

// The audit diff of an update is _compute_changes over to_dict: every column
// but the stamps, compared as str(), a credential value masked.
func TestAnUpdateIsAuditedAsItsChangedColumns(t *testing.T) {
	s := func(v string) *string { return &v }
	before := EgressExit{ID: "e", Name: "office", UpstreamURL: s("http://p:3128"), CreatedAt: time.Unix(1, 0), UpdatedAt: time.Unix(1, 0)}
	after := before
	after.Description, after.Username, after.AllowPlaintextCredentials, after.UpdatedAt = s("d"), s("u"), true, time.Unix(2, 0)
	got := AuditChanges(before, after)
	want := []map[string]any{
		{"field": "allow_plaintext_credentials", "before": "***", "after": "***"},
		{"field": "description", "before": nil, "after": "d"},
		{"field": "username", "before": nil, "after": "u"},
	}
	if len(got) != len(want) {
		t.Fatalf("changes %v", got)
	}
	for i := range want {
		for k, v := range want[i] {
			if got[i][k] != v {
				t.Fatalf("change %d = %v, want %v", i, got[i], want[i])
			}
		}
	}
	if c := AuditChanges(before, before); c == nil || len(c) != 0 {
		t.Fatalf("an unchanged exit is an empty diff, not none: %#v", c)
	}
}
