package openapi

import (
	"bytes"
	"encoding/json"
	"os"
	"testing"
)

func TestSpecIsTheExportedSpec(t *testing.T) {
	exported, err := os.ReadFile("../../../agentarea-webapp/src/api/openapi.json")
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(Spec(), exported) {
		t.Fatal("api/openapi/openapi.json differs from agentarea-webapp/src/api/openapi.json: run go run ./tools/openapigen")
	}
	var doc struct {
		OpenAPI string         `json:"openapi"`
		Paths   map[string]any `json:"paths"`
	}
	if err := json.Unmarshal(Spec(), &doc); err != nil || doc.OpenAPI == "" || len(doc.Paths) == 0 {
		t.Fatalf("not an OpenAPI document: %v", err)
	}
}
