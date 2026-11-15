package handlers

import (
	"net/http"
	"strconv"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/service"
)

// utcISO is utc_isoformat: a naive value read as UTC, with microseconds only when set.
func utcISO(t time.Time) string {
	t = t.UTC()
	if t.Nanosecond()/1000 == 0 {
		return t.Format("2006-01-02T15:04:05") + "Z"
	}
	return t.Format("2006-01-02T15:04:05.000000") + "Z"
}

func isoPtr(t *time.Time) any {
	if t == nil {
		return nil
	}
	return utcISO(*t)
}

func orNil[T any](p *T) any {
	if p == nil {
		return nil
	}
	return *p
}

// authJSON is MCPAuthConfigResponse; the credentials are never in it.
func authJSON(a domain.AuthConfig) wirejson.Object {
	cfg := a.Config
	if cfg == nil {
		cfg = map[string]any{}
	}
	return wirejson.Object{
		{Key: "id", Value: a.ID},
		{Key: "name", Value: a.Name},
		{Key: "description", Value: orNil(a.Description)},
		{Key: "auth_type", Value: a.AuthType},
		{Key: "config", Value: cfg},
		{Key: "created_at", Value: utcISO(a.CreatedAt)},
		{Key: "updated_at", Value: utcISO(a.UpdatedAt)},
	}
}

// linkJSON is OAuthLinkResponse, token included (the admin reads it).
func linkJSON(l domain.OAuthLink) wirejson.Object {
	return wirejson.Object{
		{Key: "id", Value: l.ID},
		{Key: "mcp_instance_id", Value: l.MCPInstanceID},
		{Key: "token", Value: l.Token},
		{Key: "access_control", Value: l.AccessControl},
		{Key: "is_active", Value: l.IsActive},
		{Key: "expires_at", Value: isoPtr(l.ExpiresAt)},
		{Key: "access_count", Value: int(l.AccessCount)},
		{Key: "last_accessed_at", Value: isoPtr(l.LastAccessedAt)},
		{Key: "created_at", Value: utcISO(l.CreatedAt)},
	}
}

// maskedHeaders is _format_headers: nil when empty, a secret's value never shown.
func maskedHeaders(hs []domain.Header) any {
	if len(hs) == 0 {
		return nil
	}
	out := make([]any, 0, len(hs))
	for _, h := range hs {
		var v any
		if !h.Secret && h.Value != nil {
			v = *h.Value
		}
		out = append(out, wirejson.Object{{Key: "name", Value: h.Name}, {Key: "secret", Value: h.Secret}, {Key: "value", Value: v}})
	}
	return out
}

func maskedQuery(ps []domain.QueryParam) any {
	if len(ps) == 0 {
		return nil
	}
	out := make([]any, 0, len(ps))
	for _, p := range ps {
		var v any
		if !p.Secret && p.Value != nil {
			v = *p.Value
		}
		out = append(out, wirejson.Object{{Key: "name", Value: p.Name}, {Key: "secret", Value: p.Secret}, {Key: "value", Value: v}})
	}
	return out
}

// connectionJSON is OpenAPIConnectionResponse in its field order.
func connectionJSON(v service.ConnectionView) wirejson.Object {
	c := v.Connection
	var base any
	if b := c.VisibleBaseURL(); b != nil {
		base = *b
	}
	var vars any
	if c.URLVariables != nil {
		vars = c.URLVariables
	}
	tools := make([]any, 0, len(c.AvailableTools))
	for _, t := range c.AvailableTools {
		var schema any
		if t.InputSchema != nil {
			schema = t.InputSchema
		}
		tools = append(tools, wirejson.Object{{Key: "name", Value: t.Name}, {Key: "description", Value: t.Description}, {Key: "inputSchema", Value: schema}})
	}
	var last, cost any
	if c.LastDispatch != nil {
		last = c.LastDispatch
	}
	if c.Cost != nil {
		cost = c.Cost
	}
	return wirejson.Object{
		{Key: "id", Value: c.ID},
		{Key: "name", Value: c.Name},
		{Key: "base_url", Value: base},
		{Key: "description", Value: orNil(c.Description)},
		{Key: "spec_url", Value: orNil(c.SpecURL)},
		{Key: "auth_config_id", Value: orNil(c.AuthConfigID)},
		{Key: "registry_item_id", Value: orNil(c.RegistryItemID)},
		{Key: "custom_headers", Value: maskedHeaders(c.CustomHeaders)},
		{Key: "custom_query_params", Value: maskedQuery(c.CustomQuery)},
		{Key: "url_variables", Value: vars},
		{Key: "available_tools", Value: tools},
		{Key: "status", Value: c.Status},
		{Key: "last_dispatch", Value: last},
		{Key: "cost", Value: cost},
		{Key: "managed_by", Value: orNil(c.ManagedBy)},
		{Key: "personal", Value: v.Sharing.Personal},
		{Key: "is_owner", Value: v.Sharing.IsOwner},
		{Key: "created_at", Value: utcISO(c.CreatedAt)},
		{Key: "updated_at", Value: utcISO(c.UpdatedAt)},
	}
}

// response is a JSONResponse body as Starlette writes it, or an empty status.
type response struct {
	status int
	body   any
}

func (x response) visit(w http.ResponseWriter) error {
	if x.body == nil {
		w.WriteHeader(x.status)
		return nil
	}
	raw, err := wirejson.Marshal(x.body, wirejson.Compact)
	if err != nil {
		return err
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Content-Length", strconv.Itoa(len(raw)))
	w.WriteHeader(x.status)
	_, err = w.Write(raw)
	return err
}

// The generated strict response objects, one visitor per operation.
func (x response) VisitListConnectionsV1OpenapiConnectionsGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitGetConnectionV1OpenapiConnectionsConnectionIdGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitDeleteConnectionV1OpenapiConnectionsConnectionIdDeleteResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitListMcpAuthConfigsV1McpAuthConfigsGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitCreateMcpAuthConfigV1McpAuthConfigsPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitGetMcpAuthConfigV1McpAuthConfigsConfigIdGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitUpdateMcpAuthConfigV1McpAuthConfigsConfigIdPutResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitDeleteMcpAuthConfigV1McpAuthConfigsConfigIdDeleteResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitCreateOauthLinkV1McpOauthLinksPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitListOauthLinksForInstanceV1McpOauthLinksInstanceInstanceIdGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitGetOauthLinkV1McpOauthLinksLinkIdGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitRevokeOauthLinkV1McpOauthLinksLinkIdDeleteResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
