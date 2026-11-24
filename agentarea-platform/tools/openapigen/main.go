// Command openapigen turns the Python-exported spec into one oapi-codegen
// package per module under api/openapi/<module>/ (plan decision 13), and
// copies the spec to api/openapi/openapi.json, which the serve role publishes.
//
//	go run ./tools/openapigen          regenerate
//	go run ./tools/openapigen -check   fail when regenerating would change a file
package main

import (
	"bytes"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
)

const oapiCodegen = "github.com/oapi-codegen/oapi-codegen/v2/cmd/oapi-codegen@v2.8.2"

func main() {
	spec := flag.String("spec", "../agentarea-webapp/src/api/openapi.json", "exported OpenAPI spec")
	routes := flag.String("routes", "tools/openapigen/routes.json", "operation id to router file")
	out := flag.String("out", "api/openapi", "output directory")
	check := flag.Bool("check", false, "compare with a fresh generation instead of writing")
	flag.Parse()
	if err := run(*spec, *routes, *out, *check); err != nil {
		fmt.Fprintln(os.Stderr, "openapigen:", err)
		os.Exit(1)
	}
}

func run(specPath, routesPath, out string, check bool) error {
	doc, err := loadJSON(specPath)
	if err != nil {
		return err
	}
	owners, err := loadOwners(routesPath)
	if err != nil {
		return err
	}
	if _, err := preprocess(doc, owners); err != nil {
		return err
	}
	work, err := os.MkdirTemp("", "openapigen")
	if err != nil {
		return err
	}
	defer func() { _ = os.RemoveAll(work) }()
	dst := out
	if check {
		dst = filepath.Join(work, "out")
	}
	specFile := filepath.Join(work, "spec.json")
	if err := writeJSON(specFile, doc); err != nil {
		return err
	}
	for _, m := range Modules() {
		dir := filepath.Join(dst, m)
		if err := os.MkdirAll(dir, 0o755); err != nil {
			return err
		}
		cfg := fmt.Sprintf("package: %s\noutput: %s\ngenerate:\n  models: true\n  chi-server: true\n  strict-server: true\noutput-options:\n  include-tags: [%s]\n",
			m, filepath.Join(dir, "api.gen.go"), m)
		cfgFile := filepath.Join(work, m+".yaml")
		if err := os.WriteFile(cfgFile, []byte(cfg), 0o644); err != nil {
			return err
		}
		cmd := exec.Command("go", "run", oapiCodegen, "-config", cfgFile, specFile)
		if b, err := cmd.CombinedOutput(); err != nil {
			return fmt.Errorf("oapi-codegen %s: %w\n%s", m, err, b)
		}
	}
	raw, err := os.ReadFile(specPath)
	if err != nil {
		return err
	}
	if err := os.WriteFile(filepath.Join(dst, "openapi.json"), raw, 0o644); err != nil {
		return err
	}
	if !check {
		return nil
	}
	return compare(dst, out)
}

func compare(fresh, committed string) error {
	var bad []string
	for _, m := range Modules() {
		a, errA := os.ReadFile(filepath.Join(fresh, m, "api.gen.go"))
		b, errB := os.ReadFile(filepath.Join(committed, m, "api.gen.go"))
		if errA != nil || errB != nil || !bytes.Equal(a, b) {
			bad = append(bad, m)
		}
	}
	a, errA := os.ReadFile(filepath.Join(fresh, "openapi.json"))
	b, errB := os.ReadFile(filepath.Join(committed, "openapi.json"))
	if errA != nil || errB != nil || !bytes.Equal(a, b) {
		bad = append(bad, "openapi.json")
	}
	sort.Strings(bad)
	if len(bad) > 0 {
		return fmt.Errorf("stale generated code in %v: run go run ./tools/openapigen", bad)
	}
	return nil
}

func loadJSON(path string) (map[string]any, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var doc map[string]any
	if err := json.Unmarshal(b, &doc); err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	return doc, nil
}

func writeJSON(path string, doc map[string]any) error {
	b, err := json.Marshal(doc)
	if err != nil {
		return err
	}
	return os.WriteFile(path, b, 0o644)
}
