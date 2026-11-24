package openapispec

import (
	"regexp"
	"sort"
	"strings"
)

// KeyField is one value a catalog API's key form asks for.
type KeyField struct {
	Name     string
	Location string
	Label    string
	Scheme   *string
	// Description is nil when absent or empty.
	Description *string
}

// KeyTemplate is catalog_key_template's form.
type KeyTemplate struct{ Fields []KeyField }

// KeyTemplateError is CatalogKeyTemplateError: the catalog item is malformed, a 500.
type KeyTemplateError struct{ Msg string }

func (e *KeyTemplateError) Error() string { return e.Msg }

var (
	keyHeaderName = regexp.MustCompile(`^[A-Za-z0-9\-_]+$`)
	keyQueryName  = regexp.MustCompile(`^[A-Za-z0-9_.\-\[\]]+$`)
	keyScheme     = regexp.MustCompile(`^[A-Za-z0-9\-_]+$`)
)

func keyErr(msg string) error { return &KeyTemplateError{Msg: msg} }

func keyField(entry any) (KeyField, error) {
	o, ok := asObject(entry)
	if !ok {
		return KeyField{}, keyErr("api_key field is not an object")
	}
	name, location, label := get(o, "name", nil), get(o, "location", nil), get(o, "label", nil)
	scheme, description := get(o, "scheme", nil), get(o, "description", nil)
	loc, _ := location.(string)
	if loc != "header" && loc != "query" {
		return KeyField{}, keyErr("api_key field location " + repr(location) + " is not header or query")
	}
	pattern := keyHeaderName
	if loc == "query" {
		pattern = keyQueryName
	}
	n, isStr := name.(string)
	if !isStr || !pattern.MatchString(n) {
		return KeyField{}, keyErr("api_key field name " + repr(name) + " is not a valid " + loc + " name")
	}
	l, isStr := label.(string)
	if !isStr || strings.TrimSpace(l) == "" {
		return KeyField{}, keyErr("api_key field " + n + " has no label")
	}
	f := KeyField{Name: n, Location: loc, Label: strings.TrimSpace(l)}
	if scheme != nil {
		s, isStr := scheme.(string)
		if loc != "header" || !isStr || !keyScheme.MatchString(s) {
			return KeyField{}, keyErr("api_key field " + n + " has an invalid scheme")
		}
		f.Scheme = &s
	}
	if description != nil {
		d, isStr := description.(string)
		if !isStr {
			return KeyField{}, keyErr("api_key field " + n + " has an invalid description")
		}
		if d != "" {
			f.Description = &d
		}
	}
	return f, nil
}

// CatalogKeyTemplate is catalog_key_template: the key form a catalog item
// declares, nil when it authenticates another way (OAuth).
func CatalogKeyTemplate(spec map[string]any) (*KeyTemplate, error) {
	block, ok := spec["api_key"]
	if !ok || block == nil {
		return nil, nil
	}
	o, ok := asObject(block)
	if !ok {
		return nil, keyErr("api_key is not an object")
	}
	entries, ok := get(o, "fields", nil).([]any)
	if !ok || len(entries) == 0 {
		return nil, keyErr("api_key declares no fields")
	}
	t := &KeyTemplate{}
	seen := map[string]bool{}
	for _, e := range entries {
		f, err := keyField(e)
		if err != nil {
			return nil, err
		}
		key := f.Location + "\x00" + f.Name
		if f.Location == "header" {
			key = f.Location + "\x00" + strings.ToLower(f.Name)
		}
		if seen[key] {
			return nil, keyErr("api_key declares the same field twice")
		}
		seen[key] = true
		t.Fields = append(t.Fields, f)
	}
	return t, nil
}

// KeyHeader and KeyQuery are a new connection's credentials from its key form.
type KeyHeader struct{ Name, Value string }

// Credentials is catalog_key_credentials: one secret header or query
// parameter per field; an unknown or empty value is an *Error.
func (t *KeyTemplate) Credentials(values map[string]string) (headers, query []KeyHeader, err error) {
	known := map[string]bool{}
	for _, f := range t.Fields {
		known[f.Name] = true
	}
	var unknown []string
	for k := range values {
		if !known[k] {
			unknown = append(unknown, k)
		}
	}
	if len(unknown) > 0 {
		sort.Strings(unknown)
		return nil, nil, errorf("Not a field of this connection: %s", strings.Join(unknown, ", "))
	}
	for _, f := range t.Fields {
		v := strings.TrimSpace(values[f.Name])
		if v == "" {
			return nil, nil, errorf("%s is required", f.Label)
		}
		if f.Location == "header" {
			if f.Scheme != nil {
				v = *f.Scheme + " " + v
			}
			headers = append(headers, KeyHeader{Name: f.Name, Value: v})
		} else {
			query = append(query, KeyHeader{Name: f.Name, Value: v})
		}
	}
	return headers, query, nil
}
