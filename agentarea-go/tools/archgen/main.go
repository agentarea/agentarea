// Command archgen prints .golangci.yml with the depguard rules that enforce
// the layering of layout.md section 4, generated from the module table so a
// new module is one line, not a YAML block per module.
//
//	go run ./tools/archgen > .golangci.yml
//
// make archlint-fresh fails when the committed file differs.
//
// Rules: 1 a module imports the kernel, itself and other modules' api only;
// 2 follows from 1 (another module's service or store cannot be imported, so
// it cannot be constructed); 3 the kernel imports no module, a domain package
// imports the standard library and its own module only; 4 SQL only in store/
// and kernel/db, the Temporal SDK only in kernel/durable and
// modules/*/workflows (decision 4), OpenFGA only in kernel/authz, Kubernetes
// only in sandbox/backends; 6 no package-level mutable state, no init.
// Rule 5 (planes) is deferred with the split (decision 2).
package main

import (
	"fmt"
	"os"
	"sort"
	"strings"
)

const mod = "github.com/agentarea/agentarea/agentarea-go"

// modules is the module table. Adding a module is one line here.
func modules() []string {
	return []string{
		"agents", "catalog", "connections", "governance", "identity", "insights",
		"models", "projects", "runs", "sandbox", "streams", "wallet",
	}
}

// schemaPaths hold the migration set and its checker, which run SQL through
// goose and database/sql by design.
func schemaPaths() []string {
	return []string{"!**/internal/schema/**", "!**/tools/schemacheck/**"}
}

type list struct {
	name  string
	mode  string
	files []string
	allow []string
	deny  map[string]string
}

func p(s string) string { return mod + "/" + s }

func lists() []list {
	all := modules()
	sort.Strings(all)
	var out []list

	out = append(out, list{
		name: "kernel", files: []string{"**/internal/kernel/**"},
		deny: map[string]string{
			p("internal/modules"):  "rule 3: kernel imports no module",
			p("internal/profiles"): "rule 3: kernel imports no profile",
			p("app"):               "kernel imports no composition",
			p("ext"):               "kernel imports no extension surface",
		},
	})

	for _, m := range all {
		allow := []string{p("internal/modules/" + m + "$"), p("internal/modules/" + m + "/")}
		for _, x := range all {
			if x != m {
				allow = append(allow, p("internal/modules/"+x+"/api$"))
			}
		}
		out = append(out,
			list{
				name: "module-" + m, mode: "lax",
				files: []string{"**/internal/modules/" + m + "/**"},
				allow: allow,
				deny: map[string]string{
					p("internal/modules/"): "rule 1: import another module through its api package only; declare the interface you need in service/deps.go and let app pass it in (rule 2)",
					p("internal/profiles"): "modules depend on kernel ports, never on an adapter set",
					p("app"):               "nothing under internal imports app",
					p("ext"):               "modules receive extensions through their Deps",
				},
			},
			list{
				name: "domain-" + m, mode: "strict",
				files: []string{"**/internal/modules/" + m + "/domain/**"},
				allow: []string{"$gostd", p("internal/modules/" + m + "/api$"), p("internal/modules/" + m + "/domain")},
				deny: map[string]string{
					p("internal/kernel"):                    "rule 3: domain imports no kernel package",
					p("internal/modules/" + m + "/service"): "domain is below service",
					p("internal/modules/" + m + "/store"):   "domain is below store",
				},
			})
	}

	out = append(out,
		list{
			name:  "sql-only-in-store",
			files: append([]string{"$all", "!**/store/**", "!**/internal/kernel/db/**"}, schemaPaths()...),
			deny: map[string]string{
				"database/sql":             "rule 4: SQL appears only in a module's store/ and kernel/db",
				"github.com/jackc/pgx":     "rule 4: SQL appears only in a module's store/ and kernel/db",
				"github.com/lib/pq":        "rule 4: use pgx through kernel/db",
				"github.com/pressly/goose": "rule 4: migrations live in internal/schema",
			},
		},
		list{
			name:  "temporal-only-in-workflows",
			files: []string{"$all", "!**/internal/kernel/durable/**", "!**/internal/modules/*/workflows/**"},
			deny:  map[string]string{"go.temporal.io/sdk": "decision 4: the Temporal SDK is imported in kernel/durable and modules/*/workflows only"},
		},
		list{
			name:  "openfga-only-in-authz",
			files: []string{"$all", "!**/internal/kernel/authz/**"},
			deny:  map[string]string{"github.com/openfga/go-sdk": "rule 4: authorization goes through kernel/authz"},
		},
		list{
			name:  "kubernetes-only-in-workload-backends",
			files: []string{"$all", "!**/internal/modules/sandbox/backends/**", "!**/internal/modules/connections/runtime/kube/**", "!**/internal/modules/catalog/operator/**"},
			deny: map[string]string{
				"k8s.io/client-go":               "only the workload backends (sandbox/backends, connections/runtime/kube) and the operator (catalog/operator) talk to Kubernetes",
				"sigs.k8s.io/controller-runtime": "only the workload backends (sandbox/backends, connections/runtime/kube) and the operator (catalog/operator) talk to Kubernetes",
			},
		},
		list{
			name: "exec-supervisor", mode: "strict",
			files: []string{"**/cmd/exec-supervisor/**", "**/internal/modules/sandbox/supervisor/**"},
			allow: []string{"$gostd", "golang.org/x/sys/unix", p("internal/modules/sandbox/supervisor")},
		},
		list{
			name:  "ext-surface",
			files: []string{"**/ext/**"},
			deny:  map[string]string{p("internal/modules"): "ext exposes kernel types by alias, never module internals"},
		},
	)
	return out
}

