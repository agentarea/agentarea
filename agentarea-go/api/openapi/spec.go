// Package openapi holds the API's OpenAPI document and, one package per
// module below it, the server interfaces tools/openapigen generates from it.
package openapi

import _ "embed"

//go:embed openapi.json
var spec []byte

// Spec is the OpenAPI document the serve role publishes at /openapi.json: the
// spec exported from the Python API (agentarea-webapp/src/api/openapi.json), byte for byte.
func Spec() []byte { return spec }
