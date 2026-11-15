package service

import (
	"bytes"
	"encoding/json"
	"fmt"
	"sort"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
)

// dumpsSorted is json.dumps(v, sort_keys=True, separators=(",", ":")) with
// ensure_ascii on, the bytes Python hashes and signs.
func dumpsSorted(v any) ([]byte, error) {
	raw, err := json.Marshal(v)
	if err != nil {
		return nil, err
	}
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	var generic any
	if err := dec.Decode(&generic); err != nil {
		return nil, err
	}
	return appendSorted(nil, generic)
}

func appendSorted(dst []byte, v any) ([]byte, error) {
	switch x := v.(type) {
	case nil:
		return append(dst, "null"...), nil
	case bool:
		if x {
			return append(dst, "true"...), nil
		}
		return append(dst, "false"...), nil
	case json.Number:
		return append(dst, x...), nil
	case string:
		return wirejson.AppendString(dst, x, wirejson.Dumps), nil
	case []any:
		dst = append(dst, '[')
		for i, e := range x {
			if i > 0 {
				dst = append(dst, ',')
			}
			var err error
			if dst, err = appendSorted(dst, e); err != nil {
				return nil, err
			}
		}
		return append(dst, ']'), nil
	case map[string]any:
		keys := make([]string, 0, len(x))
		for k := range x {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		dst = append(dst, '{')
		for i, k := range keys {
			if i > 0 {
				dst = append(dst, ',')
			}
			dst = wirejson.AppendString(dst, k, wirejson.Dumps)
			dst = append(dst, ':')
			var err error
			if dst, err = appendSorted(dst, x[k]); err != nil {
				return nil, err
			}
		}
		return append(dst, '}'), nil
	}
	return nil, fmt.Errorf("pyjson: unexpected %T", v)
}
