package domain

import (
	"fmt"
	"strconv"
	"strings"
	"unicode"
	"unicode/utf8"
)

// pySyntaxError is a SyntaxError as ast.parse reports it: CPython's message and line.
type pySyntaxError struct {
	Msg  string
	Line int
}

func (e *pySyntaxError) Error() string { return fmt.Sprintf("%s (line %d)", e.Msg, e.Line) }

type pyTokKind int

const (
	tokName pyTokKind = iota
	tokNumber
	tokString
	tokOp
	tokNewline
	tokIndent
	tokDedent
)

// pyStrPart is a piece of a string literal: literal text, or an f-string expression's source.
type pyStrPart struct {
	text string
	expr bool
}

type pyTok struct {
	kind  pyTokKind
	text  string
	line  int
	depth int
	// For strings: the decoded parts, whether bytes, whether an f-string.
	parts  []pyStrPart
	bytes  bool
	fstr   bool
	indent int
}

type pyLexer struct {
	src    []rune
	pos    int
	line   int
	toks   []pyTok
	opens  []pyTok
	indent []int
}

func isIdentStart(r rune) bool { return r == '_' || unicode.IsLetter(r) }
func isIdentPart(r rune) bool  { return r == '_' || unicode.IsLetter(r) || unicode.IsDigit(r) }

func validStringPrefix(p string) (raw, byt, f, ok bool) {
	switch strings.ToLower(p) {
	case "":
		return false, false, false, true
	case "r":
		return true, false, false, true
	case "u":
		return false, false, false, true
	case "b":
		return false, true, false, true
	case "f":
		return false, false, true, true
	case "rb", "br":
		return true, true, false, true
	case "rf", "fr":
		return true, false, true, true
	}
	return false, false, false, false
}

// tokenizePython tokenizes code as CPython's tokenizer does, as far as the processor check needs:
// names, strings (decoded, f-strings split), operators, logical lines and indentation.
func tokenizePython(code string) ([]pyTok, error) {
	code = strings.ReplaceAll(strings.ReplaceAll(code, "\r\n", "\n"), "\r", "\n")
	lx := &pyLexer{src: []rune(code), line: 1, indent: []int{0}}
	if err := lx.run(); err != nil {
		return nil, err
	}
	return lx.toks, nil
}

func (lx *pyLexer) peek(off int) rune {
	if lx.pos+off < len(lx.src) {
		return lx.src[lx.pos+off]
	}
	return 0
}

func (lx *pyLexer) emit(t pyTok) {
	t.depth = len(lx.opens)
	lx.toks = append(lx.toks, t)
}

func (lx *pyLexer) lastLine() int {
	n := strings.Count(strings.TrimRight(string(lx.src), "\n"), "\n") + 1
	return n
}

// blockAfter names the statement a ':' line opens, as "expected an indented block after ..." does.
func blockAfter(toks []pyTok) string {
	for i, t := range toks {
		if t.kind != tokName {
			continue
		}
		switch t.text {
		case "def":
			return "function definition"
		case "class":
			return "class definition"
		case "async":
			if i+1 < len(toks) && toks[i+1].text == "def" {
				return "function definition"
			}
			if i+1 < len(toks) {
				return "'" + toks[i+1].text + "' statement"
			}
		case "if", "elif", "else", "for", "while", "with", "try", "except", "finally", "match", "case":
			return "'" + t.text + "' statement"
		}
		if t.text != "@" {
			return ""
		}
	}
	return ""
}

func (lx *pyLexer) currentLine() []pyTok {
	start := len(lx.toks)
	for start > 0 {
		k := lx.toks[start-1].kind
		if k == tokNewline || k == tokIndent || k == tokDedent {
			break
		}
		start--
	}
	return lx.toks[start:]
}

