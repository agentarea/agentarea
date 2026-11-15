package mcpserver

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	connectionsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/api"
)

type connectionIDArgs struct {
	ConnectionID string `json:"connection_id"`
}

// jsonArg is one *_json argument: the document key it fills and its text.
type jsonArg struct {
	key, arg, text string
}

// toolDocumentOf is fields plus every non-empty *_json argument decoded
// (json.loads), as one document.
func toolDocumentOf(fields map[string]any, args ...jsonArg) (json.RawMessage, error) {
	for _, a := range args {
		if a.text == "" {
			continue
		}
		if !json.Valid([]byte(a.text)) {
			var v any
			err := json.Unmarshal([]byte(a.text), &v)
			return nil, fmt.Errorf("%s is not JSON: %w", a.arg, err)
		}
		fields[a.key] = json.RawMessage(a.text)
	}
	return json.Marshal(fields)
}

func openAPIConnectionJSON(conn connectionsapi.OpenAPIConnection) map[string]any {
	named := func(fs []connectionsapi.NamedField) []map[string]any {
		out := make([]map[string]any, len(fs))
		for i, f := range fs {
			out[i] = map[string]any{"name": f.Name, "secret": f.Secret}
		}
		return out
	}
	return map[string]any{
		"id": conn.ID, "name": conn.Name, "description": conn.Description,
		"base_url": conn.BaseURL, "spec_url": conn.SpecURL, "auth_config_id": conn.AuthConfigID,
		"custom_headers": named(conn.CustomHeaders), "custom_query_params": named(conn.CustomQueryParams),
		"url_variables": conn.URLVariables, "tools_count": len(conn.Tools),
		"status": conn.Status, "last_dispatch": conn.LastDispatch,
	}
}

func openAPIToolsJSON(tools []connectionsapi.OpenAPITool) []map[string]any {
	out := make([]map[string]any, len(tools))
	for i, t := range tools {
		out[i] = map[string]any{"name": t.Name, "description": t.Description}
	}
	return out
}

func connectionNotFound(err error) error {
	if errors.Is(err, connectionsapi.ErrNotFound) {
		return &toolError{"Connection not found"}
	}
	return err
}

