package main

import (
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"sort"
	"testing"
)

// Every operation id of the spec is a method of exactly one module's
// StrictServerInterface.
func TestEveryOperationInExactlyOneModule(t *testing.T) {
	doc, err := loadJSON("../../../agentarea-webapp/src/api/openapi.json")
	if err != nil {
		t.Fatal(err)
	}
	owners, err := loadOwners("routes.json")
	if err != nil {
		t.Fatal(err)
	}
	want, err := preprocess(doc, owners)
	if err != nil {
		t.Fatal(err)
	}
	if len(want) < 341 {
		t.Fatalf("spec has %d operations, want at least 341", len(want))
	}

	found := map[string][]string{}
	for _, m := range Modules() {
		for _, name := range strictMethods(t, filepath.Join("../../api/openapi", m)) {
			found[name] = append(found[name], m)
		}
	}
	var problems []string
	for id, mod := range want {
		got := found[camel(id)]
		if len(got) != 1 || got[0] != mod {
			problems = append(problems, id+": want "+mod+", found "+join(got))
		}
		delete(found, camel(id))
	}
	for name, mods := range found {
		problems = append(problems, name+": not in the spec, in "+join(mods))
	}
	sort.Strings(problems)
	for _, p := range problems {
		t.Error(p)
	}
}

func join(s []string) string {
	if len(s) == 0 {
		return "none"
	}
	out := s[0]
	for _, x := range s[1:] {
		out += "," + x
	}
	return out
}

func strictMethods(t *testing.T, dir string) []string {
	t.Helper()
	files, err := filepath.Glob(filepath.Join(dir, "*.go"))
	if err != nil || len(files) == 0 {
		t.Fatalf("no generated code in %s", dir)
	}
	var names []string
	for _, f := range files {
		src, err := os.ReadFile(f)
		if err != nil {
			t.Fatal(err)
		}
		file, err := parser.ParseFile(token.NewFileSet(), f, src, 0)
		if err != nil {
			t.Fatal(err)
		}
		for _, d := range file.Decls {
			gd, ok := d.(*ast.GenDecl)
			if !ok {
				continue
			}
			for _, s := range gd.Specs {
				ts, ok := s.(*ast.TypeSpec)
				if !ok || ts.Name.Name != "StrictServerInterface" {
					continue
				}
				for _, m := range ts.Type.(*ast.InterfaceType).Methods.List {
					for _, n := range m.Names {
						names = append(names, n.Name)
					}
				}
			}
		}
	}
	return names
}