func (lx *pyLexer) run() error {
	atLineStart := true
	needIndent := 0
	needIndentWhat := ""
	for {
		if atLineStart && len(lx.opens) == 0 {
			col := 0
			for lx.pos < len(lx.src) {
				switch lx.src[lx.pos] {
				case ' ':
					col++
				case '\t':
					col = (col/8 + 1) * 8
				case '\f':
					col = 0
				default:
					goto measured
				}
				lx.pos++
			}
		measured:
			r := lx.peek(0)
			if r == '\n' {
				lx.pos++
				lx.line++
				continue
			}
			if r == '#' {
				for lx.pos < len(lx.src) && lx.src[lx.pos] != '\n' {
					lx.pos++
				}
				continue
			}
			if r == '\\' && lx.peek(1) == '\n' {
				lx.pos += 2
				lx.line++
				continue
			}
			if lx.pos >= len(lx.src) {
				if needIndent > 0 {
					return &pySyntaxError{Msg: fmt.Sprintf("expected an indented block after %s on line %d", needIndentWhat, needIndent), Line: lx.lastLine()}
				}
				for len(lx.indent) > 1 {
					lx.indent = lx.indent[:len(lx.indent)-1]
					lx.emit(pyTok{kind: tokDedent, line: lx.line})
				}
				return nil
			}
			top := lx.indent[len(lx.indent)-1]
			switch {
			case col > top:
				if needIndent == 0 {
					return &pySyntaxError{Msg: "unexpected indent", Line: lx.line}
				}
				lx.indent = append(lx.indent, col)
				lx.emit(pyTok{kind: tokIndent, line: lx.line, indent: col})
			case needIndent > 0:
				return &pySyntaxError{Msg: fmt.Sprintf("expected an indented block after %s on line %d", needIndentWhat, needIndent), Line: lx.line}
			case col < top:
				for col < lx.indent[len(lx.indent)-1] {
					lx.indent = lx.indent[:len(lx.indent)-1]
					lx.emit(pyTok{kind: tokDedent, line: lx.line})
				}
				if col != lx.indent[len(lx.indent)-1] {
					return &pySyntaxError{Msg: "unindent does not match any outer indentation level", Line: lx.line}
				}
			}
			needIndent = 0
			atLineStart = false
		}
		if lx.pos >= len(lx.src) {
			if len(lx.opens) > 0 {
				o := lx.opens[len(lx.opens)-1]
				return &pySyntaxError{Msg: fmt.Sprintf("'%s' was never closed", o.text), Line: o.line}
			}
			lx.endLogicalLine(&needIndent, &needIndentWhat)
			atLineStart = true
			continue
		}
		r := lx.src[lx.pos]
		switch {
		case r == '\n':
			lx.pos++
			if len(lx.opens) == 0 {
				lx.endLogicalLine(&needIndent, &needIndentWhat)
				atLineStart = true
			}
			lx.line++
		case r == ' ' || r == '\t' || r == '\f':
			lx.pos++
		case r == '#':
			for lx.pos < len(lx.src) && lx.src[lx.pos] != '\n' {
				lx.pos++
			}
		case r == '\\':
			if lx.peek(1) != '\n' {
				return &pySyntaxError{Msg: "unexpected character after line continuation character", Line: lx.line}
			}
			lx.pos += 2
			lx.line++
		case r == '"' || r == '\'':
			if err := lx.lexString("", lx.line); err != nil {
				return err
			}
		case isIdentStart(r):
			start := lx.pos
			for lx.pos < len(lx.src) && isIdentPart(lx.src[lx.pos]) {
				lx.pos++
			}
			word := string(lx.src[start:lx.pos])
			if q := lx.peek(0); q == '"' || q == '\'' {
				if _, _, _, ok := validStringPrefix(word); ok {
					if err := lx.lexString(word, lx.line); err != nil {
						return err
					}
					continue
				}
			}
			lx.emit(pyTok{kind: tokName, text: word, line: lx.line})
		case unicode.IsDigit(r) || (r == '.' && unicode.IsDigit(lx.peek(1))):
			lx.lexNumber()
		default:
			if err := lx.lexOp(); err != nil {
				return err
			}
		}
	}
}

func (lx *pyLexer) endLogicalLine(needIndent *int, what *string) {
	line := lx.currentLine()
	if len(line) == 0 {
		return
	}
	last := line[len(line)-1]
	if last.kind == tokOp && last.text == ":" {
		if w := blockAfter(line); w != "" {
			*needIndent = line[0].line
			*what = w
		}
	}
	lx.emit(pyTok{kind: tokNewline, line: lx.line})
}

func (lx *pyLexer) lexNumber() {
	start := lx.pos
	hex := lx.peek(0) == '0' && strings.ContainsRune("xXoObB", lx.peek(1))
	for lx.pos < len(lx.src) {
		r := lx.src[lx.pos]
		if r == '_' || r == '.' || unicode.IsLetter(r) || unicode.IsDigit(r) {
			lx.pos++
			if !hex && (r == 'e' || r == 'E') && (lx.peek(0) == '+' || lx.peek(0) == '-') && unicode.IsDigit(lx.peek(1)) {
				lx.pos++
			}
			continue
		}
		break
	}
	lx.emit(pyTok{kind: tokNumber, text: string(lx.src[start:lx.pos]), line: lx.line})
}

