package service

import (
	"encoding/json"
	"strings"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
)

// IconURL is build_icon_url: empty is nil, an http(s) URL passes, anything
// else names a built-in SVG under the API's public base.
func IconURL(apiURL, namespace string, icon *string) *string {
	if icon == nil || *icon == "" {
		return nil
	}
	if strings.HasPrefix(*icon, "http://") || strings.HasPrefix(*icon, "https://") {
		return icon
	}
	u := strings.TrimRight(apiURL, "/") + "/static/icons/" + namespace + "/" + *icon + ".svg"
	return &u
}

// ProviderIcons is PROVIDER_ICON_NAMESPACE.
const ProviderIcons = "providers"

// PyTruthy is bool() of a decoded JSON value.
func PyTruthy(v any) bool {
	switch x := v.(type) {
	case nil:
		return false
	case bool:
		return x
	case string:
		return x != ""
	case json.Number:
		f, err := x.Float64()
		return err != nil || f != 0
	case wirejson.Float:
		return x != 0
	case []any:
		return len(x) > 0
	case wirejson.Object:
		return len(x) > 0
	}
	return true
}

func get(o wirejson.Object, key string) any {
	v, _ := o.Get(key)
	return v
}

// NormalizeEnvSchema is normalize_env_schema.
func NormalizeEnvSchema(entries any) []any {
	list, ok := entries.([]any)
	if !ok {
		return []any{}
	}
	out := []any{}
	for _, e := range list {
		entry, ok := e.(wirejson.Object)
		if !ok {
			continue
		}
		name, ok := get(entry, "name").(string)
		if !ok || strings.TrimSpace(name) == "" {
			continue
		}
		required, has := entry.Get("isRequired")
		if !has || required == nil {
			required = get(entry, "required")
		}
		req := PyTruthy(required)
		secret := PyTruthy(get(entry, "isSecret"))
		desc := get(entry, "description")
		if !PyTruthy(desc) {
			desc = ""
		}
		field := wirejson.Object{
			{Key: "name", Value: name}, {Key: "description", Value: desc}, {Key: "isSecret", Value: secret},
			{Key: "isRequired", Value: req}, {Key: "required", Value: req},
		}
		if d, has := entry.Get("default"); !secret && has {
			field = append(field, wirejson.Member{Key: "default", Value: d})
		}
		out = append(out, field)
	}
	return out
}

// DeriveEnvSchema is derive_env_schema_from_spec.
func DeriveEnvSchema(spec any) []any {
	o, ok := spec.(wirejson.Object)
	if !ok {
		return []any{}
	}
	if declared := NormalizeEnvSchema(get(o, "env_schema")); len(declared) > 0 {
		return declared
	}
	raw, ok := get(o, "raw_spec").(wirejson.Object)
	if !ok {
		raw = o
	}
	conn := get(o, "connection_type")
	if conn == "url" {
		remotes, ok := get(raw, "remotes").([]any)
		if !ok {
			return []any{}
		}
		var matching []wirejson.Object
		for _, r := range remotes {
			if m, ok := r.(wirejson.Object); ok {
				matching = append(matching, m)
			}
		}
		if url := get(o, "url"); PyTruthy(url) {
			var byURL []wirejson.Object
			for _, m := range matching {
				if pyEqual(get(m, "url"), url) {
					byURL = append(byURL, m)
				}
			}
			if len(byURL) > 0 {
				matching = byURL
			} else if len(matching) != 1 {
				return []any{}
			}
		} else if len(matching) != 1 {
			return []any{}
		}
		return NormalizeEnvSchema(get(matching[0], "headers"))
	}
	if conn != "command" && conn != "docker" {
		return []any{}
	}
	packages, ok := get(raw, "packages").([]any)
	if !ok {
		return []any{}
	}
	registry := get(o, "package_registry")
	name := get(o, "package_name")
	if !PyTruthy(name) {
		name = get(o, "image")
	}
	var candidates []wirejson.Object
	for _, p := range packages {
		m, ok := p.(wirejson.Object)
		if ok && (!PyTruthy(registry) || pyEqual(get(m, "registryType"), registry)) {
			candidates = append(candidates, m)
		}
	}
	if PyTruthy(name) {
		var matching []wirejson.Object
		for _, c := range candidates {
			if pyEqual(get(c, "name"), name) || pyEqual(get(c, "identifier"), name) {
				matching = append(matching, c)
			}
		}
		if len(matching) > 0 {
			candidates = matching
		} else if len(candidates) != 1 {
			return []any{}
		}
	} else if len(candidates) != 1 {
		return []any{}
	}
	if len(candidates) != 1 {
		return []any{}
	}
	return NormalizeEnvSchema(get(candidates[0], "environmentVariables"))
}

// pyEqual is == over decoded JSON scalars; containers never match here.
func pyEqual(a, b any) bool {
	switch x := a.(type) {
	case string:
		y, ok := b.(string)
		return ok && x == y
	case bool:
		y, ok := b.(bool)
		return ok && x == y
	case json.Number:
		y, ok := b.(json.Number)
		return ok && x == y
	case nil:
		return b == nil
	}
	return false
}

// MirroredServer is what _update_mcp_server writes, JSON fields decoded.
type MirroredServer struct {
	DockerImageURL *string
	Tags           []any
	EnvSchema      []any
	Cmd            []any
	RemoteURL      *string
	JSONSpec       any
}

// ErrBadSpec is an item spec Python fails on with a TypeError: a 500.
type ErrBadSpec struct{ Field string }

func (e *ErrBadSpec) Error() string { return "catalog item spec: " + e.Field + " has the wrong type" }

// MirrorOf is _update_mcp_server's mapping of an mcp_servers item's spec
// (`item.spec or {}`); nil Cmd is None.
func MirrorOf(spec wirejson.Object) (MirroredServer, error) {
	conn, has := spec.Get("connection_type")
	if !has {
		conn = "url"
	}
	empty := ""
	m := MirroredServer{DockerImageURL: &empty, EnvSchema: DeriveEnvSchema(spec), JSONSpec: get(spec, "raw_spec")}
	switch conn {
	case "docker":
		img, has := spec.Get("image")
		if !has {
			img = ""
		}
		switch s := img.(type) {
		case nil:
			m.DockerImageURL = nil
		case string:
			m.DockerImageURL = &s
		default:
			return m, &ErrBadSpec{Field: "image"}
		}
	case "command":
		base := "agentarea/agentarea-mcp-base"
		m.DockerImageURL = &base
		command, has := spec.Get("command")
		if !has {
			command = ""
		}
		if PyTruthy(command) {
			m.Cmd = []any{command}
			args, has := spec.Get("args")
			switch a := args.(type) {
			case []any:
				m.Cmd = append(m.Cmd, a...)
			case string:
				for _, r := range a {
					m.Cmd = append(m.Cmd, string(r))
				}
			default:
				if has {
					return m, &ErrBadSpec{Field: "args"}
				}
			}
		}
	}
	if conn == "url" {
		if u := get(spec, "url"); u != nil {
			s, ok := u.(string)
			if !ok {
				return m, &ErrBadSpec{Field: "url"}
			}
			m.RemoteURL = &s
		}
	}
	m.Tags = []any{"registry", conn}
	if t := get(spec, "transport"); PyTruthy(t) {
		m.Tags = append(m.Tags, t)
	}
	return m, nil
}
