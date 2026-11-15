package domain

import (
	"errors"
	"fmt"
	"strings"
	"unicode"
	"unicode/utf16"
)

// MaxCodeBytes is the largest processor code (MAX_CODE_BYTES).
const MaxCodeBytes = 64 * 1024

// CheckProcessorCode is check_code: refuse code that cannot run as a processor, or that holds a
// secret. The code is read by a Python tokenizer, not CPython's parser: a syntax error the
// tokenizer cannot see (an incomplete expression) surfaces when the processor runs.
func CheckProcessorCode(code string) error {
	if strings.TrimFunc(code, pyIsSpace) == "" {
		return Fail(ErrProcessorCode, "The processor's code is empty")
	}
	if size := len(code); size > MaxCodeBytes {
		return Fail(ErrProcessorCode, fmt.Sprintf("The code is %d bytes; a processor holds %d", size, MaxCodeBytes))
	}
	toks, err := tokenizePython(code)
	if err == nil {
		err = checkStringGroups(toks)
	}
	var syn *pySyntaxError
	if errors.As(err, &syn) {
		return Fail(ErrProcessorCode, fmt.Sprintf("The code does not parse: %s (line %d)", syn.Msg, syn.Line))
	}
	if err != nil {
		return err
	}
	if !definesProcess(toks) {
		return Fail(ErrProcessorCode, "The code must define a top-level def process(event) returning a list of events or None")
	}
	if line, ok := secretLine(toks); ok {
		return Fail(ErrProcessorCode, fmt.Sprintf("Line %d holds what looks like a secret. A processor gets no secrets, "+
			"and its code is shown to everyone who reads the stream", line))
	}
	return nil
}

func pyIsSpace(r rune) bool { return unicode.IsSpace(r) || (r >= 0x1c && r <= 0x1f) }

func pyKeyword(s string) bool {
	switch s {
	case "False", "None", "True", "and", "as", "assert", "async", "await", "break", "class", "continue", "def",
		"del", "elif", "else", "except", "finally", "for", "from", "global", "if", "import", "in", "is", "lambda",
		"nonlocal", "not", "or", "pass", "raise", "return", "try", "while", "with", "yield":
		return true
	}
	return false
}

// checkStringGroups refuses adjacent literals that mix bytes and str, as the parser does.
func checkStringGroups(toks []pyTok) error {
	for i := 0; i < len(toks); {
		if toks[i].kind != tokString {
			i++
			continue
		}
		j, byt, str := i, false, false
		for ; j < len(toks) && toks[j].kind == tokString; j++ {
			if toks[j].bytes {
				byt = true
			} else {
				str = true
			}
		}
		if byt && str {
			return &pySyntaxError{Msg: "cannot mix bytes and nonbytes literals", Line: toks[i].line}
		}
		i = j
	}
	return nil
}

// levelChange is how a layout token moves the block level; ok false for any other token.
func levelChange(k pyTokKind) (int, bool) {
	switch k {
	case tokIndent:
		return 1, true
	case tokDedent:
		return -1, true
	case tokNewline:
		return 0, true
	case tokName, tokNumber, tokString, tokOp:
	}
	return 0, false
}

// definesProcess is _defines_process: the first top-level def process takes a positional argument.
func definesProcess(toks []pyTok) bool {
	level := 0
	lineStart := true
	for i, t := range toks {
		if d, ok := levelChange(t.kind); ok {
			level += d
			lineStart = true
			continue
		}
		if !lineStart {
			continue
		}
		lineStart = false
		if level != 0 || t.kind != tokName || t.text != "def" || i+3 >= len(toks) {
			continue
		}
		if toks[i+1].text != "process" || toks[i+2].text != "(" {
			continue
		}
		first := toks[i+3]
		switch {
		case first.kind == tokName:
			return true
		case first.text == "*":
			return i+4 < len(toks) && toks[i+4].kind == tokName
		default:
			return false
		}
	}
	return false
}

// strGroup is a run of adjacent string tokens: one Constant, or one JoinedStr.
type strGroup struct {
	start, end int
	line       int
	plain      bool
	bytes      bool
	value      string
}