func (lx *pyLexer) lexOp() error {
	three := []string{"**=", "//=", ">>=", "<<=", "..."}
	two := []string{"->", ":=", "==", "!=", "<=", ">=", "**", "//", "<<", ">>", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "@="}
	rest := string(lx.src[lx.pos:min(lx.pos+3, len(lx.src))])
	for _, group := range [][]string{three, two} {
		for _, op := range group {
			if strings.HasPrefix(rest, op) {
				lx.pos += len(op)
				lx.emit(pyTok{kind: tokOp, text: op, line: lx.line})
				return nil
			}
		}
	}
	r := lx.src[lx.pos]
	lx.pos++
	op := string(r)
	switch r {
	case '(', '[', '{':
		t := pyTok{kind: tokOp, text: op, line: lx.line}
		lx.emit(t)
		lx.opens = append(lx.opens, t)
		return nil
	case ')', ']', '}':
		if len(lx.opens) == 0 {
			return &pySyntaxError{Msg: fmt.Sprintf("unmatched '%s'", op), Line: lx.line}
		}
		o := lx.opens[len(lx.opens)-1]
		if map[string]string{"(": ")", "[": "]", "{": "}"}[o.text] != op {
			if o.line != lx.line {
				return &pySyntaxError{Msg: fmt.Sprintf("closing parenthesis '%s' does not match opening parenthesis '%s' on line %d", op, o.text, o.line), Line: lx.line}
			}
			return &pySyntaxError{Msg: fmt.Sprintf("closing parenthesis '%s' does not match opening parenthesis '%s'", op, o.text), Line: lx.line}
		}
		lx.opens = lx.opens[:len(lx.opens)-1]
		lx.emit(pyTok{kind: tokOp, text: op, line: lx.line})
		return nil
	}
	if strings.ContainsRune(":,;.+-*/%&|^~<>=@!", r) {
		lx.emit(pyTok{kind: tokOp, text: op, line: lx.line})
		return nil
	}
	return &pySyntaxError{Msg: "invalid syntax", Line: lx.line}
}

// lexString reads one string literal whose quote is at lx.pos.
func (lx *pyLexer) lexString(prefix string, startLine int) error {
	raw, byt, f, _ := validStringPrefix(prefix)
	q := lx.src[lx.pos]
	triple := lx.peek(1) == q && lx.peek(2) == q
	if triple {
		lx.pos += 3
	} else {
		lx.pos++
	}
	body, err := lx.scanBody(q, triple, f, startLine)
	if err != nil {
		return err
	}
	t := pyTok{kind: tokString, text: prefix, line: startLine, bytes: byt, fstr: f}
	if f {
		t.parts = splitFString(body, raw)
	} else {
		t.parts = []pyStrPart{{text: decodeEscapes(body, raw)}}
	}
	lx.emit(t)
	return nil
}

// scanBody returns the literal's source between its quotes and moves past the closing quote.
func (lx *pyLexer) scanBody(q rune, triple, f bool, startLine int) (string, error) {
	var b strings.Builder
	depth := 0
	for {
		if lx.pos >= len(lx.src) {
			if triple {
				at := lx.line
				if len(lx.src) > 0 && lx.src[len(lx.src)-1] == '\n' {
					at--
				}
				return "", &pySyntaxError{Msg: fmt.Sprintf("unterminated triple-quoted string literal (detected at line %d)", at), Line: startLine}
			}
			return "", &pySyntaxError{Msg: fmt.Sprintf("unterminated string literal (detected at line %d)", lx.line), Line: startLine}
		}
		r := lx.src[lx.pos]
		if f && depth > 0 && (r == '"' || r == '\'') {
			inner := lx.peek(1) == r && lx.peek(2) == r
			n := 1
			if inner {
				n = 3
			}
			b.WriteString(strings.Repeat(string(r), n))
			lx.pos += n
			s, err := lx.scanBody(r, inner, false, lx.line)
			if err != nil {
				return "", err
			}
			b.WriteString(s)
			b.WriteString(strings.Repeat(string(r), n))
			continue
		}
		switch {
		case r == '\\':
			b.WriteRune(r)
			lx.pos++
			if lx.pos < len(lx.src) {
				if lx.src[lx.pos] == '\n' {
					lx.line++
				}
				b.WriteRune(lx.src[lx.pos])
				lx.pos++
			}
			continue
		case r == '\n':
			if !triple && depth == 0 {
				return "", &pySyntaxError{Msg: fmt.Sprintf("unterminated string literal (detected at line %d)", lx.line), Line: startLine}
			}
			lx.line++
		case r == q && (!triple || (lx.peek(1) == q && lx.peek(2) == q)):
			if f && depth > 0 {
				return "", &pySyntaxError{Msg: "f-string: expecting '}'", Line: startLine}
			}
			if triple {
				lx.pos += 3
			} else {
				lx.pos++
			}
			return b.String(), nil
		case f && r == '{':
			if depth == 0 && lx.peek(1) == '{' {
				b.WriteString("{{")
				lx.pos += 2
				continue
			}
			depth++
		case f && r == '}':
			if depth == 0 && lx.peek(1) == '}' {
				b.WriteString("}}")
				lx.pos += 2
				continue
			}
			if depth > 0 {
				depth--
			}
		}
		b.WriteRune(r)
		lx.pos++
	}
}

