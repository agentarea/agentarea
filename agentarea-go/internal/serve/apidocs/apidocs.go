// Package apidocs is the pages FastAPI served next to /openapi.json: Swagger UI
// at /docs, its OAuth2 redirect, and ReDoc at /redoc, as fastapi.openapi.docs
// renders them for the AgentArea API.
package apidocs

import _ "embed"

//go:embed swagger.html
var swagger []byte

//go:embed redoc.html
var redoc []byte

//go:embed oauth2-redirect.html
var oauth2Redirect []byte

// Swagger is /docs.
func Swagger() []byte { return swagger }

// ReDoc is /redoc.
func ReDoc() []byte { return redoc }

// OAuth2Redirect is /docs/oauth2-redirect.
func OAuth2Redirect() []byte { return oauth2Redirect }
