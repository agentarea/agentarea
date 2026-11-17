package domain

import (
	"regexp"
	"strings"
)

// YAMLMap is a mapping in key order (sort_keys=False).
type YAMLMap []YAMLItem

// YAMLItem is one key of a YAMLMap.
type YAMLItem struct {
	Key   string
	Value any
}

// YAMLInt is an int as Python's str(int) writes it.
type YAMLInt string

// YAMLFloat is a float as Python's repr(float) writes it.
type YAMLFloat string

// YAML values: string, bool, nil, YAMLInt, YAMLFloat, []any, YAMLMap.

var (
	yamlBoolRE  = regexp.MustCompile(`^(?:yes|Yes|YES|no|No|NO|true|True|TRUE|false|False|FALSE|on|On|ON|off|Off|OFF)$`)
	yamlFloatRE = regexp.MustCompile(`^(?:[-+]?(?:[0-9][0-9_]*)\.[0-9_]*(?:[eE][-+][0-9]+)?|\.[0-9][0-9_]*(?:[eE][-+][0-9]+)?|[-+]?[0-9][0-9_]*(?::[0-5]?[0-9])+\.[0-9_]*|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))$`)
	yamlIntRE   = regexp.MustCompile(`^(?:[-+]?0b[0-1_]+|[-+]?0[0-7_]+|[-+]?(?:0|[1-9][0-9_]*)|[-+]?0x[0-9a-fA-F_]+|[-+]?[1-9][0-9_]*(?::[0-5]?[0-9])+)$`)
	yamlNullRE  = regexp.MustCompile(`^(?:~|null|Null|NULL|)$`)
	yamlTimeRE  = regexp.MustCompile(`^(?:[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]|[0-9][0-9][0-9][0-9]-[0-9][0-9]?-[0-9][0-9]?(?:[Tt]|[ \t]+)[0-9][0-9]?:[0-9][0-9]:[0-9][0-9](?:\.[0-9]*)?(?:[ \t]*(?:Z|[-+][0-9][0-9]?(?::[0-9][0-9])?))?)$`)
)

// yamlResolvesPlain is whether a plain scalar with this text would load as
// something other than a string (Resolver's implicit resolvers, by first char).
func yamlResolvesPlain(v string) bool {
	first := byte(0)
	if v != "" {
		first = v[0]
	}
	in := func(set string) bool { return v != "" && strings.IndexByte(set, first) >= 0 }
	switch {
	case in("yYnNtTfFoO") && yamlBoolRE.MatchString(v):
	case in("-+0123456789.") && yamlFloatRE.MatchString(v):
	case in("-+0123456789") && yamlIntRE.MatchString(v):
	case in("<") && v == "<<":
	case (v == "" || in("~nN")) && yamlNullRE.MatchString(v):
	case in("0123456789") && yamlTimeRE.MatchString(v):
	case in("=") && v == "=":
	default:
		return false
	}
	return true
}

// SafeDumpYAML is yaml.safe_dump(v, default_flow_style=False,
// allow_unicode=True, sort_keys=False) for the values above.
func SafeDumpYAML(v any) string {
	e := &yamlEmitter{whitespace: true, indention: true, indent: -1}
	e.node(v, true, false, false, false)
	e.writeIndent()
	return e.out.String()
}

const (
	yamlBestIndent = 2
	yamlBestWidth  = 80
)

type yamlScalar struct {
	value  string
	isText bool
}

type yamlAnalysis struct {
	empty, multiline                                       bool
	allowFlowPlain, allowBlockPlain, allowSingle, allowDbl bool
}

type yamlEmitter struct {
	out        strings.Builder
	indent     int
	indents    []int
	flowLevel  int
	column     int
	whitespace bool
	indention  bool
	simpleKey  bool
}

func (e *yamlEmitter) increaseIndent(flow, indentless bool) {
	e.indents = append(e.indents, e.indent)
	switch {
	case e.indent < 0 && flow:
		e.indent = yamlBestIndent
	case e.indent < 0:
		e.indent = 0
	case !indentless:
		e.indent += yamlBestIndent
	}
}

func (e *yamlEmitter) popIndent() {
	e.indent = e.indents[len(e.indents)-1]
	e.indents = e.indents[:len(e.indents)-1]
}

