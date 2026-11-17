package wirejson

import (
	"bytes"
	"fmt"
	"unicode/utf8"
)

// DecodeError is json.JSONDecodeError: Python's message and the position, in
// characters, where json.loads stopped.
type DecodeError struct {
	Msg string
	Pos int
}

func (e *DecodeError) Error() string { return fmt.Sprintf("%s: char %d", e.Msg, e.Pos) }

// Check reports whether json.loads(body) succeeds, and if not, the error it
// raises. It follows CPython's C scanner (Modules/_json.c): NaN, Infinity and
// lone surrogate escapes are accepted, a leading UTF-8 BOM is skipped as
// json.loads skips it on bytes. ok is false for a body that is not UTF-8
// (FastAPI answers that one 400, not 422).
func Check(body []byte) (decodeErr *DecodeError, ok bool) {
	decodeErr, ok, _ = check(body)
	return decodeErr, ok
}

// ContainsNUL reports whether json.loads(body) succeeds and a string or key
// of the result holds U+0000 (NulCharacterMiddleware's contains_nul); a raw
// NUL fails the parse, so only a \u0000 escape can.
func ContainsNUL(body []byte) bool {
	decodeErr, ok, nul := check(body)
	return ok && decodeErr == nil && nul
}

// maxDepth stands for Python's recursion limit: json.loads fails past it.
const maxDepth = 10000

func check(body []byte) (decodeErr *DecodeError, ok, nul bool) {
	body = bytes.TrimPrefix(body, []byte("\xef\xbb\xbf"))
	if !utf8.Valid(body) {
		return nil, false, false
	}
	s := &scanner{s: []rune(string(body))}
	defer func() {
		if r := recover(); r != nil {
			e, isDecode := r.(*DecodeError)
			if !isDecode {
				panic(r)
			}
			decodeErr, ok, nul = e, true, false
		}
	}()
	idx := s.ws(0)
	end, scanned := s.scanOnce(idx)
	if !scanned {
		return &DecodeError{Msg: "Expecting value", Pos: end}, true, false
	}
	end = s.ws(end)
	if end != len(s.s) {
		return &DecodeError{Msg: "Extra data", Pos: end}, true, false
	}
	return nil, true, s.nul
}

type scanner struct {
	s     []rune
	depth int
	nul   bool
}

func (sc *scanner) enter(idx int) {
	sc.depth++
	if sc.depth > maxDepth {
		sc.fail("maximum recursion depth exceeded", idx)
	}
}

func (sc *scanner) fail(msg string, pos int) { panic(&DecodeError{Msg: msg, Pos: pos}) }

func (sc *scanner) ws(i int) int {
	for i < len(sc.s) {
		switch sc.s[i] {
		case ' ', '\t', '\n', '\r':
			i++
		default:
			return i
		}
	}
	return i
}

func (sc *scanner) has(i int, lit string) bool {
	r := []rune(lit)
	if i+len(r) > len(sc.s) {
		return false
	}
	for j, c := range r {
		if sc.s[i+j] != c {
			return false
		}
	}
	return true
}

// scanOnce scans one value at idx; on a value that does not start there it
// returns (failPos, false), CPython's StopIteration(failPos) that becomes
// "Expecting value" wherever it surfaces.
func (sc *scanner) scanOnce(idx int) (int, bool) {
	if idx >= len(sc.s) {
		return idx, false
	}
	switch sc.s[idx] {
	case '"':
		return sc.str(idx + 1), true
	case '{':
		sc.enter(idx)
		defer func() { sc.depth-- }()
		return sc.object(idx + 1)
	case '[':
		sc.enter(idx)
		defer func() { sc.depth-- }()
		return sc.array(idx + 1)
	case 'n':
		if sc.has(idx, "null") {
			return idx + 4, true
		}
	case 't':
		if sc.has(idx, "true") {
			return idx + 4, true
		}
	case 'f':
		if sc.has(idx, "false") {
			return idx + 5, true
		}
	case 'N':
		if sc.has(idx, "NaN") {
			return idx + 3, true
		}
	case 'I':
		if sc.has(idx, "Infinity") {
			return idx + 8, true
		}
	case '-':
		if sc.has(idx, "-Infinity") {
			return idx + 9, true
		}
	}
	return sc.number(idx)
}

func digit(r rune) bool { return r >= '0' && r <= '9' }

