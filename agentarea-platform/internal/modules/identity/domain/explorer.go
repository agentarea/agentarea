package domain

import (
	"fmt"
	"strings"
	"unicode"
	"unicode/utf8"
)

// Node kinds of the access explorer and their palettes (access_control.py _COLORS).
const (
	KindAgent      = "agent"
	KindCollection = "collection"
	KindMCP        = "mcp"
	KindSkill      = "skill"
)

func palette(kind string) []string {
	switch kind {
	case KindAgent:
		return []string{"#6366f1", "#8b5cf6", "#a855f7", "#7c3aed", "#4f46e5"}
	case KindCollection:
		return []string{"#0ea5e9", "#06b6d4", "#0891b2", "#0284c7", "#22d3ee"}
	case KindMCP:
		return []string{"#10b981", "#14b8a6", "#059669", "#16a34a", "#34d399"}
	case KindSkill:
		return []string{"#f59e0b", "#f97316", "#fbbf24", "#ea580c", "#fb923c"}
	}
	return nil
}

// Color is _color: the kind's palette indexed by enumeration order.
func Color(kind string, index int) string {
	p := palette(kind)
	return p[index%len(p)]
}

// Namespaces the explorer accepts from the UI, each checked against the
// workspace's own table.
const (
	NamespaceAgent           = "Agent"
	NamespaceMCPServer       = "MCPServer"
	NamespaceSkill           = "Skill"
	NamespaceSkillCollection = "SkillCollection"
)

// ReadableNamespace reports whether ns is one of the four.
func ReadableNamespace(ns string) bool {
	switch ns {
	case NamespaceAgent, NamespaceMCPServer, NamespaceSkill, NamespaceSkillCollection:
		return true
	}
	return false
}

// GrantLabel is _GRANT_LABEL; ok is false for any other relation.
func GrantLabel(relation string) (string, bool) {
	switch relation {
	case "reader":
		return "user", true
	case "writer":
		return "editor", true
	case "manager":
		return "owner", true
	}
	return "", false
}

// GrantRank is _GRANT_RANK.
func GrantRank(relation string) int {
	switch relation {
	case "reader":
		return 1
	case "writer":
		return 2
	case "manager":
		return 3
	}
	return 0
}

// VerbByKind is _VERB_BY_KIND.
func VerbByKind(kind string) string {
	switch kind {
	case KindSkill, KindCollection:
		return "use"
	case KindMCP:
		return "connect"
	case KindAgent:
		return "operate"
	}
	return ""
}

// NamespaceOfKind is the resolve route's kind to namespace table.
func NamespaceOfKind(kind string) string {
	switch kind {
	case KindSkill:
		return NamespaceSkill
	case KindCollection:
		return NamespaceSkillCollection
	case KindMCP:
		return NamespaceMCPServer
	case KindAgent:
		return NamespaceAgent
	}
	return ""
}

// VerbToBit is _VERB_TO_BIT.get(verb, verb).
func VerbToBit(verb string) string {
	switch verb {
	case "use", "view", "read", "operate", "connect":
		return "can_read"
	case "execute":
		return "can_invoke"
	case "configure", "edit", "write":
		return "can_write"
	case "manage", "own", "delete":
		return "can_manage"
	}
	return verb
}

// CheckableBit reports whether bit is one of the four the check route asks.
func CheckableBit(bit string) bool {
	switch bit {
	case "can_read", "can_write", "can_manage", "can_invoke":
		return true
	}
	return false
}

// LegacyRelationToGrant is _LEGACY_RELATION_TO_GRANT.
func LegacyRelationToGrant(relation string) (string, bool) {
	switch relation {
	case "viewers", "connectors", "reader":
		return "reader", true
	case "editors", "writer":
		return "writer", true
	case "owners", "operators", "manager":
		return "manager", true
	}
	return "", false
}

// PyRepr is repr() of a str: single quotes unless the text holds a single
// quote and no double quote, backslash escapes for the quote, backslash and
// the non-printable characters.
func PyRepr(s string) string {
	quote := byte('\'')
	if strings.Contains(s, "'") && !strings.Contains(s, `"`) {
		quote = '"'
	}
	var b strings.Builder
	b.WriteByte(quote)
	for i := 0; i < len(s); {
		r, size := utf8.DecodeRuneInString(s[i:])
		if r == utf8.RuneError && size == 1 {
			fmt.Fprintf(&b, `\udc%02x`, s[i])
			i++
			continue
		}
		i += size
		switch {
		case r == rune(quote) || r == '\\':
			b.WriteByte('\\')
			b.WriteRune(r)
		case r == '\t':
			b.WriteString(`\t`)
		case r == '\n':
			b.WriteString(`\n`)
		case r == '\r':
			b.WriteString(`\r`)
		case r < 0x20 || r == 0x7f:
			fmt.Fprintf(&b, `\x%02x`, r)
		case r < 0x7f:
			b.WriteRune(r)
		case pyPrintable(r):
			b.WriteRune(r)
		case r <= 0xff:
			fmt.Fprintf(&b, `\x%02x`, r)
		case r <= 0xffff:
			fmt.Fprintf(&b, `\u%04x`, r)
		default:
			fmt.Fprintf(&b, `\U%08x`, r)
		}
	}
	b.WriteByte(quote)
	return b.String()
}

// pyPrintable is str.isprintable for one non-ASCII character: everything but
// the separator and other categories, the space included.
func pyPrintable(r rune) bool {
	if r == ' ' {
		return true
	}
	return !unicode.In(r, unicode.Z, unicode.C)
}
