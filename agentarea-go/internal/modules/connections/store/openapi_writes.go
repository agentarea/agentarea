package store

import (
	"context"
	"encoding/json"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
)

// ConnectionNew is the row create inserts. Tools and SpecContent are JSON
// as written (key order kept); nil header, query and variable lists store NULL.
type ConnectionNew struct {
	ID                 uuid.UUID
	CreatedBy          string
	Name               string
	Description        *string
	SpecURL            *string
	SpecContent        json.RawMessage
	BaseURL            string
	AuthConfigID       *uuid.UUID
	RegistryItemID     *uuid.UUID
	AllowedAuthOrigins []string
	CustomHeaders      []domain.Header
	CustomQuery        []domain.QueryParam
	URLVariables       []string
	AvailableTools     json.RawMessage
	Status             string
	Now                time.Time
}

// ConnectionRow is every column update writes, all replaced.
type ConnectionRow struct {
	Name           string
	Description    *string
	SpecURL        *string
	SpecContent    json.RawMessage
	BaseURL        string
	AuthConfigID   *uuid.UUID
	CustomHeaders  []domain.Header
	CustomQuery    []domain.QueryParam
	URLVariables   []string
	AvailableTools json.RawMessage
	Cost           map[string]any
	Now            time.Time
}

// headersJSON is the stored shape: a secret entry carries no value.
func headersJSON(hs []domain.Header) []byte {
	if hs == nil {
		return nil
	}
	out := make([]wirejson.Object, 0, len(hs))
	for _, h := range hs {
		o := wirejson.Object{{Key: "name", Value: h.Name}, {Key: "secret", Value: h.Secret}}
		if !h.Secret {
			v := ""
			if h.Value != nil {
				v = *h.Value
			}
			o = append(o, wirejson.Member{Key: "value", Value: v})
		}
		out = append(out, o)
	}
	raw, err := json.Marshal(out)
	if err != nil {
		panic(err)
	}
	return raw
}

func queryJSON(ps []domain.QueryParam) []byte {
	if ps == nil {
		return nil
	}
	hs := make([]domain.Header, len(ps))
	for i, p := range ps {
		hs[i] = domain.Header(p)
	}
	return headersJSON(hs)
}

func stringsJSON(list []string) []byte {
	if list == nil {
		return nil
	}
	raw, err := json.Marshal(list)
	if err != nil {
		panic(err)
	}
	return raw
}

func rawOrNull(r json.RawMessage) []byte {
	if len(r) == 0 {
		return nil
	}
	return r
}

func toolsOrEmpty(r json.RawMessage) []byte {
	if len(r) == 0 {
		return []byte("[]")
	}
	return r
}

func fullFrom(r GetOpenAPIConnectionFullRow) (domain.Connection, error) {
	c, err := connFrom(GetOpenAPIConnectionRow{
		ID: r.ID, WorkspaceID: r.WorkspaceID, CreatedBy: r.CreatedBy, Name: r.Name, Description: r.Description,
		SpecUrl: r.SpecUrl, BaseUrl: r.BaseUrl, AuthConfigID: r.AuthConfigID, RegistryItemID: r.RegistryItemID,
		CustomHeaders: r.CustomHeaders, CustomQueryParams: r.CustomQueryParams, UrlVariables: r.UrlVariables,
		AvailableTools: r.AvailableTools, Status: r.Status, LastDispatch: r.LastDispatch, ManagedBy: r.ManagedBy,
		Cost: r.Cost, CreatedAt: r.CreatedAt, UpdatedAt: r.UpdatedAt,
	})
	if err != nil {
		return domain.Connection{}, err
	}
	if len(r.SpecContent) > 0 {
		if c.SpecContent, err = wirejson.Unmarshal(r.SpecContent); err != nil {
			return domain.Connection{}, err
		}
	}
	if err := json.Unmarshal(orNull(r.AllowedAuthOrigins), &c.AllowedAuthOrigins); err != nil {
		return domain.Connection{}, err
	}
	return c, nil
}

