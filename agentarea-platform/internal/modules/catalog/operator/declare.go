package operator

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strings"

	"sigs.k8s.io/yaml"
)

// Declared is one resource of a manifest: what the controller would read from the cluster.
type Declared struct {
	Kind, Namespace, Name string
	Spec                  map[string]any
}

func resourceOf(kind string) (string, bool) {
	switch kind {
	case "LLMProviderConfig":
		return KindProvider, true
	case "PlatformConnection":
		return KindConnection, true
	case "PlatformEgressExit":
		return KindEgressExit, true
	}
	return "", false
}

var documentSeparator = regexp.MustCompile(`(?m)^---[ \t]*$`)

// ReadManifests reads the declared resources of each path: a YAML file, which may hold several
// documents, or a directory, whose *.yaml and *.yml files are read in name order. A resource
// without a namespace takes namespace.
func ReadManifests(paths []string, namespace string) ([]Declared, error) {
	var out []Declared
	for _, p := range paths {
		files, err := manifestFiles(p)
		if err != nil {
			return nil, err
		}
		for _, f := range files {
			data, err := os.ReadFile(f)
			if err != nil {
				return nil, err
			}
			ds, err := parseManifest(data, namespace)
			if err != nil {
				return nil, fmt.Errorf("%s: %w", f, err)
			}
			out = append(out, ds...)
		}
	}
	return out, nil
}

func manifestFiles(path string) ([]string, error) {
	info, err := os.Stat(path)
	if err != nil {
		return nil, err
	}
	if !info.IsDir() {
		return []string{path}, nil
	}
	entries, err := os.ReadDir(path)
	if err != nil {
		return nil, err
	}
	var files []string
	for _, e := range entries {
		if ext := filepath.Ext(e.Name()); !e.IsDir() && (ext == ".yaml" || ext == ".yml") {
			files = append(files, filepath.Join(path, e.Name()))
		}
	}
	slices.Sort(files)
	return files, nil
}

func parseManifest(data []byte, namespace string) ([]Declared, error) {
	var out []Declared
	for i, doc := range documentSeparator.Split(string(data), -1) {
		var obj struct {
			APIVersion string `json:"apiVersion"`
			Kind       string `json:"kind"`
			Metadata   struct {
				Name      string `json:"name"`
				Namespace string `json:"namespace"`
			} `json:"metadata"`
			Spec map[string]any `json:"spec"`
		}
		if err := yaml.Unmarshal([]byte(doc), &obj); err != nil {
			return nil, fmt.Errorf("document %d: %w", i+1, err)
		}
		if obj.Kind == "" && obj.APIVersion == "" {
			continue
		}
		kind, ok := resourceOf(obj.Kind)
		if !ok || obj.APIVersion != "agentarea.io/v1alpha1" {
			return nil, fmt.Errorf("document %d: %s %s is not a declared resource "+
				"(agentarea.io/v1alpha1 LLMProviderConfig, PlatformConnection or PlatformEgressExit)", i+1, obj.APIVersion, obj.Kind)
		}
		if obj.Metadata.Name == "" {
			return nil, fmt.Errorf("document %d: metadata.name is required", i+1)
		}
		ns := obj.Metadata.Namespace
		if ns == "" {
			ns = namespace
		}
		spec := obj.Spec
		if spec == nil {
			spec = map[string]any{}
		}
		out = append(out, Declared{Kind: kind, Namespace: ns, Name: obj.Metadata.Name, Spec: spec})
	}
	return out, nil
}

// Apply reconciles d once, as the controller does when it first sees the resource.
func (r *Reconciler) Apply(ctx context.Context, d Declared) Outcome {
	switch d.Kind {
	case KindProvider:
		return r.Provider(ctx, d.Namespace, d.Name, d.Spec)
	case KindConnection:
		return r.Connection(ctx, d.Namespace, d.Name, d.Spec)
	default:
		return r.EgressExit(ctx, d.Namespace, d.Name, d.Spec)
	}
}

// DirSecrets reads a Secret's key from <dir>/<name>/<key>, the layout of a Secret mounted as a
// volume. The namespace is the resource's own and plays no part.
type DirSecrets struct{ Dir string }

// Read implements SecretReader.
func (s DirSecrets) Read(_ context.Context, _, name, key string) (string, error) {
	if s.Dir == "" {
		return "", fmt.Errorf("secret %s: no secrets directory was given", name)
	}
	for _, part := range []string{name, key} {
		if part == "" || part == "." || part == ".." || strings.ContainsAny(part, `/\`) {
			return "", fmt.Errorf("secret %q key %q: not a Secret name and key", name, key)
		}
	}
	data, err := os.ReadFile(filepath.Join(s.Dir, name, key))
	if errors.Is(err, os.ErrNotExist) {
		return "", fmt.Errorf("Key '%s' not found in Secret '%s'", key, name) //nolint:staticcheck // the status text operators read
	}
	if err != nil {
		return "", err
	}
	return strings.TrimRight(string(data), "\r\n"), nil
}
