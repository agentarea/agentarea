package openapispec

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"net/http"
	"strconv"
	"strings"

	"go.yaml.in/yaml/v3"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/netguard"
)

// Spec YAML budgets (_SPEC_MAX_NODES, _SPEC_MAX_DEPTH): the byte limit bounds
// the work once aliases and merge keys are refused.
const (
	specMaxNodes = 2_000_000
	specMaxDepth = 128
)

// FetchTimeout is the spec fetch's whole-request deadline.
const FetchTimeout = 30

// Fetch is fetch_and_parse_spec after the URL check: one GET through
// client, which must not follow redirects, read up to MaxSpecBytes and
// parsed as JSON, else YAML (YAML first for a .yaml or .yml URL). Every
// refusal is an *Error; objects keep their key order.
func Fetch(ctx context.Context, client *http.Client, url string, headers map[string]string) (any, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, errorf("Could not fetch the spec from %s: %v", url, err)
	}
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	resp, err := client.Do(req)
	if err != nil {
		if errors.Is(err, netguard.ErrUnsafe) {
			return nil, errorf("%s", UnsafeMessage(err))
		}
		return nil, errorf("Could not fetch the spec from %s: %v", url, err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, errorf("Spec URL %s returned HTTP %d", url, resp.StatusCode)
	}
	raw, err := io.ReadAll(io.LimitReader(resp.Body, MaxSpecBytes+1))
	if err != nil {
		return nil, errorf("Could not fetch the spec from %s: %v", url, err)
	}
	if len(raw) > MaxSpecBytes {
		return nil, errorf("Spec response exceeds 5MB limit.")
	}
	text := strings.ToValidUTF8(string(raw), "�")
	if strings.HasSuffix(url, ".yaml") || strings.HasSuffix(url, ".yml") {
		return LoadYAML(text)
	}
	if v, err := wirejson.Unmarshal([]byte(text)); err == nil {
		return v, nil
	}
	return LoadYAML(text)
}

// UnsafeMessage is the refusal text of an outbound destination netguard refused.
func UnsafeMessage(err error) string {
	var blocked *netguard.BlockedError
	var resolve *netguard.ResolveError
	var bad *netguard.URLError
	switch {
	case errors.As(err, &blocked):
		return blocked.Error()
	case errors.As(err, &resolve):
		return resolve.Error()
	case errors.As(err, &bad):
		return bad.Error()
	}
	return err.Error()
}

// LoadYAML is _load_yaml_spec: load_untrusted_yaml with timestamps kept as
// text; aliases, merge keys and the node and depth budgets are refused.
func LoadYAML(text string) (any, error) {
	fail := func(msg string) error { return errorf("The spec is not acceptable YAML: %s", msg) }
	if len(text) > MaxSpecBytes {
		return nil, fail(fmt.Sprintf("YAML is larger than %d bytes", MaxSpecBytes))
	}
	dec := yaml.NewDecoder(strings.NewReader(text))
	var doc yaml.Node
	if err := dec.Decode(&doc); err != nil {
		if errors.Is(err, io.EOF) {
			return nil, nil
		}
		return nil, fail(strings.TrimPrefix(err.Error(), "yaml: "))
	}
	var more yaml.Node
	if err := dec.Decode(&more); err == nil {
		return nil, fail("expected a single document in the stream")
	} else if !errors.Is(err, io.EOF) {
		return nil, fail(strings.TrimPrefix(err.Error(), "yaml: "))
	}
	if len(doc.Content) == 0 {
		return nil, nil
	}
	nodes := 0
	v, err := yamlValue(doc.Content[0], 1, &nodes)
	if err != nil {
		return nil, fail(err.Error())
	}
	return v, nil
}

func yamlValue(n *yaml.Node, depth int, nodes *int) (any, error) {
	if n.Kind == yaml.AliasNode {
		return nil, errors.New("YAML aliases are not accepted here")
	}
	*nodes++
	if *nodes > specMaxNodes {
		return nil, fmt.Errorf("YAML holds at most %d nodes here", specMaxNodes)
	}
	if depth > specMaxDepth {
		return nil, fmt.Errorf("YAML is nested deeper than %d levels", specMaxDepth)
	}
	switch n.Kind {
	case yaml.MappingNode:
		out := wirejson.Object{}
		for i := 0; i+1 < len(n.Content); i += 2 {
			k := n.Content[i]
			if k.Kind == yaml.ScalarNode && k.ShortTag() == "!!merge" {
				return nil, errors.New("YAML merge keys are not accepted here")
			}
			key, err := yamlValue(k, depth+1, nodes)
			if err != nil {
				return nil, err
			}
			v, err := yamlValue(n.Content[i+1], depth+1, nodes)
			if err != nil {
				return nil, err
			}
			out.Set(keyText(key), v)
		}
		return out, nil
	case yaml.SequenceNode:
		out := make([]any, 0, len(n.Content))
		for _, c := range n.Content {
			v, err := yamlValue(c, depth+1, nodes)
			if err != nil {
				return nil, err
			}
			out = append(out, v)
		}
		return out, nil
	case yaml.ScalarNode:
		return yamlScalar(n)
	case yaml.AliasNode:
		return nil, errors.New("YAML aliases are not accepted here")
	case yaml.DocumentNode:
		if len(n.Content) == 0 {
			return nil, nil
		}
		return yamlValue(n.Content[0], depth, nodes)
	}
	return nil, nil
}

func yamlScalar(n *yaml.Node) (any, error) {
	switch n.ShortTag() {
	case "!!null":
		return nil, nil
	case "!!bool":
		var b bool
		if err := n.Decode(&b); err != nil {
			return nil, err
		}
		return b, nil
	case "!!int":
		var i int64
		if err := n.Decode(&i); err == nil {
			return json.Number(strconv.FormatInt(i, 10)), nil
		}
		return n.Value, nil
	case "!!float":
		var f float64
		if err := n.Decode(&f); err != nil {
			return nil, err
		}
		if math.IsInf(f, 0) || math.IsNaN(f) {
			return n.Value, nil
		}
		return wirejson.Float(f), nil
	case "!!binary":
		return n.Value, nil
	}
	return n.Value, nil
}

// keyText is the key a JSON object holds for a YAML key, as json.dumps writes one.
func keyText(v any) string {
	switch t := v.(type) {
	case string:
		return t
	case nil:
		return "null"
	case bool:
		if t {
			return "true"
		}
		return "false"
	case wirejson.Float:
		return wirejson.FormatFloat(float64(t))
	}
	return fmt.Sprint(v)
}