// Insert writes a new connection in the session's workspace.
func (OpenAPI) Insert(ctx context.Context, s db.Session, n ConnectionNew) (domain.Connection, error) {
	r, err := New(s.Q()).InsertOpenAPIConnection(ctx, InsertOpenAPIConnectionParams{
		ID: n.ID, WorkspaceID: s.Workspace().ID(), CreatedBy: n.CreatedBy, Name: n.Name,
		Description: text(n.Description), SpecUrl: text(n.SpecURL), SpecContent: rawOrNull(n.SpecContent),
		BaseUrl: n.BaseURL, AuthConfigID: nullUUID(n.AuthConfigID), RegistryItemID: nullUUID(n.RegistryItemID),
		AllowedAuthOrigins: stringsJSON(n.AllowedAuthOrigins), CustomHeaders: headersJSON(n.CustomHeaders),
		CustomQueryParams: queryJSON(n.CustomQuery), UrlVariables: stringsJSON(n.URLVariables),
		AvailableTools: toolsOrEmpty(n.AvailableTools), Status: n.Status, Now: naive(n.Now),
	})
	if err != nil {
		return domain.Connection{}, err
	}
	return fullFrom(GetOpenAPIConnectionFullRow(r))
}

// Full is the connection the workspace sees with its spec; false when none.
func (OpenAPI) Full(ctx context.Context, s db.Session, id uuid.UUID) (domain.Connection, bool, error) {
	r, err := New(s.Q()).GetOpenAPIConnectionFull(ctx, GetOpenAPIConnectionFullParams{ID: id, WorkspaceID: s.Workspace().ID()})
	if IsNoRows(err) {
		return domain.Connection{}, false, nil
	}
	if err != nil {
		return domain.Connection{}, false, err
	}
	c, err := fullFrom(r)
	return c, err == nil, err
}

// Lock reads the workspace's own row FOR UPDATE; s must be a transaction.
func (OpenAPI) Lock(ctx context.Context, s db.Session, id uuid.UUID) (domain.Connection, bool, error) {
	r, err := New(s.Q()).LockOpenAPIConnection(ctx, LockOpenAPIConnectionParams{ID: id, WorkspaceID: s.Workspace().ID()})
	if IsNoRows(err) {
		return domain.Connection{}, false, nil
	}
	if err != nil {
		return domain.Connection{}, false, err
	}
	c, err := fullFrom(GetOpenAPIConnectionFullRow(r))
	return c, err == nil, err
}

// Save replaces the workspace row's mutable columns; false when it has no such row.
func (OpenAPI) Save(ctx context.Context, s db.Session, id uuid.UUID, r ConnectionRow) (bool, error) {
	var cost []byte
	if r.Cost != nil {
		cost = jsonObject(r.Cost)
	}
	n, err := New(s.Q()).UpdateOpenAPIConnection(ctx, UpdateOpenAPIConnectionParams{
		ID: id, WorkspaceID: s.Workspace().ID(), Name: r.Name, Description: text(r.Description),
		SpecUrl: text(r.SpecURL), SpecContent: rawOrNull(r.SpecContent), BaseUrl: r.BaseURL,
		AuthConfigID: nullUUID(r.AuthConfigID), CustomHeaders: headersJSON(r.CustomHeaders),
		CustomQueryParams: queryJSON(r.CustomQuery), UrlVariables: stringsJSON(r.URLVariables),
		AvailableTools: toolsOrEmpty(r.AvailableTools), Cost: cost, Now: naive(r.Now),
	})
	return n > 0, err
}

// SetDiscovery stores the tools a spec gave and the spec; false when the
// workspace has no such row (a platform connection's tools are the platform's).
func (OpenAPI) SetDiscovery(ctx context.Context, s db.Session, id uuid.UUID, tools, spec json.RawMessage, now time.Time) (bool, error) {
	n, err := New(s.Q()).SetOpenAPIDiscovery(ctx, SetOpenAPIDiscoveryParams{
		ID: id, WorkspaceID: s.Workspace().ID(), AvailableTools: toolsOrEmpty(tools), SpecContent: rawOrNull(spec), Now: naive(now)})
	return n > 0, err
}

// SetLastDispatch is record_dispatch's write; updated_at is left alone.
func (OpenAPI) SetLastDispatch(ctx context.Context, s db.Session, id uuid.UUID, dispatch map[string]any) (bool, error) {
	n, err := New(s.Q()).SetOpenAPILastDispatch(ctx, SetOpenAPILastDispatchParams{
		ID: id, WorkspaceID: s.Workspace().ID(), LastDispatch: jsonObject(dispatch)})
	return n > 0, err
}
