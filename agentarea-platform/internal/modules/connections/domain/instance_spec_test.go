package domain

import (
	"encoding/json"
	"reflect"
	"strings"
	"testing"
	"time"
)

func TestServerTransportSpecDeclaresFromColumns(t *testing.T) {
	url := "https://mcp.example.com/mcp"
	got := ServerTransportSpec(nil, &url, nil, nil)
	if got["type"] != TransportURL || got["endpoint_url"] != url {
		t.Fatalf("url spec = %v", got)
	}
	got = ServerTransportSpec(nil, nil, []any{"npx", "-y", "pkg"}, nil)
	if got["type"] != TransportCommand || got["command"] != "npx" || !reflect.DeepEqual(got["args"], []any{"-y", "pkg"}) {
		t.Fatalf("command spec = %v", got)
	}
	got = ServerTransportSpec(map[string]any{"type": "url", "url": "https://x"}, nil, nil, nil)
	if got["endpoint_url"] != "https://x" || got["url"] != nil {
		t.Fatalf("legacy url key not normalized: %v", got)
	}
}

func TestMergeTransportSpecConvertedDockerDropsServerTransport(t *testing.T) {
	server := map[string]any{"type": "command", "command": "npx", "args": []any{"x"}, "environment": map[string]any{"A": "1"}}
	got := MergeTransportSpec(server, map[string]any{"image": "ghcr.io/a/b:1"}, TransportDocker)
	if _, has := got["command"]; has {
		t.Fatalf("server command kept on a converted instance: %v", got)
	}
	if got["type"] != TransportDocker || got["image"] != "ghcr.io/a/b:1" || got["environment"] == nil {
		t.Fatalf("merge = %v", got)
	}
}

func TestImageServesStdio(t *testing.T) {
	spec := map[string]any{"image": "ghcr.io/a/b:1", "packages": []any{
		map[string]any{"registryType": "oci", "identifier": "ghcr.io/a/b:2", "transport": map[string]any{"type": "stdio"}},
	}}
	if !ImageServesStdio(spec) {
		t.Fatal("stdio OCI package not detected")
	}
	spec["port"] = json.Number("8080")
	if ImageServesStdio(spec) {
		t.Fatal("a declared port overrides the package")
	}
}

func TestValidateJSONSpec(t *testing.T) {
	cases := []struct {
		spec map[string]any
		want []string
	}{
		{map[string]any{}, []string{"Required field 'type' is missing (url, docker or command)"}},
		{map[string]any{"type": "url", "endpoint_url": "ftp://x"}, []string{"Field 'endpoint_url' must start with http:// or https://"}},
		{map[string]any{"type": "docker", "image": "a", "port": json.Number("70000")}, []string{"Field 'port' must be an integer between 1 and 65535"}},
		{map[string]any{"type": "command", "command": "npx", "tool_timeout_seconds": json.Number("0")}, []string{"Field 'tool_timeout_seconds' must be between 1 and 1800"}},
		{map[string]any{"type": "bundle"}, []string{"bundle is not a valid MCP server instance type"}},
	}
	for _, c := range cases {
		if got := ValidateJSONSpec(c.spec); !reflect.DeepEqual(got, c.want) {
			t.Errorf("ValidateJSONSpec(%v) = %v, want %v", c.spec, got, c.want)
		}
	}
}

func TestJSONSpecErrorChain(t *testing.T) {
	cases := []struct {
		spec map[string]any
		kind SpecKind
		want string
	}{
		{map[string]any{"a": "x\x00"}, InstanceCreateSpec, "$.a contains a NUL character"},
		{map[string]any{"storage": map[string]any{"enabled": false}}, InstanceCreateSpec, `json_spec.storage must be exactly {"enabled": true}`},
		{map[string]any{"egress_exit": "nope"}, InstanceCreateSpec, "json_spec.egress_exit must be an egress exit id"},
		{map[string]any{"image": "--privileged"}, InstanceCreateSpec, "'--privileged' is not a valid container image reference"},
		{map[string]any{"egress": map[string]any{"required": true}}, InstanceCreateSpec, "json_spec.egress is set on a server spec, not an instance"},
		{map[string]any{"type": "url", "port": json.Number("1")}, InstanceUpdateSpec, "Instance json_spec cannot update transport fields: port, type"},
		{map[string]any{"headers": map[string]any{"A": map[string]any{"secret_name": "s"}}}, ServerSpec, "a server spec may not reference a workspace secret"},
		{map[string]any{"egress": map[string]any{"required": "yes"}}, ServerSpec, `json_spec.egress must be exactly {"required": <bool>}`},
		{map[string]any{"environment": map[string]any{"A": "1"}}, InstanceCreateSpec, ""},
	}
	for _, c := range cases {
		if got := JSONSpecError(c.spec, c.kind); got != c.want {
			t.Errorf("JSONSpecError(%v) = %q, want %q", c.spec, got, c.want)
		}
	}
}

