package domain

import (
	"regexp"
	"strings"
	"unicode"
)

// Mapping is a decoded JSON object.
type Mapping = map[string]any

// AsMapping is _mapping: the object, or an empty one.
func AsMapping(v any) Mapping {
	if m, ok := v.(map[string]any); ok && m != nil {
		return m
	}
	return Mapping{}
}

func field(m Mapping, key string) any { return m[key] }

// Text is _text: a non-empty string or "".
func Text(v any) string {
	s, _ := v.(string)
	return s
}

// Registry types (VALID_REGISTRY_TYPES).
const (
	TypeMCPServers   = "mcp_servers"
	TypeSkills       = "skills"
	TypeLLMProviders = "llm_providers"
	TypeLLMModels    = "llm_models"
	TypeAgents       = "agents"
	TypeBundles      = "bundles"
	TypeSourceTypes  = "source_types"
)

// RegistryTypes is VALID_REGISTRY_TYPES in its order.
func RegistryTypes() []string {
	return []string{TypeMCPServers, TypeSkills, TypeLLMProviders, TypeLLMModels, TypeAgents, TypeBundles, TypeSourceTypes}
}

// Facets is ItemFacets; "" is NULL for the nullable ones.
type Facets struct {
	Category string
	SortKey  string
	Featured bool
	Protocol string
	Hosting  string
	Pricing  string
}

// Protocols, Hostings and Pricings are the facet orders.
func Protocols() []string { return []string{"mcp", "api"} }
func Hostings() []string  { return []string{"vendor", "agentarea"} }
func Pricings() []string  { return []string{"paid", "own_key", "free"} }

func tagValue(tags []any, prefix string) string {
	for _, t := range tags {
		if s, ok := t.(string); ok && strings.HasPrefix(s, prefix) {
			return s[len(prefix):]
		}
	}
	return ""
}

var (
	dashes    = regexp.MustCompile(`[-_]+`)
	nonAlnumI = regexp.MustCompile(`(?i)[^a-z0-9]+`)
)

// PyStrip is str.strip().
func PyStrip(s string) string {
	return strings.TrimFunc(s, func(r rune) bool { return unicode.IsSpace(r) || (r >= 0x1c && r <= 0x1f) })
}

func prettifySkillName(name, repo string) string {
	head, _, _ := strings.Cut(name, "--")
	if head == name && repo != "" {
		slug := strings.ToLower(nonAlnumI.ReplaceAllString(repo, "-"))
		if slug != "" && strings.HasSuffix(strings.ToLower(head), "-"+slug) {
			head = head[:len(head)-len(slug)-1]
		}
	}
	return PyStrip(dashes.ReplaceAllString(head, " "))
}

// SkillCategory is skill_category: the closed-set category of a source one.
func SkillCategory(raw string) string {
	if c, ok := skillCategories()[strings.ToLower(PyStrip(raw))]; ok {
		return c
	}
	return "other"
}

func skillCategories() map[string]string {
	m := map[string]string{"marketing": "marketing", "gaming": "gaming"}
	add := func(to string, from ...string) {
		for _, f := range from {
			m[f] = to
		}
	}
	add("development", "development", "development-tools", "engineering", "programming-languages", "language",
		"framework", "bash", "string", "core", "foundation", "extended", "applied", "github-integration", "github-skills")
	add("testing", "testing", "quality", "performance", "testing-methodologies", "specialized-testing", "test")
	add("devops", "devops", "platform", "system", "local-ai-infrastructure")
	add("data", "data", "analysis", "analysis-methods", "research-analysis", "story-analysis", "forensics")
	add("agents", "agent", "agents", "agent-coordination", "orchestration", "context-management", "ai-llm", "ai-ml",
		"generation", "artifact-generation", "skills", "meta", "adb-meta-automation")
	add("design", "design", "creative")
	add("documents", "documents", "document-processing", "docs", "writing")
	add("security", "security", "security-compliance", "security-operations", "war-room")
	add("product", "product", "planning", "project", "business", "business-monetization", "c-level")
	add("productivity", "productivity", "workflow", "personal-development", "utility", "travel")
	add("integration", "integration", "api", "messaging", "communication", "technical-integration", "wix-extensions")
	return m
}

func connectionTitle(name string, spec Mapping) string {
	raw := AsMapping(field(spec, "raw_spec"))
	if t := Text(field(raw, "title")); t != "" {
		return t
	}
	if t := Text(field(spec, "title")); t != "" {
		return t
	}
	server := Text(field(raw, "name"))
	if server == "" {
		server = name
	}
	tail := server
	if i := strings.LastIndex(server, "/"); i >= 0 {
		tail = server[i+1:]
	}
	if t := PyStrip(dashes.ReplaceAllString(tail, " ")); t != "" {
		return t
	}
	return server
}

func category(registryType string, spec Mapping, tags []any) string {
	switch registryType {
	case TypeBundles:
		return Text(field(AsMapping(field(spec, "metadata")), "category"))
	case TypeAgents:
		if len(tags) > 0 {
			return Text(tags[0])
		}
	case TypeSkills:
		if src := tagValue(tags, "category:"); src != "" {
			return SkillCategory(src)
		}
	case TypeMCPServers:
		return Text(field(CatalogMetadata(spec), "agentarea:category"))
	}
	return ""
}

