package mcpgateway

import "testing"

// Either json_spec column can hold the JSON literal `null` instead of SQL NULL:
// the control plane writes it whenever the field was omitted, and the query's
// COALESCE only substitutes for the SQL flavour. Unmarshalling `null` into a map
// yields nil, so merging the instance spec over it used to panic with
// "assignment to entry in nil map" -- gin recovered, and the platform saw a 500
// for every request to that instance.
func TestDecodeSpecsAcceptsNullServerSpec(t *testing.T) {
	spec, err := decodeSpecs([]byte("null"), []byte(`{"type":"docker","port":8000}`))
	if err != nil {
		t.Fatalf("decodeSpecs() error = %v, want nil", err)
	}
	if spec == nil {
		t.Fatal("decodeSpecs() returned a nil map; callers write into it")
	}
	if got := spec["type"]; got != "docker" {
		t.Fatalf("spec[type] = %v, want docker", got)
	}
	if got := spec["port"]; got != float64(8000) {
		t.Fatalf("spec[port] = %v, want 8000", got)
	}
}

func TestDecodeSpecsAcceptsNullInstanceSpec(t *testing.T) {
	spec, err := decodeSpecs([]byte(`{"type":"docker","image":"example:1"}`), []byte("null"))
	if err != nil {
		t.Fatalf("decodeSpecs() error = %v, want nil", err)
	}
	if got := spec["image"]; got != "example:1" {
		t.Fatalf("spec[image] = %v, want example:1", got)
	}
}

func TestDecodeSpecsInstanceOverridesServer(t *testing.T) {
	spec, err := decodeSpecs(
		[]byte(`{"type":"docker","image":"example:1","port":9000}`),
		[]byte(`{"port":8000}`),
	)
	if err != nil {
		t.Fatalf("decodeSpecs() error = %v, want nil", err)
	}
	if got := spec["port"]; got != float64(8000) {
		t.Fatalf("spec[port] = %v, want the instance value 8000", got)
	}
	if got := spec["image"]; got != "example:1" {
		t.Fatalf("spec[image] = %v, want the server value example:1", got)
	}
}

func TestDecodeSpecsRejectsMalformedJSON(t *testing.T) {
	if _, err := decodeSpecs([]byte("{"), []byte("{}")); err == nil {
		t.Fatal("decodeSpecs() error = nil, want a decode failure for malformed server spec")
	}
	if _, err := decodeSpecs([]byte("{}"), []byte("{")); err == nil {
		t.Fatal("decodeSpecs() error = nil, want a decode failure for malformed instance spec")
	}
}