func TestExtractSecretsSecretByDefault(t *testing.T) {
	schema := []EnvSchemaEntry{{Name: "REGION"}, {Name: "TOKEN", IsSecret: true}}
	spec := map[string]any{"environment": map[string]any{"REGION": "eu", "TOKEN": "t0k", "OTHER": "o"},
		"headers": map[string]any{"X-Ref": map[string]any{"secret_name": "ws_key"}}}
	stored, secrets, err := ExtractSecrets(spec, schema, nil)
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(stored["environment"], map[string]any{"REGION": "eu"}) {
		t.Fatalf("plain config not kept alone: %v", stored["environment"])
	}
	if !reflect.DeepEqual(secrets, map[string]string{"TOKEN": "t0k", "OTHER": "o"}) {
		t.Fatalf("secrets = %v", secrets)
	}
	if !reflect.DeepEqual(stored["env_vars"], []any{"OTHER", "TOKEN"}) {
		t.Fatalf("env_vars = %v", stored["env_vars"])
	}
	if !IsSecretRef(stored["headers"].(map[string]any)["X-Ref"]) {
		t.Fatal("a reference must stay in the spec")
	}
}

func TestExtractSecretsMaskKeepsStoredValue(t *testing.T) {
	prev := map[string]any{"headers": map[string]any{"Auth": map[string]any{"secret_name": "k"}}, "env_vars": []any{"TOKEN"}}
	spec := map[string]any{"headers": map[string]any{"Auth": MaskedValue}, "environment": map[string]any{"TOKEN": MaskedValue}}
	stored, secrets, err := ExtractSecrets(spec, nil, prev)
	if err != nil {
		t.Fatal(err)
	}
	if len(secrets) != 0 {
		t.Fatalf("a mask must never be stored as a value: %v", secrets)
	}
	if !IsSecretRef(stored["headers"].(map[string]any)["Auth"]) {
		t.Fatal("a mask over a reference keeps the reference")
	}
}

func TestExtractSecretsRefusesMalformedReference(t *testing.T) {
	_, _, err := ExtractSecrets(map[string]any{"headers": map[string]any{"A": map[string]any{"secret_name": "x", "b": 1}}}, nil, nil)
	var si *SpecInvalid
	if err == nil || !strings.Contains(err.Error(), "headers.A must be a string") {
		t.Fatalf("err = %v", err)
	}
	_ = si
}

func TestConnectionCostError(t *testing.T) {
	cases := map[string]struct {
		cost map[string]any
		want string
	}{
		"free":      {map[string]any{"source": "free"}, ""},
		"rate":      {map[string]any{"source": "rate", "rate": map[string]any{"amount": "0.5", "currency": "RUB"}}, ""},
		"settled":   {map[string]any{"source": "settled"}, "a connection's own cost is a rate, a reported field or free, not settled"},
		"bad":       {map[string]any{"source": "x"}, "unknown cost source 'x'"},
		"negative":  {map[string]any{"source": "rate", "rate": map[string]any{"amount": json.Number("-1"), "currency": "RUB"}}, "rate.amount must be a non-negative number, got -1"},
		"currency":  {map[string]any{"source": "rate", "rate": map[string]any{"amount": "1", "currency": "rub"}}, "rate.currency must be an ISO 4217 code like RUB, got 'rub'"},
		"reported":  {map[string]any{"source": "reported", "reported": map[string]any{"path": "cost", "currency": "USD"}}, "reported.path must be a path like $.field, got 'cost'"},
		"quantity":  {map[string]any{"source": "rate", "rate": map[string]any{"amount": "1", "currency": "USD", "quantity": map[string]any{"default": json.Number("2")}}}, "rate.quantity must be one of arg, count, path; got {'default': 2}"},
		"argQty":    {map[string]any{"source": "rate", "rate": map[string]any{"amount": "1", "currency": "USD", "quantity": map[string]any{"arg": "n", "default": json.Number("5")}}}, ""},
		"notNumber": {map[string]any{"source": "rate", "rate": map[string]any{"amount": "abc", "currency": "USD"}}, "rate.amount must be a number, got 'abc'"},
	}
	for name, c := range cases {
		if got := ConnectionCostError(c.cost); got != c.want {
			t.Errorf("%s: ConnectionCostError = %q, want %q", name, got, c.want)
		}
	}
}

func TestDeriveBundleVerification(t *testing.T) {
	now := time.Date(2026, 1, 2, 3, 4, 5, 0, time.UTC)
	bundle := Instance{JSONSpec: map[string]any{"members": []any{"a", "b"}}}
	ok := Instance{Name: "A", Verification: Verification{Status: VerifySucceeded}}
	bad := Instance{Name: "B", Verification: Verification{Status: VerifyFailed}}
	if v := DeriveBundleVerification(bundle, map[string]Instance{"a": ok}, now); v.Error == nil || v.Error.Code != "bundle_member_missing" {
		t.Fatalf("missing member: %+v", v)
	}
	if v := DeriveBundleVerification(bundle, map[string]Instance{"a": ok, "b": bad}, now); v.Error.Message != "Bundle members not ready: [B]." {
		t.Fatalf("not ready: %+v", v.Error)
	}
	if v := DeriveBundleVerification(bundle, map[string]Instance{"a": ok, "b": ok}, now); v.Status != VerifySucceeded || v.Error != nil {
		t.Fatalf("ready: %+v", v)
	}
	if v := DeriveBundleVerification(Instance{}, nil, now); v.Error.Code != "bundle_empty" {
		t.Fatalf("empty: %+v", v)
	}
}