func yamlScalarOf(v any) (yamlScalar, bool) {
	switch x := v.(type) {
	case string:
		return yamlScalar{value: x, isText: true}, true
	case nil:
		return yamlScalar{value: "null"}, true
	case bool:
		if x {
			return yamlScalar{value: "true"}, true
		}
		return yamlScalar{value: "false"}, true
	case YAMLInt:
		return yamlScalar{value: string(x)}, true
	case YAMLFloat:
		s := strings.ToLower(string(x))
		if !strings.Contains(s, ".") && strings.Contains(s, "e") {
			s = strings.Replace(s, "e", ".0e", 1)
		}
		return yamlScalar{value: s}, true
	}
	return yamlScalar{}, false
}

func (e *yamlEmitter) node(v any, root, sequence, mapping, simpleKey bool) {
	_ = root
	e.simpleKey = simpleKey
	if s, ok := yamlScalarOf(v); ok {
		e.increaseIndent(true, false)
		e.scalar(s)
		e.popIndent()
		return
	}
	switch x := v.(type) {
	case []any:
		if e.flowLevel > 0 || len(x) == 0 {
			e.writeIndicator("[", true, true, false)
			e.writeIndicator("]", false, false, false)
			return
		}
		e.increaseIndent(false, mapping && !e.indention)
		for _, item := range x {
			e.writeIndent()
			e.writeIndicator("-", true, false, true)
			e.node(item, false, true, false, false)
		}
		e.popIndent()
	case YAMLMap:
		if e.flowLevel > 0 || len(x) == 0 {
			e.writeIndicator("{", true, true, false)
			e.writeIndicator("}", false, false, false)
			return
		}
		e.increaseIndent(false, false)
		for _, it := range x {
			e.writeIndent()
			k := yamlScalar{value: it.Key, isText: true}
			if a := yamlAnalyze(k.value); len([]rune(k.value)) < 128 && !a.empty && !a.multiline {
				e.node(it.Key, false, false, true, true)
				e.writeIndicator(":", false, false, false)
			} else {
				e.writeIndicator("?", true, false, true)
				e.node(it.Key, false, false, true, false)
				e.writeIndent()
				e.writeIndicator(":", true, false, true)
			}
			e.node(it.Value, false, false, true, false)
		}
		e.popIndent()
	default:
		panic("yaml: unsupported value")
	}
}

func (e *yamlEmitter) scalar(s yamlScalar) {
	a := yamlAnalyze(s.value)
	implicitPlain := !s.isText || !yamlResolvesPlain(s.value)
	style := byte('"')
	switch {
	case implicitPlain && (!e.simpleKey || (!a.empty && !a.multiline)) &&
		((e.flowLevel > 0 && a.allowFlowPlain) || (e.flowLevel == 0 && a.allowBlockPlain)):
		style = 0
	case a.allowSingle && (!e.simpleKey || !a.multiline):
		style = '\''
	}
	if !s.isText && style != 0 {
		panic("yaml: a non-string scalar needs a tag")
	}
	split := !e.simpleKey
	text := []rune(s.value)
	switch style {
	case '"':
		e.writeDoubleQuoted(text, split)
	case '\'':
		e.writeSingleQuoted(text, split)
	default:
		e.writePlain(text, split)
	}
}

func yamlIsBreak(r rune) bool { return r == '\n' || r == '\x85' || r == ' ' || r == ' ' }

func yamlIsBlankZ(r rune) bool { return r == 0 || r == ' ' || r == '\t' || r == '\r' || yamlIsBreak(r) }