func title(registryType, name string, spec Mapping, tags []any) string {
	switch registryType {
	case TypeBundles:
		if t := Text(field(spec, "display_name")); t != "" {
			return t
		}
		if t := Text(field(spec, "name")); t != "" {
			return t
		}
		return name
	case TypeSkills:
		if t := Text(field(spec, "display_name")); t != "" {
			return t
		}
		original := Text(field(spec, "original_name"))
		var t string
		if original != "" {
			t = prettifySkillName(original, "")
		} else {
			t = prettifySkillName(name, tagValue(tags, "repo:"))
		}
		if t != "" {
			return t
		}
		return name
	case TypeMCPServers:
		return connectionTitle(name, spec)
	}
	return name
}

func protocol(registryType string, spec Mapping) string {
	if registryType != TypeMCPServers {
		return ""
	}
	if s, ok := field(spec, "connection_type").(string); ok && s == "openapi" {
		return "api"
	}
	return "mcp"
}

func truthy(v any) bool {
	switch t := v.(type) {
	case nil:
		return false
	case bool:
		return t
	case string:
		return t != ""
	case []any:
		return len(t) > 0
	case Mapping:
		return len(t) > 0
	}
	return true
}

func hosting(registryType string, spec Mapping) string {
	if protocol(registryType, spec) != "mcp" {
		return ""
	}
	ct, _ := field(spec, "connection_type").(string)
	switch ct {
	case "command", "docker":
		return "agentarea"
	case "url":
		return "vendor"
	}
	if Text(field(spec, "url")) != "" || Text(field(spec, "remote_url")) != "" {
		return "vendor"
	}
	if truthy(field(spec, "cmd")) || Text(field(spec, "docker_image_url")) != "" || Text(field(spec, "image")) != "" {
		return "agentarea"
	}
	return ""
}

// CatalogMetadata is catalog_metadata: raw_spec.metadata of a connection.
func CatalogMetadata(spec Mapping) Mapping {
	return AsMapping(field(AsMapping(field(spec, "raw_spec")), "metadata"))
}

// DeclaredCosts is declared_costs: the default cost, then each tool's.
func DeclaredCosts(metadata Mapping) []any {
	cost := AsMapping(field(metadata, "agentarea:cost"))
	out := []any{field(cost, "default")}
	for _, v := range AsMapping(field(cost, "tools")) {
		out = append(out, v)
	}
	return out
}

// ErrMalformedPayers is connector_payers' ToolCostError.
type ErrMalformedPayers struct{ Raw any }

func (e ErrMalformedPayers) Error() string { return "malformed payers" }

// ConnectorPayers is connector_payers: the payers a connector allows.
func ConnectorPayers(raw any) ([]string, error) {
	if raw == nil {
		return []string{"workspace"}, nil
	}
	arr, ok := raw.([]any)
	if !ok || len(arr) == 0 {
		return nil, ErrMalformedPayers{Raw: raw}
	}
	out := make([]string, len(arr))
	for i, v := range arr {
		s, isStr := v.(string)
		if !isStr || (s != "workspace" && s != "platform" && s != "per_call") {
			return nil, ErrMalformedPayers{Raw: raw}
		}
		out[i] = s
	}
	return out, nil
}

func pricing(registryType string, spec Mapping) (string, error) {
	if registryType != TypeMCPServers {
		return "", nil
	}
	metadata := CatalogMetadata(spec)
	costly := false
	for _, d := range DeclaredCosts(metadata) {
		switch Text(field(AsMapping(d), "source")) {
		case "rate", "reported", "settled":
			costly = true
		}
	}
	if !costly {
		return "free", nil
	}
	payers, err := ConnectorPayers(field(metadata, "agentarea:payers"))
	if err != nil {
		return "", err
	}
	for _, p := range payers {
		if p == "platform" {
			return "paid", nil
		}
	}
	return "own_key", nil
}

// Casefold is str.casefold for the letters it folds beyond lower().
func Casefold(s string) string {
	var b strings.Builder
	for _, r := range s {
		switch r {
		case 'ß', 'ẞ':
			b.WriteString("ss")
		case 'ς':
			b.WriteRune('σ')
		case 'ﬁ':
			b.WriteString("fi")
		case 'ﬂ':
			b.WriteString("fl")
		case 'ﬀ':
			b.WriteString("ff")
		case 'ſ':
			b.WriteRune('s')
		case 'µ':
			b.WriteRune('μ')
		default:
			b.WriteRune(unicode.ToLower(r))
		}
	}
	return b.String()
}

// Truncate is s[:n] over code points.
func Truncate(s string, n int) string {
	i := 0
	for pos := range s {
		if i == n {
			return s[:pos]
		}
		i++
	}
	return s
}

// DeriveFacets is derive_facets. A malformed payers list leaves pricing
// NULL and is reported for the caller to log.
func DeriveFacets(registryType, name string, spec any, tags any) (Facets, error) {
	m := AsMapping(spec)
	tagList, _ := tags.([]any)
	f := Facets{
		Category: category(registryType, m, tagList),
		SortKey:  Truncate(Casefold(title(registryType, name, m, tagList)), 255),
		Protocol: protocol(registryType, m),
		Hosting:  hosting(registryType, m),
	}
	for _, t := range tagList {
		if s, ok := t.(string); ok && s == "featured" {
			f.Featured = true
		}
	}
	var err error
	f.Pricing, err = pricing(registryType, m)
	return f, err
}
