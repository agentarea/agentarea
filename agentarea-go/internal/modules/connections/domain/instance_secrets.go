package domain

import "slices"

// isMask is a value equal to one of the two placeholders a masked response shows.
func isMask(v any) bool {
	s, ok := v.(string)
	return ok && (s == MaskedValue || s == "••••••")
}

func uniqueStrings(in []string) []string {
	var out []string
	for _, s := range in {
		if !slices.Contains(out, s) {
			out = append(out, s)
		}
	}
	return out
}

// ExtractSecrets is _extract_secrets_from_spec: the spec as stored, with every
// secret value of environment and headers taken out, and those values. A
// value is secret when the schema marks it or does not know it; a masked
// value keeps what previous stored; a reference stays in the spec.
func ExtractSecrets(spec map[string]any, schema []EnvSchemaEntry, previous map[string]any) (map[string]any, map[string]string, error) {
	known, secret := map[string]bool{}, map[string]bool{}
	for _, e := range schema {
		known[e.Name] = true
		if e.IsSecret {
			secret[e.Name] = true
		}
	}
	declared := uniqueStrings(StringList(spec["env_vars"]))
	for _, n := range declared {
		secret[n] = true
	}
	out := copyMap(spec)
	fields := slices.Clone(declared)
	values := map[string]string{}
	for _, field := range []string{"environment", "headers"} {
		vals, ok := out[field].(map[string]any)
		if !ok {
			continue
		}
		prevVals, _ := previous[field].(map[string]any)
		cleaned := map[string]any{}
		for _, name := range sortedKeys(vals) {
			value := vals[name]
			prev := prevVals[name]
			if isMask(value) && IsSecretRef(prev) {
				value = prev
			}
			ref, err := SecretRefName(field+"."+name, value)
			if err != nil {
				return nil, nil, Refused(err.Error())
			}
			if ref != "" || (!secret[name] && known[name]) {
				cleaned[name] = value
				continue
			}
			if !slices.Contains(fields, name) {
				fields = append(fields, name)
			}
			stored := value
			if isMask(value) {
				if prev == nil || isMask(prev) {
					continue
				}
				stored = prev
			}
			if stored != nil {
				values[name] = pyStr(stored)
			}
		}
		out[field] = cleaned
	}
	if len(fields) > 0 {
		var list []any
		for _, n := range uniqueStrings(append(StringList(out["env_vars"]), fields...)) {
			list = append(list, n)
		}
		out["env_vars"] = list
	}
	refs, err := SpecSecretRefs(out)
	if err != nil {
		return nil, nil, Refused(err.Error())
	}
	if l, ok := out["env_vars"].([]any); ok && len(refs) > 0 {
		kept := []any{}
		for _, n := range l {
			if s, ok := n.(string); ok {
				if _, isRef := refs[s]; isRef {
					continue
				}
			}
			kept = append(kept, n)
		}
		out["env_vars"] = kept
	}
	return out, values, nil
}