func yamlAnalyze(scalar string) yamlAnalysis {
	text := []rune(scalar)
	if len(text) == 0 {
		return yamlAnalysis{empty: true, allowBlockPlain: true, allowSingle: true, allowDbl: true}
	}
	var blockInd, flowInd, lineBreaks, special bool
	var leadingSpace, leadingBreak, trailingSpace, trailingBreak, breakSpace, spaceBreak bool
	if strings.HasPrefix(scalar, "---") || strings.HasPrefix(scalar, "...") {
		blockInd, flowInd = true, true
	}
	precededByWS := true
	followedByWS := len(text) == 1 || yamlIsBlankZ(text[1])
	prevSpace, prevBreak := false, false
	for i, ch := range text {
		if i == 0 {
			if strings.ContainsRune("#,[]{}&*!|>'\"%@`", ch) {
				flowInd, blockInd = true, true
			}
			if ch == '?' || ch == ':' {
				flowInd = true
				if followedByWS {
					blockInd = true
				}
			}
			if ch == '-' && followedByWS {
				flowInd, blockInd = true, true
			}
		} else {
			if strings.ContainsRune(",?[]{}", ch) {
				flowInd = true
			}
			if ch == ':' {
				flowInd = true
				if followedByWS {
					blockInd = true
				}
			}
			if ch == '#' && precededByWS {
				flowInd, blockInd = true, true
			}
		}
		if yamlIsBreak(ch) {
			lineBreaks = true
		}
		if ch != '\n' && (ch < 0x20 || ch > 0x7E) {
			printable := (ch == 0x85 || (ch >= 0xA0 && ch <= 0xD7FF) || (ch >= 0xE000 && ch <= 0xFFFD) ||
				(ch >= 0x10000 && ch < 0x10FFFF)) && ch != 0xFEFF
			if !printable {
				special = true
			}
		}
		switch {
		case ch == ' ':
			if i == 0 {
				leadingSpace = true
			}
			if i == len(text)-1 {
				trailingSpace = true
			}
			if prevBreak {
				breakSpace = true
			}
			prevSpace, prevBreak = true, false
		case yamlIsBreak(ch):
			if i == 0 {
				leadingBreak = true
			}
			if i == len(text)-1 {
				trailingBreak = true
			}
			if prevSpace {
				spaceBreak = true
			}
			prevSpace, prevBreak = false, true
		default:
			prevSpace, prevBreak = false, false
		}
		precededByWS = yamlIsBlankZ(ch)
		followedByWS = i+2 >= len(text) || yamlIsBlankZ(text[i+2])
	}
	a := yamlAnalysis{multiline: lineBreaks, allowFlowPlain: true, allowBlockPlain: true, allowSingle: true, allowDbl: true}
	if leadingSpace || leadingBreak || trailingSpace || trailingBreak {
		a.allowFlowPlain, a.allowBlockPlain = false, false
	}
	if breakSpace {
		a.allowFlowPlain, a.allowBlockPlain, a.allowSingle = false, false, false
	}
	if spaceBreak || special {
		a.allowFlowPlain, a.allowBlockPlain, a.allowSingle = false, false, false
	}
	if lineBreaks {
		a.allowFlowPlain, a.allowBlockPlain = false, false
	}
	if flowInd {
		a.allowFlowPlain = false
	}
	if blockInd {
		a.allowBlockPlain = false
	}
	return a
}

func (e *yamlEmitter) write(s string) {
	e.out.WriteString(s)
	e.column += len([]rune(s))
}

func (e *yamlEmitter) writeIndicator(ind string, needWhitespace, whitespace, indention bool) {
	data := ind
	if !e.whitespace && needWhitespace {
		data = " " + ind
	}
	e.whitespace = whitespace
	e.indention = e.indention && indention
	e.write(data)
}

func (e *yamlEmitter) writeIndent() {
	indent := max(e.indent, 0)
	if !e.indention || e.column > indent || (e.column == indent && !e.whitespace) {
		e.writeLineBreak("\n")
	}
	if e.column < indent {
		e.whitespace = true
		e.out.WriteString(strings.Repeat(" ", indent-e.column))
		e.column = indent
	}
}

func (e *yamlEmitter) writeLineBreak(data string) {
	e.whitespace = true
	e.indention = true
	e.column = 0
	e.out.WriteString(data)
}

func (e *yamlEmitter) writeBreaks(text []rune) {
	for _, br := range text {
		e.writeLineBreak(string(br))
	}
}

func (e *yamlEmitter) writeSingleQuoted(text []rune, split bool) {
	e.writeIndicator("'", true, false, false)
	spaces, breaks := false, false
	start := 0
	for end := 0; end <= len(text); end++ {
		var ch rune = -1
		if end < len(text) {
			ch = text[end]
		}
		switch {
		case spaces:
			if ch != ' ' {
				if start+1 == end && e.column > yamlBestWidth && split && start != 0 && end != len(text) {
					e.writeIndent()
				} else {
					e.write(string(text[start:end]))
				}
				start = end
			}
		case breaks:
			if ch == -1 || !yamlIsBreak(ch) {
				if text[start] == '\n' {
					e.writeLineBreak("\n")
				}
				e.writeBreaks(text[start:end])
				e.writeIndent()
				start = end
			}
		default:
			if ch == -1 || ch == ' ' || yamlIsBreak(ch) || ch == '\'' {
				if start < end {
					e.write(string(text[start:end]))
					start = end
				}
			}
		}
		if ch == '\'' {
			e.write("''")
			start = end + 1
		}
		if ch != -1 {
			spaces = ch == ' '
			breaks = yamlIsBreak(ch)
		}
	}
	e.writeIndicator("'", false, false, false)
}

