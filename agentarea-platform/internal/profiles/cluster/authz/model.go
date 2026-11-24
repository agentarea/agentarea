package authz

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"os"
	"reflect"
	"slices"
	"strings"

	"go.yaml.in/yaml/v3"
)

// packagedModel is the model the platform's checks name:
// model/authorization-model.json, transformed from model/model.fga (see
// model/README.md).
//
//go:embed model/authorization-model.json
var packagedModel []byte

// PackagedModel is the packaged authorization model as JSON values.
func PackagedModel() (map[string]any, error) {
	var m map[string]any
	if err := json.Unmarshal(packagedModel, &m); err != nil {
		return nil, fmt.Errorf("packaged authorization model: %w", err)
	}
	return m, nil
}

// LoadModel reads a model file, YAML or JSON as yaml.safe_load reads it, into
// JSON values.
func LoadModel(path string) (map[string]any, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("authorization model file is not readable: %s", path)
	}
	var doc any
	if err := yaml.Unmarshal(raw, &doc); err != nil {
		return nil, fmt.Errorf("authorization model file %s: %w", path, err)
	}
	if _, ok := doc.(map[string]any); !ok {
		return nil, fmt.Errorf("authorization model file must contain an object: %s", path)
	}
	asJSON, err := json.Marshal(doc)
	if err != nil {
		return nil, fmt.Errorf("authorization model file %s: %w", path, err)
	}
	var m map[string]any
	if err := json.Unmarshal(asJSON, &m); err != nil {
		return nil, fmt.Errorf("authorization model file %s: %w", path, err)
	}
	return m, nil
}

func isEmptyCollection(v any) bool {
	switch x := v.(type) {
	case map[string]any:
		return len(x) == 0
	case []any:
		return len(x) == 0
	}
	return false
}

// normalizeModel is a model as the server stores it: ids, empty collections
// and blank provenance dropped, so a stored model compares equal to the file
// it was written from (openfga_bootstrap.py _normalize_authorization_model).
func normalizeModel(v any) any {
	switch x := v.(type) {
	case map[string]any:
		out := make(map[string]any, len(x))
		for key, raw := range x {
			item := normalizeModel(raw)
			if key == "id" || key == "authorization_model_id" {
				continue
			}
			if (key == "module" || key == "source_info" || key == "condition" || key == "object") && (item == nil || item == "") {
				continue
			}
			if isEmptyCollection(item) {
				continue
			}
			out[key] = item
		}
		return out
	case []any:
		out := make([]any, len(x))
		for i, item := range x {
			out[i] = normalizeModel(item)
		}
		return out
	}
	return v
}

// sameModel reports whether two models are the same once normalized.
func sameModel(a, b any) bool { return reflect.DeepEqual(normalizeModel(a), normalizeModel(b)) }

// withoutProvenance is a model element as OpenFGA evaluates it, without where
// a module declared it (openfga_bootstrap.py _without_provenance).
func withoutProvenance(v any) any {
	switch x := v.(type) {
	case map[string]any:
		out := make(map[string]any, len(x))
		for key, raw := range x {
			if key == "module" || key == "source_info" {
				continue
			}
			item := withoutProvenance(raw)
			if item == nil || item == "" || isEmptyCollection(item) {
				continue
			}
			out[key] = item
		}
		return out
	case []any:
		out := make([]any, len(x))
		for i, item := range x {
			out[i] = withoutProvenance(item)
		}
		return out
	}
	return v
}

func asMap(v any) map[string]any {
	m, _ := v.(map[string]any)
	return m
}

func asList(v any) []any {
	l, _ := v.([]any)
	return l
}

func relationMetadata(typeDef map[string]any) map[string]any {
	return asMap(asMap(typeDef["metadata"])["relations"])
}

func definition(rewrite, metadata any) any {
	return withoutProvenance(map[string]any{"rewrite": rewrite, "metadata": metadata})
}

// RequireExtends refuses a custom model that drops or redefines any type,
// relation or condition of base: the platform's checks name them, so a model
// without them fails every such check at runtime. Additions are allowed.
func RequireExtends(custom, base map[string]any) error {
	var problems []string
	customTypes := map[string]map[string]any{}
	for _, t := range asList(custom["type_definitions"]) {
		td := asMap(t)
		if name, ok := td["type"].(string); ok {
			customTypes[name] = td
		}
	}
	for _, t := range asList(base["type_definitions"]) {
		baseType := asMap(t)
		name, _ := baseType["type"].(string)
		mine, ok := customTypes[name]
		if !ok {
			problems = append(problems, "type "+name+" is missing")
			continue
		}
		baseMeta, mineMeta := relationMetadata(baseType), relationMetadata(mine)
		baseRelations, mineRelations := asMap(baseType["relations"]), asMap(mine["relations"])
		names := make([]string, 0, len(baseRelations))
		for rel := range baseRelations {
			names = append(names, rel)
		}
		slices.Sort(names)
		for _, rel := range names {
			mineRewrite, present := mineRelations[rel]
			switch {
			case !present:
				problems = append(problems, name+"#"+rel+" is missing")
			case !reflect.DeepEqual(definition(mineRewrite, mineMeta[rel]), definition(baseRelations[rel], baseMeta[rel])):
				problems = append(problems, name+"#"+rel+" is redefined")
			}
		}
	}
	customConditions := asMap(custom["conditions"])
	baseConditions := asMap(base["conditions"])
	names := make([]string, 0, len(baseConditions))
	for c := range baseConditions {
		names = append(names, c)
	}
	slices.Sort(names)
	for _, c := range names {
		if !reflect.DeepEqual(withoutProvenance(customConditions[c]), withoutProvenance(baseConditions[c])) {
			problems = append(problems, "condition "+c+" is missing or redefined")
		}
	}
	if len(problems) > 0 {
		return fmt.Errorf("AGENTAREA_AUTHZ_FGA_MODEL_PATH must extend the packaged authorization model: %s", strings.Join(problems, "; "))
	}
	return nil
}
