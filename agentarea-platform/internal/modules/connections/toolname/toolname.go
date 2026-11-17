// Package toolname names the tools an aggregated MCP endpoint and the policy
// engine see: model-facing names and the canonical targets rules match.
package toolname

import (
	"crypto/sha1" //nolint:gosec // a stable name digest, not a security boundary
	"encoding/hex"
	"regexp"
	"strings"
	"unicode"

	"golang.org/x/text/unicode/norm"
)

// NSSep joins a connection's namespace and a tool's name on an aggregated endpoint.
const NSSep = "__"

// MaxToolNameLength is the provider limit on a model-facing tool name.
const MaxToolNameLength = 64

var (
	invalidToolChars = regexp.MustCompile(`[^a-zA-Z0-9_-]`)
	notSlug          = regexp.MustCompile(`[^a-z0-9]+`)
)

const (
	cyrillicLetters = "абвгдеёжзийклмнопрстуфхцчшщъыьэюяіїєґў"
	cyrillicSounds  = "a b v g d e e zh z i y k l m n o p r s t u f h ts ch sh sch - y - e yu ya i yi ye g u"
)

// cyrillicLatin is r's Latin spelling when r is a lower-case Cyrillic letter.
func cyrillicLatin(r rune) (string, bool) {
	i := 0
	for _, l := range cyrillicLetters {
		if l == r {
			s := strings.Fields(cyrillicSounds)[i]
			if s == "-" {
				return "", true
			}
			return s, true
		}
		i++
	}
	return "", false
}

func isASCII(s string) bool {
	for i := 0; i < len(s); i++ {
		if s[i] >= 0x80 {
			return false
		}
	}
	return true
}

// SanitizeToolName replaces what a function name may not hold with
// underscores (openapi_tool._slugify_name, mcp_tool_identity._sanitize).
func SanitizeToolName(name string) string { return invalidToolChars.ReplaceAllString(name, "_") }

// ASCIISlug is ascii_slug: Cyrillic transliterated, accents dropped, [a-z0-9_].
func ASCIISlug(name string) string {
	var b strings.Builder
	for _, r := range strings.ToLower(name) {
		if l, ok := cyrillicLatin(r); ok {
			b.WriteString(l)
			continue
		}
		b.WriteRune(r)
	}
	var folded strings.Builder
	for _, r := range norm.NFKD.String(b.String()) {
		if r < 0x80 && !unicode.Is(unicode.Mn, r) {
			folded.WriteRune(r)
		}
	}
	return strings.Trim(notSlug.ReplaceAllString(folded.String(), "_"), "_")
}

// ServerLabel is server_label: the server segment of a model-facing tool name.
func ServerLabel(instanceName string) string {
	name := strings.ToLower(strings.TrimSpace(instanceName))
	var out string
	if isASCII(name) {
		out = SanitizeToolName(name)
	} else {
		out = ASCIISlug(name)
	}
	if out == "" {
		return "server"
	}
	return out
}

// QualifyMCPToolName is qualify_mcp_tool_name: mcp__<label>__<raw>, shortened
// with a stable digest past the provider limit.
func QualifyMCPToolName(label, raw string) string {
	name := strings.Join([]string{"mcp", ServerLabel(label), SanitizeToolName(raw)}, NSSep)
	if len(name) <= MaxToolNameLength {
		return name
	}
	sum := sha1.Sum([]byte(label + "\x00" + raw)) //nolint:gosec // see import
	digest := hex.EncodeToString(sum[:])[:8]
	return name[:MaxToolNameLength-len(digest)-1] + "_" + digest
}

// MCPToolTarget is mcp_tool_target: how a policy rule names one tool of one server.
func MCPToolTarget(serverRef, raw string) string { return "mcp:" + serverRef + ":" + raw }

// MCPNarrowingNames is mcp_tool_narrowing_names: names that may deny a tool
// or hold it for approval, never allow it.
func MCPNarrowingNames(instanceName, raw string) []string {
	var names []string
	if instanceName != "" {
		names = append(names, MCPToolTarget(instanceName, raw), QualifyMCPToolName(instanceName, raw))
	}
	return append(names, raw)
}

// OpenAPIToolTarget is openapi_tool_target: the id-qualified name of one operation.
func OpenAPIToolTarget(connectionID, tool string) string {
	return "openapi:" + connectionID + ":" + tool
}

// AggregateNamespace is MCPAggregatorProxy._get_namespace: the link's prefix,
// else the instance name (ASCII: lowered, spaces and hyphens to underscores;
// otherwise its server label), else the id's first eight characters.
func AggregateNamespace(prefix *string, instanceID, instanceName string) string {
	if prefix != nil && *prefix != "" {
		return *prefix
	}
	if instanceName != "" && !isASCII(instanceName) {
		return ServerLabel(instanceName)
	}
	if instanceName != "" {
		return strings.NewReplacer(" ", "_", "-", "_").Replace(strings.ToLower(instanceName))
	}
	if len(instanceID) > 8 {
		return instanceID[:8]
	}
	return instanceID
}