func render() string {
	w := &strings.Builder{}
	fmt.Fprintln(w, "# Generated by go run ./tools/archgen; do not edit by hand.")
	fmt.Fprintln(w, "# depguard enforces layout.md section 4 rules 1, 3 and 4; rule 2 follows from 1;")
	fmt.Fprintln(w, "# gochecknoglobals and gochecknoinits enforce rule 6. make archlint-proof shows")
	fmt.Fprintln(w, "# each rule catching a deliberate violation (files tagged archviolation).")
	fmt.Fprintln(w, `version: "2"`)
	fmt.Fprintln(w, "linters:")
	fmt.Fprintln(w, "  default: standard")
	fmt.Fprintln(w, "  enable: [depguard, gochecknoglobals, gochecknoinits, errorlint, exhaustive]")
	fmt.Fprintln(w, "  settings:")
	fmt.Fprintln(w, "    depguard:")
	fmt.Fprintln(w, "      rules:")
	for _, l := range lists() {
		fmt.Fprintf(w, "        %s:\n", l.name)
		if l.mode != "" {
			fmt.Fprintf(w, "          list-mode: %s\n", l.mode)
		}
		fmt.Fprintln(w, "          files:")
		for _, f := range l.files {
			fmt.Fprintf(w, "            - %q\n", f)
		}
		if len(l.allow) > 0 {
			fmt.Fprintln(w, "          allow:")
			for _, a := range l.allow {
				fmt.Fprintf(w, "            - %q\n", a)
			}
		}
		if len(l.deny) > 0 {
			keys := make([]string, 0, len(l.deny))
			for k := range l.deny {
				keys = append(keys, k)
			}
			sort.Strings(keys)
			fmt.Fprintln(w, "          deny:")
			for _, k := range keys {
				fmt.Fprintf(w, "            - pkg: %q\n              desc: %q\n", k, l.deny[k])
			}
		}
	}
	fmt.Fprintln(w, "  exclusions:")
	fmt.Fprintln(w, "    rules:")
	fmt.Fprintln(w, "      - path: _test\\.go")
	fmt.Fprintln(w, "        linters: [gochecknoglobals]")
	fmt.Fprintln(w, "issues:")
	fmt.Fprintln(w, "  max-issues-per-linter: 0")
	fmt.Fprintln(w, "  max-same-issues: 0")
	return w.String()
}

func main() {
	if _, err := os.Stdout.WriteString(render()); err != nil {
		os.Exit(1)
	}
}