func groupAt(toks []pyTok, i int) strGroup {
	g := strGroup{start: i, line: toks[i].line, plain: true}
	var b strings.Builder
	j := i
	for ; j < len(toks) && toks[j].kind == tokString; j++ {
		if toks[j].bytes {
			g.bytes = true
		}
		if toks[j].fstr {
			g.plain = false
		}
		for _, p := range toks[j].parts {
			b.WriteString(p.text)
		}
	}
	g.end = j
	g.value = b.String()
	return g
}

// strConst is the str value of an expression that is one str Constant: adjacent plain
// literals, in any number of parentheses.
func strConst(toks []pyTok) (string, bool) {
	for len(toks) >= 2 && toks[0].text == "(" && toks[0].kind == tokOp && toks[len(toks)-1].text == ")" &&
		closes(toks, 0) == len(toks)-1 {
		toks = toks[1 : len(toks)-1]
	}
	if len(toks) == 0 || toks[0].kind != tokString {
		return "", false
	}
	g := groupAt(toks, 0)
	if g.end != len(toks) || !g.plain || g.bytes {
		return "", false
	}
	return g.value, true
}

// closes is the index of the bracket closing the one at i.
func closes(toks []pyTok, i int) int {
	d := toks[i].depth
	for j := i + 1; j < len(toks); j++ {
		if toks[j].kind == tokOp && toks[j].depth == d && strings.Contains(")]}", toks[j].text) {
			return j
		}
	}
	return -1
}

// pyJSON is json.dumps of a str (ensure_ascii).
func pyJSON(s string) string {
	var b strings.Builder
	b.WriteByte('"')
	for _, r := range s {
		switch r {
		case '"':
			b.WriteString(`\"`)
		case '\\':
			b.WriteString(`\\`)
		case '\n':
			b.WriteString(`\n`)
		case '\r':
			b.WriteString(`\r`)
		case '\t':
			b.WriteString(`\t`)
		case '\b':
			b.WriteString(`\b`)
		case '\f':
			b.WriteString(`\f`)
		default:
			switch {
			case r < 0x20 || (r >= 0x7f && r < 0x10000):
				fmt.Fprintf(&b, `\u%04x`, r)
			case r >= 0x10000:
				hi, lo := utf16.EncodeRune(r)
				fmt.Fprintf(&b, `\u%04x\u%04x`, hi, lo)
			default:
				b.WriteRune(r)
			}
		}
	}
	b.WriteByte('"')
	return b.String()
}

// secretAssignment is _secret_assignment: a non-empty str written under a secret-shaped name.
func secretAssignment(name, value string) bool {
	if value == "" {
		return false
	}
	written := pyJSON(name) + ": " + pyJSON(value)
	return MaskInlineSecrets(written) != written
}

type secretScan struct {
	line  int
	found bool
}

func (s *secretScan) at(line int) {
	if !s.found || line < s.line {
		s.line, s.found = line, true
	}
}

// secretLine is _secret_line: a str Constant holding a secret shape, or a secret-shaped name
// bound to a str Constant (assignment, keyword, dict entry, a def's default). Python reports the
// first node of ast.walk; this reports the lowest line.
func secretLine(toks []pyTok) (int, bool) {
	var s secretScan
	scanConstants(toks, 0, &s)
	for _, line := range logicalLines(toks) {
		scanStatements(line, &s)
	}
	scanBrackets(toks, &s)
	return s.line, s.found
}

func scanConstants(toks []pyTok, lineOffset int, s *secretScan) {
	for i := 0; i < len(toks); {
		if toks[i].kind != tokString {
			i++
			continue
		}
		g := groupAt(toks, i)
		line := g.line + lineOffset
		if !g.bytes {
			var lit strings.Builder
			check := func() {
				if lit.Len() > 0 && MaskInlineSecrets(lit.String()) != lit.String() {
					s.at(line)
				}
				lit.Reset()
			}
			for _, t := range toks[g.start:g.end] {
				for _, p := range t.parts {
					if !p.expr {
						lit.WriteString(p.text)
						continue
					}
					check()
					if inner, err := tokenizePython(p.text); err == nil {
						scanConstants(inner, line-1, s)
					}
				}
			}
			check()
		}
		i = g.end
	}
}