func yamlEscape(r rune) (string, bool) {
	switch r {
	case 0:
		return "0", true
	case 0x07:
		return "a", true
	case 0x08:
		return "b", true
	case 0x09:
		return "t", true
	case 0x0A:
		return "n", true
	case 0x0B:
		return "v", true
	case 0x0C:
		return "f", true
	case 0x0D:
		return "r", true
	case 0x1B:
		return "e", true
	case '"':
		return "\"", true
	case '\\':
		return "\\", true
	case 0x85:
		return "N", true
	case 0xA0:
		return "_", true
	case 0x2028:
		return "L", true
	case 0x2029:
		return "P", true
	}
	return "", false
}

func yamlPrintable(ch rune) bool {
	return (ch >= 0x20 && ch <= 0x7E) || (ch >= 0xA0 && ch <= 0xD7FF) || (ch >= 0xE000 && ch <= 0xFFFD)
}

func yamlHex(prefix string, width int, r rune) string {
	const digits = "0123456789ABCDEF"
	b := make([]byte, width)
	for i := width - 1; i >= 0; i-- {
		b[i] = digits[r&0xF]
		r >>= 4
	}
	return prefix + string(b)
}

func (e *yamlEmitter) writeDoubleQuoted(text []rune, split bool) {
	e.writeIndicator("\"", true, false, false)
	start := 0
	for end := 0; end <= len(text); end++ {
		var ch rune = -1
		if end < len(text) {
			ch = text[end]
		}
		if ch == -1 || ch == '"' || ch == '\\' || ch == 0x85 || ch == 0x2028 || ch == 0x2029 || ch == 0xFEFF ||
			!yamlPrintable(ch) {
			if start < end {
				e.write(string(text[start:end]))
				start = end
			}
			if ch != -1 {
				var data string
				switch esc, ok := yamlEscape(ch); {
				case ok:
					data = "\\" + esc
				case ch <= 0xFF:
					data = yamlHex("\\x", 2, ch)
				case ch <= 0xFFFF:
					data = yamlHex("\\u", 4, ch)
				default:
					data = yamlHex("\\U", 8, ch)
				}
				e.write(data)
				start = end + 1
			}
		}
		if end > 0 && end < len(text)-1 && (ch == ' ' || start >= end) && e.column+(end-start) > yamlBestWidth && split {
			data := string(text[start:end]) + "\\"
			if start < end {
				start = end
			}
			e.write(data)
			e.writeIndent()
			e.whitespace = false
			e.indention = false
			if text[start] == ' ' {
				e.write("\\")
			}
		}
	}
	e.writeIndicator("\"", false, false, false)
}

func (e *yamlEmitter) writePlain(text []rune, split bool) {
	if len(text) == 0 {
		return
	}
	if !e.whitespace {
		e.write(" ")
	}
	e.whitespace = false
	e.indention = false
	spaces, breaks := false, false
	start := 0
	for end := 0; end <= len(text); end++ {
		var ch rune = -1
		if end < len(text) {
			ch = text[end]
		}
		switch {
		case spaces:
			if ch != ' ' {
				if start+1 == end && e.column > yamlBestWidth && split {
					e.writeIndent()
					e.whitespace = false
					e.indention = false
				} else {
					e.write(string(text[start:end]))
				}
				start = end
			}
		case breaks:
			if ch == -1 || !yamlIsBreak(ch) {
				if text[start] == '\n' {
					e.writeLineBreak("\n")
				}
				e.writeBreaks(text[start:end])
				e.writeIndent()
				e.whitespace = false
				e.indention = false
				start = end
			}
		default:
			if ch == -1 || ch == ' ' || yamlIsBreak(ch) {
				e.write(string(text[start:end]))
				start = end
			}
		}
		if ch != -1 {
			spaces = ch == ' '
			breaks = yamlIsBreak(ch)
		}
	}
}
