package secrets

import (
	"errors"
	"strings"
	"testing"
)

const u = "0b8f6a3e-1c2d-4e5f-8a9b-0c1d2e3f4a5b"

func TestParseManagedName(t *testing.T) {
	cases := []struct {
		name string
		want OwnerRef
		ok   bool
	}{
		{"provider_config_" + u, OwnerRef{"provider_config", u}, true},
		{"provider_config_nope", OwnerRef{}, false},
		{"mcp_instance_" + u + "_API_KEY", OwnerRef{"mcp_instance", u}, true},
		{"mcp_instance_" + u + "_A_B_C", OwnerRef{"mcp_instance", u}, true},
		{"mcp_instance_" + u, OwnerRef{}, false},
		{"mcp_auth_cred:" + u, OwnerRef{"mcp_auth_config", u}, true},
		{"channel_cred:telegram:" + u, OwnerRef{"trigger", u}, true},
		{"channel_cred:" + u, OwnerRef{}, false},
		{"wallet_creds_" + u, OwnerRef{"agent", u}, true},
		{"openapi:" + u + ":header:X-A:b", OwnerRef{"openapi_connection", u}, true},
		{"openapi:" + u + ":url_var:k", OwnerRef{"openapi_connection", u}, true},
		{"openapi:" + u + ":other:k", OwnerRef{}, false},
		{"task-input/" + u + "/field", OwnerRef{"task", u}, true},
		{"task-input/" + u, OwnerRef{}, false},
		{"a2a_push_token:" + u + ":any config id", OwnerRef{"task", u}, true},
		{"a2a_push_token:" + u + ":", OwnerRef{}, false},
		{"task_webhook:" + u, OwnerRef{"task", u}, true},
		{"my-secret", OwnerRef{}, false},
	}
	for _, c := range cases {
		got, ok := ParseManagedName(c.name)
		if ok != c.ok || got != c.want {
			t.Errorf("%q: got %v %v want %v %v", c.name, got, ok, c.want, c.ok)
		}
	}
}

func TestManagedField(t *testing.T) {
	cases := map[string]string{
		"mcp_instance_" + u + "_API_KEY":         "API_KEY",
		"mcp_instance_" + u + "_":                "",
		"openapi:" + u + ":header:Authorization": "Authorization",
		"openapi:" + u + ":url_var:tenant":       "tenant",
		"channel_cred:telegram:" + u:             "telegram",
		"task-input/" + u + "/token":             "token",
		"provider_config_" + u:                   "",
		"plain":                                  "",
	}
	for name, want := range cases {
		if got := ManagedField(name); got != want {
			t.Errorf("%q: got %q want %q", name, got, want)
		}
	}
}

func TestValidateUserName(t *testing.T) {
	for _, ok := range []string{"ab", "a-b_c", "a1", strings.Repeat("a", 64)} {
		if err := ValidateUserName(ok); err != nil {
			t.Errorf("%q refused: %v", ok, err)
		}
	}
	for _, bad := range []string{"", "a", "A1", "-ab", "ab-", "a b", strings.Repeat("a", 65), "ab\n", "ключ"} {
		err := ValidateUserName(bad)
		if !errors.Is(err, ErrInvalidName) || errors.Is(err, ErrReservedName) {
			t.Errorf("%q: %v", bad, err)
		}
	}
	err := ValidateUserName("task-input/x")
	if !errors.Is(err, ErrReservedName) || !errors.Is(err, ErrInvalidName) {
		t.Errorf("reserved: %v", err)
	}
	if !strings.Contains(err.Error(), "'task-input/'") {
		t.Errorf("message: %v", err)
	}
}

func TestEveryReservedPrefixIsParsedOrExplicitlyNot(t *testing.T) {
	ps := parsers()
	prefixes := ReservedPrefixes()
	if len(ps) != len(prefixes) {
		t.Fatalf("%d parsers for %d prefixes", len(ps), len(prefixes))
	}
	for i, p := range ps {
		if p.prefix != prefixes[i] {
			t.Errorf("parser %d is %q, prefix list says %q", i, p.prefix, prefixes[i])
		}
	}
}