func logicalLines(toks []pyTok) [][]pyTok {
	var out [][]pyTok
	start := 0
	for i, t := range toks {
		if t.kind == tokNewline || t.kind == tokIndent || t.kind == tokDedent {
			if i > start {
				out = append(out, toks[start:i])
			}
			start = i + 1
		}
	}
	if start < len(toks) {
		out = append(out, toks[start:])
	}
	return out
}

func splitAt(toks []pyTok, depth int, sep string) [][]pyTok {
	var out [][]pyTok
	start := 0
	for i, t := range toks {
		if t.kind == tokOp && t.depth == depth && t.text == sep {
			out = append(out, toks[start:i])
			start = i + 1
		}
	}
	return append(out, toks[start:])
}

func compoundHeader(t pyTok) bool {
	if t.kind != tokName {
		return false
	}
	switch t.text {
	case "if", "elif", "else", "while", "for", "with", "try", "except", "finally", "def", "class", "async", "match", "case":
		return true
	}
	return false
}

// scanStatements finds Assign and AnnAssign of a str Constant to a name.
func scanStatements(line []pyTok, s *secretScan) {
	for _, seg := range splitAt(line, 0, ";") {
		for len(seg) > 0 && compoundHeader(seg[0]) {
			colon := -1
			for i, t := range seg {
				if t.kind == tokOp && t.depth == 0 && t.text == ":" {
					colon = i
					break
				}
			}
			if colon < 0 {
				seg = nil
				break
			}
			seg = seg[colon+1:]
		}
		if len(seg) == 0 {
			continue
		}
		parts := splitAt(seg, 0, "=")
		if len(parts) < 2 {
			continue
		}
		value, ok := strConst(parts[len(parts)-1])
		if !ok {
			continue
		}
		for i, target := range parts[:len(parts)-1] {
			name := ""
			switch {
			case len(target) == 1 && target[0].kind == tokName && !pyKeyword(target[0].text):
				name = target[0].text
			case i == 0 && len(parts) == 2 && len(target) >= 3 && target[0].kind == tokName && !pyKeyword(target[0].text) &&
				target[1].kind == tokOp && target[1].text == ":":
				name = target[0].text
			}
			if name != "" && secretAssignment(name, value) {
				s.at(seg[0].line)
			}
		}
	}
}

// scanBrackets finds keywords and a def's defaults inside parentheses, and dict entries.
func scanBrackets(toks []pyTok, s *secretScan) {
	for i, t := range toks {
		if t.kind != tokOp || (t.text != "(" && t.text != "{") {
			continue
		}
		end := closes(toks, i)
		if end < 0 {
			continue
		}
		items := splitAt(toks[i+1:end], t.depth+1, ",")
		if t.text == "{" {
			scanDict(items, t, s)
			continue
		}
		defLine := 0
		if i >= 2 && toks[i-1].kind == tokName && toks[i-2].kind == tokName && toks[i-2].text == "def" {
			if i >= 3 && toks[i-3].kind == tokName && toks[i-3].text == "async" && toks[i-3].line == toks[i-2].line {
				continue
			}
			defLine = toks[i-2].line
		}
		for _, item := range items {
			if len(item) < 3 || item[0].kind != tokName || pyKeyword(item[0].text) {
				continue
			}
			eq := -1
			for k, x := range item {
				if x.kind == tokOp && x.depth == t.depth+1 && x.text == "=" {
					eq = k
					break
				}
			}
			if eq < 0 || (defLine == 0 && eq != 1) {
				continue
			}
			value, ok := strConst(item[eq+1:])
			if !ok || !secretAssignment(item[0].text, value) {
				continue
			}
			if defLine != 0 {
				s.at(defLine)
			} else {
				s.at(item[0].line)
			}
		}
	}
}

func scanDict(items [][]pyTok, open pyTok, s *secretScan) {
	for _, item := range items {
		for _, x := range item {
			if x.kind == tokName && x.text == "for" && x.depth == open.depth+1 {
				return
			}
		}
	}
	for _, item := range items {
		colon := -1
		for k, x := range item {
			if x.kind == tokOp && x.depth == open.depth+1 && x.text == ":" {
				colon = k
				break
			}
		}
		if colon < 0 {
			continue
		}
		key, ok := strConst(item[:colon])
		if !ok {
			continue
		}
		if value, ok := strConst(item[colon+1:]); ok && secretAssignment(key, value) {
			s.at(open.line)
		}
	}
}
