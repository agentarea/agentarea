// Command tableowner enforces decision 3a: every table named in
// internal/modules/<m>/store/queries/*.sql is owned by <m>. A foreign table is
// read through its owner's api package. The owner map is owners.csv (copied
// from the migration research, runs-surface and runs-loop folded into runs;
// owner "kernel" or "enterprise" means no module may name the table).
//
//	go run ./tools/tableowner -owners tools/tableowner/owners.csv internal/modules
package main

import (
	"encoding/csv"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

func main() {
	owners := flag.String("owners", "tools/tableowner/owners.csv", "table,owner map")
	flag.Parse()
	root := "internal/modules"
	if flag.NArg() > 0 {
		root = flag.Arg(0)
	}
	problems, files, err := check(*owners, root)
	if err != nil {
		fmt.Fprintln(os.Stderr, "tableowner:", err)
		os.Exit(1)
	}
	if len(problems) > 0 {
		for _, p := range problems {
			fmt.Fprintln(os.Stderr, p)
		}
		os.Exit(1)
	}
	fmt.Printf("tableowner: %d query files, every table owned by its module\n", files)
}

func check(ownersPath, root string) (problems []string, files int, err error) {
	f, err := os.Open(ownersPath)
	if err != nil {
		return nil, 0, err
	}
	defer func() { _ = f.Close() }()
	owners, err := readOwners(f)
	if err != nil {
		return nil, 0, fmt.Errorf("%s: %w", ownersPath, err)
	}
	var paths []string
	for _, pattern := range []string{
		filepath.Join(root, "*", "store", "queries", "*.sql"),
		filepath.Join(root, "*", "*", "store", "queries", "*.sql"),
	} {
		found, err := filepath.Glob(pattern)
		if err != nil {
			return nil, 0, err
		}
		paths = append(paths, found...)
	}
	sort.Strings(paths)
	for _, path := range paths {
		rel, err := filepath.Rel(root, path)
		if err != nil {
			return nil, 0, err
		}
		module := strings.Split(filepath.ToSlash(rel), "/")[0]
		src, err := os.ReadFile(path)
		if err != nil {
			return nil, 0, err
		}
		for _, table := range Tables(string(src)) {
			owner, known := owners[table]
			switch {
			case !known:
				problems = append(problems, fmt.Sprintf("%s: table %q is not in %s", path, table, ownersPath))
			case owner != module:
				problems = append(problems, fmt.Sprintf("%s: table %q is owned by %s, not %s; read it through %s's api", path, table, owner, module, owner))
			}
		}
	}
	return problems, len(paths), nil
}

func readOwners(r io.Reader) (map[string]string, error) {
	rows, err := csv.NewReader(r).ReadAll()
	if err != nil {
		return nil, err
	}
	if len(rows) == 0 || len(rows[0]) != 2 || rows[0][0] != "table" || rows[0][1] != "owner" {
		return nil, errors.New("header must be table,owner")
	}
	owners := make(map[string]string, len(rows)-1)
	for _, row := range rows[1:] {
		if _, dup := owners[row[0]]; dup {
			return nil, fmt.Errorf("table %q listed twice", row[0])
		}
		owners[row[0]] = row[1]
	}
	return owners, nil
}

// Tables returns the tables a SQL file names after FROM, JOIN, INTO, UPDATE,
// USING and TABLE, schema-qualified when written so ("public." dropped),
// lowercased, without CTE names, functions or system catalogs, sorted and
// unique.
func Tables(sql string) []string {
	toks := tokenize(sql)
	ctes := map[string]bool{}
	for i := 0; i+2 < len(toks); i++ {
		if toks[i].ident && toks[i+1].is("as") && toks[i+2].text == "(" && i > 0 &&
			(toks[i-1].is("with") || toks[i-1].is("recursive") || toks[i-1].text == ",") {
			ctes[toks[i].name()] = true
		}
	}
	found := map[string]bool{}
	var parens []string
	for i := 0; i < len(toks); i++ {
		t := toks[i]
		switch t.text {
		case "(":
			fn := ""
			if i > 0 && toks[i-1].ident {
				fn = toks[i-1].name()
			}
			parens = append(parens, fn)
			continue
		case ")":
			if len(parens) > 0 {
				parens = parens[:len(parens)-1]
			}
			continue
		}
		if !t.ident || !startsTableRef(toks, i, parens) {
			continue
		}
		for j := i + 1; j < len(toks); {
			if toks[j].is("only") || toks[j].is("lateral") {
				j++
				continue
			}
			callable := t.is("from") || t.is("join") || t.is("using")
			if !toks[j].ident || keyword(toks[j]) || (callable && j+1 < len(toks) && toks[j+1].text == "(") {
				break
			}
			name := toks[j].name()
			if !ctes[name] && !system(name) {
				found[strings.TrimPrefix(name, "public.")] = true
			}
			if !t.is("from") {
				break
			}
			j++
			if j < len(toks) && toks[j].is("as") {
				j++
			}
			if j < len(toks) && toks[j].ident && !keyword(toks[j]) {
				j++
			}
			if j >= len(toks) || toks[j].text != "," {
				break
			}
			j++
		}
	}
	out := make([]string, 0, len(found))
	for n := range found {
		out = append(out, n)
	}
	sort.Strings(out)
	return out
}

func startsTableRef(toks []token, i int, parens []string) bool {
	t := toks[i]
	prev := func(words ...string) bool {
		if i == 0 {
			return false
		}
		for _, w := range words {
			if toks[i-1].is(w) {
				return true
			}
		}
		return false
	}
	switch {
	case t.is("from"):
		if prev("distinct") {
			return false
		}
		if len(parens) > 0 {
			switch parens[len(parens)-1] {
			case "extract", "substring", "trim", "overlay", "position":
				return false
			}
		}
		return true
	case t.is("join"), t.is("into"), t.is("table"):
		return true
	case t.is("using"):
		return i+1 < len(toks) && toks[i+1].text != "("
	case t.is("update"):
		return !prev("for", "key", "do")
	}
	return false
}

func system(name string) bool {
	return strings.HasPrefix(name, "pg_") || strings.HasPrefix(name, "pg_catalog.") ||
		strings.HasPrefix(name, "information_schema.")
}

func keyword(t token) bool {
	switch t.name() {
	case "where", "join", "left", "right", "inner", "outer", "full", "cross", "on", "using",
		"group", "order", "limit", "offset", "for", "union", "except", "intersect", "returning",
		"set", "natural", "lateral", "window", "having", "values", "select", "do":
		return !t.quoted
	}
	return false
}

type token struct {
	text   string
	ident  bool
	quoted bool
}

func (t token) is(word string) bool { return t.ident && !t.quoted && t.name() == word }

func (t token) name() string {
	if t.quoted {
		return t.text
	}
	return strings.ToLower(t.text)
}

// tokenize drops comments and string literals and returns identifiers
// (dotted names joined, double quotes removed) and punctuation.
func tokenize(s string) []token {
	var out []token
	for i := 0; i < len(s); {
		c := s[i]
		switch {
		case c == '-' && strings.HasPrefix(s[i:], "--"):
			for i < len(s) && s[i] != '\n' {
				i++
			}
		case c == '/' && strings.HasPrefix(s[i:], "/*"):
			end := strings.Index(s[i+2:], "*/")
			if end < 0 {
				return out
			}
			i += end + 4
		case c == '\'':
			i++
			for i < len(s) {
				if s[i] == '\'' {
					if i+1 < len(s) && s[i+1] == '\'' {
						i += 2
						continue
					}
					break
				}
				i++
			}
			i++
		case c == '$' && dollarTag(s[i:]) != "":
			tag := dollarTag(s[i:])
			end := strings.Index(s[i+len(tag):], tag)
			if end < 0 {
				return out
			}
			i += len(tag) + end + len(tag)
		case isIdentStart(c) || c == '"':
			name, quoted, n := readName(s[i:])
			out = append(out, token{text: name, ident: true, quoted: quoted})
			i += n
		case c == '(' || c == ')' || c == ',':
			out = append(out, token{text: string(c)})
			i++
		case c == ' ' || c == '\t' || c == '\n' || c == '\r':
			i++
		default:
			out = append(out, token{text: string(c)})
			i++
		}
	}
	return out
}

// readName reads a possibly dotted, possibly quoted name.
func readName(s string) (name string, quoted bool, n int) {
	var parts []string
	for {
		if n < len(s) && s[n] == '"' {
			end := strings.IndexByte(s[n+1:], '"')
			if end < 0 {
				end = len(s) - n - 1
			}
			parts = append(parts, s[n+1:n+1+end])
			quoted = true
			n += end + 2
		} else {
			start := n
			for n < len(s) && isIdentPart(s[n]) {
				n++
			}
			parts = append(parts, strings.ToLower(s[start:n]))
		}
		if n+1 < len(s) && s[n] == '.' && (isIdentStart(s[n+1]) || s[n+1] == '"') {
			n++
			continue
		}
		return strings.Join(parts, "."), quoted, n
	}
}

func dollarTag(s string) string {
	end := strings.IndexByte(s[1:], '$')
	if end < 0 {
		return ""
	}
	tag := s[:end+2]
	for i := 1; i < len(tag)-1; i++ {
		if !isIdentPart(tag[i]) {
			return ""
		}
	}
	return tag
}

func isIdentStart(c byte) bool { return c == '_' || c == '@' || (c|0x20 >= 'a' && c|0x20 <= 'z') }

func isIdentPart(c byte) bool { return isIdentStart(c) || (c >= '0' && c <= '9') || c == '$' }
