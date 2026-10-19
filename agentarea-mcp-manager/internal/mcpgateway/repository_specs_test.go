package mcpgateway

import (
	"reflect"
	"testing"
)

// Either json_spec column can hold the JSON literal `null` instead of SQL NULL:
// the control plane writes it whenever the field was omitted, and the query's
// COALESCE only substitutes for the SQL flavour. Unmarshalling `null` into a map
// yields nil, so merging the instance spec over it used to panic with
// "assignment to entry in nil map" -- gin recovered, and the platform saw a 500
// for every request to that instance.
func TestDecodeSpecsAcceptsNullServerSpec(t *testing.T) {
	spec, err := decodeSpecs([]byte("null"), []byte(`{"type":"docker","port":8000}`))
	if err != nil {
		t.Fatalf("decodeSpecs() error = %v, want nil", err)
	}
	if spec == nil {
		t.Fatal("decodeSpecs() returned a nil map; callers write into it")
	}
	if got := spec["type"]; got != "docker" {
		t.Fatalf("spec[type] = %v, want docker", got)
	}
	if got := spec["port"]; got != float64(8000) {
		t.Fatalf("spec[port] = %v, want 8000", got)
	}
}

func TestDecodeSpecsAcceptsNullInstanceSpec(t *testing.T) {
	spec, err := decodeSpecs([]byte(`{"type":"docker","image":"example:1"}`), []byte("null"))
	if err != nil {
		t.Fatalf("decodeSpecs() error = %v, want nil", err)
	}
	if got := spec["image"]; got != "example:1" {
		t.Fatalf("spec[image] = %v, want example:1", got)
	}
}

func TestDecodeSpecsInstanceOverridesServer(t *testing.T) {
	spec, err := decodeSpecs(
		[]byte(`{"type":"docker","image":"example:1","port":9000}`),
		[]byte(`{"port":8000}`),
	)
	if err != nil {
		t.Fatalf("decodeSpecs() error = %v, want nil", err)
	}
	if got := spec["port"]; got != float64(8000) {
		t.Fatalf("spec[port] = %v, want the instance value 8000", got)
	}
	if got := spec["image"]; got != "example:1" {
		t.Fatalf("spec[image] = %v, want the server value example:1", got)
	}
}

func TestDecodeSpecsRejectsMalformedJSON(t *testing.T) {
	if _, err := decodeSpecs([]byte("{"), []byte("{}")); err == nil {
		t.Fatal("decodeSpecs() error = nil, want a decode failure for malformed server spec")
	}
	if _, err := decodeSpecs([]byte("{}"), []byte("{")); err == nil {
		t.Fatal("decodeSpecs() error = nil, want a decode failure for malformed instance spec")
	}
}
func TestMergeLoadedSpecsPreservesConvertedDockerTransport(t *testing.T) {
	spec, err := mergeLoadedSpecs(
		[]byte(`{"type":"command","args":["server-arg"],"cmd":["npx","-y","pkg","--flag"],"endpoint_url":"https://server.example","catalog":"keep"}`),
		[]byte(`{"image":"repo@sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef","command":["/opt/mcp-pkg/bin/server","--flag"],"port":8080}`),
		"docker",
		[]byte(`["npx","-y","pkg","--flag"]`),
		"server-image:latest",
	)
	if err != nil {
		t.Fatalf("mergeLoadedSpecs() error = %v", err)
	}
	wantTransport := map[string]any{
		"type":    "docker",
		"image":   "repo@sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
		"command": []any{"/opt/mcp-pkg/bin/server", "--flag"},
		"port":    float64(8080),
	}
	for key, want := range wantTransport {
		if got := spec[key]; !reflect.DeepEqual(got, want) {
			t.Fatalf("spec[%q] = %#v, want %#v", key, got, want)
		}
	}
	for _, key := range []string{"args", "cmd", "endpoint_url"} {
		if _, exists := spec[key]; exists {
			t.Fatalf("spec[%q] unexpectedly survived converted Docker merge", key)
		}
	}
	if spec["catalog"] != "keep" {
		t.Fatalf("non-transport server metadata was not preserved: %#v", spec["catalog"])
	}
}

// urlServerSpec mirrors agentarea_mcp/transport_spec.py for a url instance:
// server_transport_spec, then merge_transport_spec, each followed by
// _normalize_url_keys.
func TestURLServerSpecMirrorsThePlatformMerge(t *testing.T) {
	for name, tc := range map[string]struct {
		server, instance, remoteURL, want string
	}{
		"remote_url is the default":            {`{}`, `{}`, "https://remote.example/mcp", "https://remote.example/mcp"},
		"server endpoint_url beats remote_url": {`{"endpoint_url":"https://declared.example"}`, `{}`, "https://remote.example/mcp", "https://declared.example"},
		"instance endpoint_url wins":           {`{"endpoint_url":"https://declared.example"}`, `{"endpoint_url":"https://mine.example"}`, "https://remote.example", "https://mine.example"},
		"legacy url on the instance":           {`null`, `{"url":"https://legacy.example"}`, "", "https://legacy.example"},
		"legacy external_url":                  {`{}`, `{"external_url":"https://external.example"}`, "", "https://external.example"},
		"server endpoint beats instance url":   {`{}`, `{"url":"https://legacy.example"}`, "https://remote.example", "https://remote.example"},
		"server legacy url is normalized":      {`{"type":"url","url":"https://server-legacy.example"}`, `null`, "", "https://server-legacy.example"},
		"no endpoint at all":                   {`{}`, `{}`, "", ""},
	} {
		t.Run(name, func(t *testing.T) {
			server, err := urlServerSpec([]byte(tc.server), []byte(tc.instance), tc.remoteURL)
			if err != nil {
				t.Fatalf("urlServerSpec() error = %v", err)
			}
			if server.EndpointURL != tc.want {
				t.Fatalf("EndpointURL = %q, want %q", server.EndpointURL, tc.want)
			}
		})
	}
}

func TestURLServerSpecHeadersAndSecretNames(t *testing.T) {
	server, err := urlServerSpec(
		[]byte(`{"headers":{"X-Server":"s"},"env_vars":["SERVER_ONLY"]}`),
		[]byte(`{"headers":{"X-Instance":"i"},"env_vars":["X-Api-Key"]}`),
		"https://remote.example",
	)
	if err != nil {
		t.Fatalf("urlServerSpec() error = %v", err)
	}
	if !reflect.DeepEqual(server.Headers, map[string]string{"X-Instance": "i"}) {
		t.Fatalf("Headers = %#v, want the instance's object replacing the server's", server.Headers)
	}
	if !reflect.DeepEqual(server.EnvVars, []string{"X-Api-Key"}) {
		t.Fatalf("EnvVars = %#v, want the instance's own names only", server.EnvVars)
	}
}

func TestURLServerSpecRejectsMalformedHeaders(t *testing.T) {
	for _, instance := range []string{
		`{"headers":{"X-Count":3}}`,
		`{"headers":"X-Api-Key: v"}`,
		`{"env_vars":[3]}`,
		`{"endpoint_url":42}`,
	} {
		if _, err := urlServerSpec([]byte(`{}`), []byte(instance), "https://remote.example"); err == nil {
			t.Errorf("urlServerSpec(%s) error = nil, want a refusal", instance)
		}
	}
}