// openAPITools is tools/openapi_connections_toolset.py.
func openAPITools(o connectionsapi.PlatformOpenAPI) map[string]toolDef {
	return map[string]toolDef{
		"create": {title: "Create OpenAPI connection", effect: effectWrite, openWorld: true, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				Name              string  `json:"name"`
				BaseURL           string  `json:"base_url"`
				Description       *string `json:"description"`
				SpecURL           *string `json:"spec_url"`
				SpecContentJSON   string  `json:"spec_content_json"`
				AuthConfigID      *string `json:"auth_config_id"`
				CustomHeadersJSON string  `json:"custom_headers_json"`
				CustomQueryJSON   string  `json:"custom_query_params_json"`
				URLVariablesJSON  string  `json:"url_variables_json"`
			}](args)
			if err != nil {
				return nil, err
			}
			fields := map[string]any{"name": in.Name, "base_url": in.BaseURL}
			for k, v := range map[string]*string{"description": in.Description, "spec_url": in.SpecURL} {
				if v != nil {
					fields[k] = *v
				}
			}
			if in.AuthConfigID != nil && *in.AuthConfigID != "" {
				fields["auth_config_id"] = *in.AuthConfigID
			}
			doc, err := toolDocumentOf(fields,
				jsonArg{"spec_content", "spec_content_json", in.SpecContentJSON},
				jsonArg{"custom_headers", "custom_headers_json", in.CustomHeadersJSON},
				jsonArg{"custom_query_params", "custom_query_params_json", in.CustomQueryJSON},
				jsonArg{"url_variables", "url_variables_json", in.URLVariablesJSON})
			if err != nil {
				return nil, err
			}
			conn, err := o.Create(ctx, c, doc)
			if err != nil {
				return nil, err
			}
			return openAPIConnectionJSON(conn), nil
		}},
		"list": {title: "List OpenAPI connections", effect: effectRead, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				Search string `json:"search"`
				Limit  *int   `json:"limit"`
				Offset int    `json:"offset"`
			}](args)
			if err != nil {
				return nil, err
			}
			limit := 100
			if in.Limit != nil {
				limit = *in.Limit
			}
			limit = max(1, min(limit, maxListed))
			conns, total, err := o.List(ctx, c, in.Search, limit, in.Offset)
			if err != nil {
				return nil, err
			}
			items := make([]map[string]any, len(conns))
			for i, conn := range conns {
				items[i] = openAPIConnectionJSON(conn)
			}
			return map[string]any{"items": items, "total": total}, nil
		}},
		"get": {title: "Get OpenAPI connection", effect: effectRead, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[connectionIDArgs](args)
			if err != nil {
				return nil, err
			}
			conn, err := o.Get(ctx, c, in.ConnectionID)
			if err != nil {
				return nil, connectionNotFound(err)
			}
			out := openAPIConnectionJSON(conn)
			out["tools"] = openAPIToolsJSON(conn.Tools)
			return out, nil
		}},
		"update": {title: "Update OpenAPI connection", effect: effectWrite, idempotent: true, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				ConnectionID      string  `json:"connection_id"`
				Name              *string `json:"name"`
				Description       *string `json:"description"`
				BaseURL           *string `json:"base_url"`
				SpecURL           *string `json:"spec_url"`
				SpecContentJSON   string  `json:"spec_content_json"`
				AuthConfigID      *string `json:"auth_config_id"`
				CustomHeadersJSON string  `json:"custom_headers_json"`
				CustomQueryJSON   string  `json:"custom_query_params_json"`
				URLVariablesJSON  string  `json:"url_variables_json"`
				CostJSON          string  `json:"cost_json"`
			}](args)
			if err != nil {
				return nil, err
			}
			fields := map[string]any{}
			for k, v := range map[string]*string{"name": in.Name, "description": in.Description, "base_url": in.BaseURL, "spec_url": in.SpecURL} {
				if v != nil {
					fields[k] = *v
				}
			}
			if in.AuthConfigID != nil {
				if *in.AuthConfigID == "" {
					fields["auth_config_id"] = nil
				} else {
					fields["auth_config_id"] = *in.AuthConfigID
				}
			}
			doc, err := toolDocumentOf(fields,
				jsonArg{"spec_content", "spec_content_json", in.SpecContentJSON},
				jsonArg{"custom_headers", "custom_headers_json", in.CustomHeadersJSON},
				jsonArg{"custom_query_params", "custom_query_params_json", in.CustomQueryJSON},
				jsonArg{"url_variables", "url_variables_json", in.URLVariablesJSON},
				jsonArg{"cost", "cost_json", in.CostJSON})
			if err != nil {
				return nil, err
			}
			conn, err := o.Update(ctx, c, in.ConnectionID, doc)
			if err != nil {
				return nil, connectionNotFound(err)
			}
			return openAPIConnectionJSON(conn), nil
		}},
		"discover_tools": {title: "Discover OpenAPI tools", effect: effectWrite, idempotent: true, openWorld: true, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[connectionIDArgs](args)
			if err != nil {
				return nil, err
			}
			d, err := o.DiscoverTools(ctx, c, in.ConnectionID)
			if err != nil {
				return nil, err
			}
			return map[string]any{"connection_id": d.ConnectionID, "tools_discovered": len(d.Tools), "tools": openAPIToolsJSON(d.Tools)}, nil
		}},
		"delete": {title: "Delete OpenAPI connection", effect: effectDestructive, idempotent: true, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[connectionIDArgs](args)
			if err != nil {
				return nil, err
			}
			deleted, err := o.Delete(ctx, c, in.ConnectionID)
			if err != nil {
				return nil, err
			}
			return map[string]any{"deleted": deleted}, nil
		}},
	}
}