// splitFString splits an f-string's body into literal pieces and expression sources;
// a format spec's literal text is a literal piece, as the AST holds it.
func splitFString(body string, raw bool) []pyStrPart {
	var parts []pyStrPart
	var lit strings.Builder
	rs := []rune(body)
	flush := func() {
		if lit.Len() > 0 {
			parts = append(parts, pyStrPart{text: decodeEscapes(lit.String(), raw)})
			lit.Reset()
		}
	}
	for i := 0; i < len(rs); i++ {
		r := rs[i]
		if r == '{' && i+1 < len(rs) && rs[i+1] == '{' {
			lit.WriteRune('{')
			i++
			continue
		}
		if r == '}' && i+1 < len(rs) && rs[i+1] == '}' {
			lit.WriteRune('}')
			i++
			continue
		}
		if r == '\\' && !raw && i+1 < len(rs) {
			lit.WriteRune(r)
			lit.WriteRune(rs[i+1])
			i++
			continue
		}
		if r != '{' {
			lit.WriteRune(r)
			continue
		}
		flush()
		depth, j := 1, i+1
		var expr strings.Builder
		var quote rune
		for ; j < len(rs) && depth > 0; j++ {
			c := rs[j]
			switch {
			case quote != 0:
				if c == quote {
					quote = 0
				}
			case c == '"' || c == '\'':
				quote = c
			case c == '{' || c == '(' || c == '[':
				depth++
			case c == '}' || c == ')' || c == ']':
				depth--
				if depth == 0 {
					continue
				}
			case c == ':' && depth == 1:
				parts = append(parts, pyStrPart{text: expr.String(), expr: true})
				expr.Reset()
				spec, end := fSpec(rs, j+1)
				parts = append(parts, splitFString(spec, raw)...)
				j = end
				depth = 0
				continue
			}
			if depth > 0 {
				expr.WriteRune(c)
			}
		}
		if expr.Len() > 0 {
			parts = append(parts, pyStrPart{text: expr.String(), expr: true})
		}
		i = j - 1
	}
	flush()
	return parts
}

// fSpec is a format spec's source from i up to its closing '}', and the index past it.
func fSpec(rs []rune, i int) (string, int) {
	depth := 0
	for j := i; j < len(rs); j++ {
		switch rs[j] {
		case '{':
			depth++
		case '}':
			if depth == 0 {
				return string(rs[i:j]), j + 1
			}
			depth--
		}
	}
	return string(rs[i:]), len(rs)
}

// decodeEscapes is a str literal's value: Python's escapes resolved unless raw.
func decodeEscapes(s string, raw bool) string {
	if raw || !strings.ContainsRune(s, '\\') {
		return s
	}
	var b strings.Builder
	for i := 0; i < len(s); {
		c := s[i]
		if c != '\\' || i+1 >= len(s) {
			b.WriteByte(c)
			i++
			continue
		}
		n := s[i+1]
		switch n {
		case '\n':
			i += 2
		case '\\', '\'', '"':
			b.WriteByte(n)
			i += 2
		case 'a':
			b.WriteByte('\a')
			i += 2
		case 'b':
			b.WriteByte('\b')
			i += 2
		case 'f':
			b.WriteByte('\f')
			i += 2
		case 'n':
			b.WriteByte('\n')
			i += 2
		case 'r':
			b.WriteByte('\r')
			i += 2
		case 't':
			b.WriteByte('\t')
			i += 2
		case 'v':
			b.WriteByte('\v')
			i += 2
		case 'x', 'u', 'U':
			width := map[byte]int{'x': 2, 'u': 4, 'U': 8}[n]
			if i+2+width <= len(s) {
				if v, err := strconv.ParseUint(s[i+2:i+2+width], 16, 32); err == nil && utf8.ValidRune(rune(v)) {
					b.WriteRune(rune(v))
					i += 2 + width
					continue
				}
			}
			b.WriteString(s[i : i+2])
			i += 2
		default:
			if n >= '0' && n <= '7' {
				j := i + 1
				for j < len(s) && j < i+4 && s[j] >= '0' && s[j] <= '7' {
					j++
				}
				v, _ := strconv.ParseUint(s[i+1:j], 8, 32)
				b.WriteRune(rune(v))
				i = j
				continue
			}
			b.WriteString(s[i : i+2])
			i += 2
		}
	}
	return b.String()
}