func (sc *scanner) number(start int) (int, bool) {
	idx := start
	last := len(sc.s) - 1
	if sc.s[idx] == '-' {
		idx++
		if idx > last {
			return start, false
		}
	}
	switch c := sc.s[idx]; {
	case c >= '1' && c <= '9':
		idx++
		for idx <= last && digit(sc.s[idx]) {
			idx++
		}
	case c == '0':
		idx++
	default:
		return start, false
	}
	if idx < last && sc.s[idx] == '.' && digit(sc.s[idx+1]) {
		idx += 2
		for idx <= last && digit(sc.s[idx]) {
			idx++
		}
	}
	if idx < last && (sc.s[idx] == 'e' || sc.s[idx] == 'E') {
		eStart := idx
		idx++
		if idx < last && (sc.s[idx] == '-' || sc.s[idx] == '+') {
			idx++
		}
		for idx <= last && digit(sc.s[idx]) {
			idx++
		}
		if !digit(sc.s[idx-1]) {
			idx = eStart
		}
	}
	return idx, true
}

func isHex(r rune) bool {
	return digit(r) || (r >= 'a' && r <= 'f') || (r >= 'A' && r <= 'F')
}

func hexVal(rs []rune) rune {
	var v rune
	for _, r := range rs {
		v <<= 4
		switch {
		case digit(r):
			v |= r - '0'
		case r >= 'a' && r <= 'f':
			v |= r - 'a' + 10
		default:
			v |= r - 'A' + 10
		}
	}
	return v
}

// str scans a string whose opening quote is at begin-1; it returns the
// index after the closing quote.
func (sc *scanner) str(begin int) int {
	n := len(sc.s)
	end := begin
	for {
		next := end
		for ; next < n; next++ {
			c := sc.s[next]
			if c == '"' || c == '\\' {
				break
			}
			if c <= 0x1f {
				sc.fail("Invalid control character at", next)
			}
		}
		if next >= n {
			sc.fail("Unterminated string starting at", begin-1)
		}
		if sc.s[next] == '"' {
			return next + 1
		}
		next++
		if next == n {
			sc.fail("Unterminated string starting at", begin-1)
		}
		c := sc.s[next]
		if c != 'u' {
			end = next + 1
			switch c {
			case '"', '\\', '/', 'b', 'f', 'n', 'r', 't':
			default:
				sc.fail("Invalid \\escape", end-2)
			}
			continue
		}
		next++
		end = next + 4
		if end >= n {
			sc.fail("Invalid \\uXXXX escape", next-1)
		}
		for ; next < end; next++ {
			if !isHex(sc.s[next]) {
				sc.fail("Invalid \\uXXXX escape", end-5)
			}
		}
		cp := hexVal(sc.s[end-4 : end])
		if cp == 0 {
			sc.nul = true
		}
		if cp >= 0xd800 && cp <= 0xdbff && end+6 < n && sc.s[next] == '\\' && sc.s[next+1] == 'u' {
			next += 2
			end += 6
			for ; next < end; next++ {
				if !isHex(sc.s[next]) {
					sc.fail("Invalid \\uXXXX escape", end-5)
				}
			}
			if low := hexVal(sc.s[end-4 : end]); low < 0xdc00 || low > 0xdfff {
				end -= 6
			}
		}
	}
}

func (sc *scanner) object(idx int) (int, bool) {
	last := len(sc.s) - 1
	idx = sc.ws(idx)
	if idx > last || sc.s[idx] != '}' {
		for {
			if idx > last || sc.s[idx] != '"' {
				sc.fail("Expecting property name enclosed in double quotes", idx)
			}
			idx = sc.ws(sc.str(idx + 1))
			if idx > last || sc.s[idx] != ':' {
				sc.fail("Expecting ':' delimiter", idx)
			}
			idx = sc.ws(idx + 1)
			next, ok := sc.scanOnce(idx)
			if !ok {
				return next, false
			}
			idx = sc.ws(next)
			if idx <= last && sc.s[idx] == '}' {
				break
			}
			if idx > last || sc.s[idx] != ',' {
				sc.fail("Expecting ',' delimiter", idx)
			}
			comma := idx
			idx = sc.ws(idx + 1)
			if idx <= last && sc.s[idx] == '}' {
				sc.fail("Illegal trailing comma before end of object", comma)
			}
		}
	}
	return idx + 1, true
}

func (sc *scanner) array(idx int) (int, bool) {
	last := len(sc.s) - 1
	idx = sc.ws(idx)
	if idx > last || sc.s[idx] != ']' {
		for {
			next, ok := sc.scanOnce(idx)
			if !ok {
				return next, false
			}
			idx = sc.ws(next)
			if idx <= last && sc.s[idx] == ']' {
				break
			}
			if idx > last || sc.s[idx] != ',' {
				sc.fail("Expecting ',' delimiter", idx)
			}
			comma := idx
			idx = sc.ws(idx + 1)
			if idx <= last && sc.s[idx] == ']' {
				sc.fail("Illegal trailing comma before end of array", comma)
			}
		}
	}
	return idx + 1, true
}
