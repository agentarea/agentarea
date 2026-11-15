package store

import (
	"context"
	"encoding/json"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
)

// OpenAPI is the openapi_connections repository.
type OpenAPI struct{}

// Filter is the list's optional status and name/description pattern (nil: none).
type Filter struct {
	Status  *string
	Pattern *string
}

type storedHeader struct {
	Name   string  `json:"name"`
	Secret bool    `json:"secret"`
	Value  *string `json:"value"`
}

type storedTool struct {
	Name        any            `json:"name"`
	Description any            `json:"description"`
	InputSchema map[string]any `json:"inputSchema"`
}

func str(v any) string {
	s, _ := v.(string)
	return s
}

func connFrom(r GetOpenAPIConnectionRow) (domain.Connection, error) {
	var headers []storedHeader
	if err := json.Unmarshal(orNull(r.CustomHeaders), &headers); err != nil {
		return domain.Connection{}, err
	}
	var query []storedHeader
	if err := json.Unmarshal(orNull(r.CustomQueryParams), &query); err != nil {
		return domain.Connection{}, err
	}
	var vars []string
	if err := json.Unmarshal(orNull(r.UrlVariables), &vars); err != nil {
		return domain.Connection{}, err
	}
	var tools []storedTool
	if err := json.Unmarshal(orNull(r.AvailableTools), &tools); err != nil {
		return domain.Connection{}, err
	}
	last, err := jsonMap(r.LastDispatch)
	if err != nil {
		return domain.Connection{}, err
	}
	cost, err := jsonMap(r.Cost)
	if err != nil {
		return domain.Connection{}, err
	}
	c := domain.Connection{
		ID: r.ID.String(), WorkspaceID: r.WorkspaceID, CreatedBy: r.CreatedBy, Name: r.Name,
		Description: fromText(r.Description), SpecURL: fromText(r.SpecUrl), BaseURL: r.BaseUrl,
		AuthConfigID: fromNullUUID(r.AuthConfigID), RegistryItemID: fromNullUUID(r.RegistryItemID),
		URLVariables: vars, Status: r.Status, LastDispatch: last, Cost: cost, ManagedBy: fromText(r.ManagedBy),
		CreatedAt: fromTimestamp(r.CreatedAt), UpdatedAt: fromTimestamp(r.UpdatedAt),
	}
	for _, h := range headers {
		c.CustomHeaders = append(c.CustomHeaders, domain.Header{Name: h.Name, Secret: h.Secret, Value: h.Value})
	}
	for _, p := range query {
		c.CustomQuery = append(c.CustomQuery, domain.QueryParam{Name: p.Name, Secret: p.Secret, Value: p.Value})
	}
	for _, t := range tools {
		tool := domain.Tool{Name: str(t.Name), Description: str(t.Description), InputSchema: t.InputSchema}
		c.AvailableTools = append(c.AvailableTools, tool)
	}
	return c, nil
}

// orNull keeps a missing column decodable as an empty list.
func orNull(b []byte) []byte {
	if len(b) == 0 {
		return []byte("null")
	}
	return b
}

// List is one page of the workspace's connections and the platform's, newest first.
func (OpenAPI) List(ctx context.Context, s db.Session, f Filter, limit, offset int32) ([]domain.Connection, error) {
	p := ListOpenAPIConnectionsParams{WorkspaceID: s.Workspace().ID(), PageLimit: limit, PageOffset: offset}
	p.Status = text(f.Status)
	if f.Pattern != nil {
		p.Pattern = text(f.Pattern)
	}
	rows, err := New(s.Q()).ListOpenAPIConnections(ctx, p)
	if err != nil {
		return nil, err
	}
	out := make([]domain.Connection, 0, len(rows))
	for _, r := range rows {
		c, err := connFrom(GetOpenAPIConnectionRow(r))
		if err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, nil
}

// Get is the connection id the workspace sees; false when there is none.
func (OpenAPI) Get(ctx context.Context, s db.Session, id uuid.UUID) (domain.Connection, bool, error) {
	r, err := New(s.Q()).GetOpenAPIConnection(ctx, GetOpenAPIConnectionParams{ID: id, WorkspaceID: s.Workspace().ID()})
	if IsNoRows(err) {
		return domain.Connection{}, false, nil
	}
	if err != nil {
		return domain.Connection{}, false, err
	}
	c, err := connFrom(r)
	return c, err == nil, err
}

// Delete removes the workspace's own row; false when there is none.
func (OpenAPI) Delete(ctx context.Context, s db.Session, id uuid.UUID) (bool, error) {
	n, err := New(s.Q()).DeleteOpenAPIConnection(ctx, DeleteOpenAPIConnectionParams{ID: id, WorkspaceID: s.Workspace().ID()})
	return n > 0, err
}
