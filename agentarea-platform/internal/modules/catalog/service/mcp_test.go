package service

import (
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
)

func object(t *testing.T, raw string) wirejson.Object {
	t.Helper()
	v, err := wirejson.Unmarshal([]byte(raw))
	if err != nil {
		t.Fatal(err)
	}
	return v.(wirejson.Object)
}

func dumpsT(t *testing.T, v any) string {
	t.Helper()
	b, err := wirejson.Marshal(v, wirejson.Dumps)
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

func TestIconURL(t *testing.T) {
	s := func(v string) *string { return &v }
	if IconURL("http://api/", ProviderIcons, nil) != nil || IconURL("http://api", ProviderIcons, s("")) != nil {
		t.Fatal("empty icon has a URL")
	}
	if got := *IconURL("http://api/", ProviderIcons, s("openai")); got != "http://api/static/icons/providers/openai.svg" {
		t.Fatal(got)
	}
	if got := *IconURL("http://api", ProviderIcons, s("https://cdn/x.png")); got != "https://cdn/x.png" {
		t.Fatal(got)
	}
}

func TestDeriveEnvSchemaFromPackage(t *testing.T) {
	spec := object(t, `{"connection_type":"command","package_name":"pkg","raw_spec":{"packages":[
		{"name":"other","environmentVariables":[{"name":"NO"}]},
		{"name":"pkg","environmentVariables":[{"name":"KEY","description":"d","isSecret":true,"default":"x"},{"name":"MODE","default":"a"}]}]}}`)
	got := dumpsT(t, DeriveEnvSchema(spec))
	want := `[{"name": "KEY", "description": "d", "isSecret": true, "isRequired": false, "required": false}, ` +
		`{"name": "MODE", "description": "", "isSecret": false, "isRequired": false, "required": false, "default": "a"}]`
	if got != want {
		t.Fatalf("got  %s\nwant %s", got, want)
	}
}

func TestDeriveEnvSchemaDeclaredWins(t *testing.T) {
	spec := object(t, `{"connection_type":"url","env_schema":[{"name":"A","required":true}],"raw_spec":{"remotes":[{"headers":[{"name":"B"}]}]}}`)
	if got := dumpsT(t, DeriveEnvSchema(spec)); got != `[{"name": "A", "description": "", "isSecret": false, "isRequired": true, "required": true}]` {
		t.Fatal(got)
	}
}

func TestMirrorOf(t *testing.T) {
	m, err := MirrorOf(object(t, `{"connection_type":"command","command":"npx","args":["-y","pkg"]}`))
	if err != nil {
		t.Fatal(err)
	}
	if *m.DockerImageURL != "agentarea/agentarea-mcp-base" || dumpsT(t, m.Cmd) != `["npx", "-y", "pkg"]` ||
		dumpsT(t, m.Tags) != `["registry", "command"]` || m.RemoteURL != nil {
		t.Fatalf("%+v", m)
	}
	m, err = MirrorOf(object(t, `{"url":"https://mcp","transport":"streamable-http"}`))
	if err != nil {
		t.Fatal(err)
	}
	if *m.DockerImageURL != "" || *m.RemoteURL != "https://mcp" || m.Cmd != nil || dumpsT(t, m.Tags) != `["registry", "url", "streamable-http"]` {
		t.Fatalf("%+v", m)
	}
}
