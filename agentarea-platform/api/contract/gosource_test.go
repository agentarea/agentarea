package contract_test

import (
	"go/ast"
	"go/parser"
	"go/token"
	"io/fs"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"testing"
)

// goSource is what the module's non-test Go source under app/ and internal/
// declares, read without building it.
type goSource struct {
	// components are lifecycle component names: the first argument of
	// lifecycle.Loop, lifecycle.Func and of every function passing its first
	// parameter on to one of them, and the name of a *Component literal. A
	// part built at run time reads "*".
	components map[string]bool
	// envelopes are the event types passed to events.NewEnvelope.
	envelopes map[string]bool
}

type goFile struct {
	dir, pkg string
	f        *ast.File
}

func scanGo(t *testing.T) goSource {
	t.Helper()
	fset := token.NewFileSet()
	var files []goFile
	for _, top := range []string{"app", "internal"} {
		err := filepath.WalkDir(filepath.Join("..", "..", top), func(path string, d fs.DirEntry, err error) error {
			if err != nil {
				return err
			}
			if d.IsDir() {
				if d.Name() == "testdata" {
					return filepath.SkipDir
				}
				return nil
			}
			name := d.Name()
			if !strings.HasSuffix(name, ".go") || strings.HasSuffix(name, "_test.go") || strings.HasSuffix(name, "_archviolation.go") {
				return nil
			}
			f, err := parser.ParseFile(fset, path, nil, parser.SkipObjectResolution)
			if err != nil {
				return err
			}
			files = append(files, goFile{dir: filepath.Dir(path), pkg: f.Name.Name, f: f})
			return nil
		})
		if err != nil {
			t.Fatal(err)
		}
	}
	wrappers := componentWrappers(files)
	consts, constsByName := stringConsts(files)
	src := goSource{components: map[string]bool{}, envelopes: map[string]bool{}}
	for _, gf := range files {
		ast.Inspect(gf.f, func(n ast.Node) bool {
			switch n := n.(type) {
			case *ast.CallExpr:
				key := calleeKey(gf.pkg, n.Fun)
				if len(n.Args) == 0 {
					return true
				}
				if wrappers[key] {
					if name, ok := nameOf(n.Args[0]); ok {
						src.components[name] = true
					}
				}
				if key == "events.NewEnvelope" {
					for _, v := range resolveString(n.Args[0], consts[gf.dir], constsByName) {
						src.envelopes[v] = true
					}
				}
			case *ast.CompositeLit:
				if v := componentLitName(n); v != nil {
					if name, ok := nameOf(v); ok {
						src.components[name] = true
					}
				}
			}
			return true
		})
	}
	return src
}

// componentWrappers are lifecycle.Loop, lifecycle.Func and the functions
// that pass their first parameter on as a component's name, by "pkg.Func".
func componentWrappers(files []goFile) map[string]bool {
	wrappers := map[string]bool{"lifecycle.Loop": true, "lifecycle.Func": true}
	for changed := true; changed; {
		changed = false
		for _, gf := range files {
			for _, d := range gf.f.Decls {
				fn, ok := d.(*ast.FuncDecl)
				if !ok || fn.Recv != nil || fn.Body == nil || len(fn.Type.Params.List) == 0 || len(fn.Type.Params.List[0].Names) == 0 {
					continue
				}
				key := gf.pkg + "." + fn.Name.Name
				if wrappers[key] {
					continue
				}
				param := fn.Type.Params.List[0].Names[0].Name
				forwards := false
				ast.Inspect(fn.Body, func(n ast.Node) bool {
					switch n := n.(type) {
					case *ast.CallExpr:
						if wrappers[calleeKey(gf.pkg, n.Fun)] && len(n.Args) > 0 && isIdent(n.Args[0], param) {
							forwards = true
						}
					case *ast.CompositeLit:
						if v := componentLitName(n); v != nil && isIdent(v, param) {
							forwards = true
						}
					}
					return !forwards
				})
				if forwards {
					wrappers[key] = true
					changed = true
				}
			}
		}
	}
	return wrappers
}

func calleeKey(pkg string, fun ast.Expr) string {
	switch f := fun.(type) {
	case *ast.Ident:
		return pkg + "." + f.Name
	case *ast.SelectorExpr:
		if x, ok := f.X.(*ast.Ident); ok {
			return x.Name + "." + f.Sel.Name
		}
	}
	return ""
}

func isIdent(e ast.Expr, name string) bool {
	id, ok := e.(*ast.Ident)
	return ok && id.Name == name
}

// componentLitName is the name field of a literal of a type named *Component.
func componentLitName(c *ast.CompositeLit) ast.Expr {
	typ, ok := c.Type.(*ast.Ident)
	if !ok || !strings.HasSuffix(typ.Name, "Component") {
		return nil
	}
	for _, el := range c.Elts {
		if kv, ok := el.(*ast.KeyValueExpr); ok && isIdent(kv.Key, "name") {
			return kv.Value
		}
	}
	return nil
}

// nameOf reads a component name: a string literal, a literal followed by a
// run-time part, or an fmt.Sprintf format; run-time parts read "*".
func nameOf(e ast.Expr) (string, bool) {
	switch e := e.(type) {
	case *ast.BasicLit:
		if e.Kind != token.STRING {
			return "", false
		}
		s, err := strconv.Unquote(e.Value)
		return s, err == nil
	case *ast.BinaryExpr:
		if e.Op != token.ADD {
			return "", false
		}
		left, ok := nameOf(e.X)
		if !ok {
			return "", false
		}
		if right, ok := nameOf(e.Y); ok {
			return left + right, true
		}
		return left + "*", true
	case *ast.CallExpr:
		if calleeKey("", e.Fun) == "fmt.Sprintf" && len(e.Args) > 0 {
			if format, ok := nameOf(e.Args[0]); ok {
				return regexp.MustCompile(`%[-+# 0-9.]*[a-zA-Z]`).ReplaceAllString(format, "*"), true
			}
		}
	}
	return "", false
}

// stringConsts are the string constants of each package directory, and of
// all of them by name.
func stringConsts(files []goFile) (map[string]map[string]string, map[string][]string) {
	byDir := map[string]map[string]string{}
	byName := map[string][]string{}
	for _, gf := range files {
		for _, d := range gf.f.Decls {
			gd, ok := d.(*ast.GenDecl)
			if !ok || gd.Tok != token.CONST {
				continue
			}
			for _, s := range gd.Specs {
				vs, ok := s.(*ast.ValueSpec)
				if !ok || len(vs.Names) != len(vs.Values) {
					continue
				}
				for i, n := range vs.Names {
					v, ok := nameOf(vs.Values[i])
					if !ok || strings.Contains(v, "*") {
						continue
					}
					if byDir[gf.dir] == nil {
						byDir[gf.dir] = map[string]string{}
					}
					byDir[gf.dir][n.Name] = v
					byName[n.Name] = append(byName[n.Name], v)
				}
			}
		}
	}
	return byDir, byName
}

func resolveString(e ast.Expr, local map[string]string, byName map[string][]string) []string {
	switch e := e.(type) {
	case *ast.BasicLit:
		if v, ok := nameOf(e); ok {
			return []string{v}
		}
	case *ast.Ident:
		if v, ok := local[e.Name]; ok {
			return []string{v}
		}
	case *ast.SelectorExpr:
		return byName[e.Sel.Name]
	}
	return nil
}
