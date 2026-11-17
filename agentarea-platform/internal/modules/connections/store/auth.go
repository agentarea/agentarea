package store

import (
	"context"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/domain"
)

// Auth is the mcp_auth_configs repository. Every method runs in the session's
// workspace.
type Auth struct{}

func authFrom(r McpAuthConfig) (domain.AuthConfig, error) {
	cfg, err := jsonMap(r.Config)
	if err != nil {
		return domain.AuthConfig{}, err
	}
	return domain.AuthConfig{
		ID: r.ID.String(), WorkspaceID: r.WorkspaceID, CreatedBy: r.CreatedBy,
		Name: r.Name, Description: fromText(r.Description), AuthType: r.AuthType, Config: cfg,
		SecretKey: fromText(r.SecretKey), OpenAPIConnID: fromNullUUID(r.OpenapiConnectionID),
		MCPInstanceID: fromNullUUID(r.McpInstanceID),
		CreatedAt:     fromTimestamp(r.CreatedAt), UpdatedAt: fromTimestamp(r.UpdatedAt),
	}, nil
}

func authsFrom(rows []McpAuthConfig) ([]domain.AuthConfig, error) {
	out := make([]domain.AuthConfig, 0, len(rows))
	for _, r := range rows {
		a, err := authFrom(r)
		if err != nil {
			return nil, err
		}
		out = append(out, a)
	}
	return out, nil
}

// List is every auth config of the workspace.
func (Auth) List(ctx context.Context, s db.Session) ([]domain.AuthConfig, error) {
	rows, err := New(s.Q()).ListAuthConfigs(ctx, s.Workspace().ID())
	if err != nil {
		return nil, err
	}
	return authsFrom(rows)
}

// Get is the auth config id of the workspace; false when there is none.
func (Auth) Get(ctx context.Context, s db.Session, id uuid.UUID) (domain.AuthConfig, bool, error) {
	r, err := New(s.Q()).GetAuthConfig(ctx, GetAuthConfigParams{ID: id, WorkspaceID: s.Workspace().ID()})
	if IsNoRows(err) {
		return domain.AuthConfig{}, false, nil
	}
	if err != nil {
		return domain.AuthConfig{}, false, err
	}
	a, err := authFrom(r)
	return a, err == nil, err
}

// OwnedByConnection is the auth configs an OpenAPI connection minted.
func (Auth) OwnedByConnection(ctx context.Context, s db.Session, connectionID uuid.UUID) ([]domain.AuthConfig, error) {
	rows, err := New(s.Q()).ListAuthConfigsOwnedByConnection(ctx, ListAuthConfigsOwnedByConnectionParams{
		WorkspaceID: s.Workspace().ID(), OwnerID: uuid.NullUUID{UUID: connectionID, Valid: true},
	})
	if err != nil {
		return nil, err
	}
	return authsFrom(rows)
}

// Insert writes a new auth config with no credentials stored yet.
func (Auth) Insert(ctx context.Context, s db.Session, id uuid.UUID, createdBy string, n domain.AuthConfigNew, now time.Time) (domain.AuthConfig, error) {
	r, err := New(s.Q()).InsertAuthConfig(ctx, InsertAuthConfigParams{
		ID: id, WorkspaceID: s.Workspace().ID(), CreatedBy: createdBy, AuthType: n.AuthType,
		Config: jsonObject(n.Config), Name: n.Name, Description: text(n.Description), Now: naive(now),
	})
	if err != nil {
		return domain.AuthConfig{}, err
	}
	return authFrom(r)
}

// SetSecretKey records where the credentials are stored.
func (Auth) SetSecretKey(ctx context.Context, s db.Session, id uuid.UUID, key string, now time.Time) error {
	_, err := New(s.Q()).SetAuthConfigSecretKey(ctx, SetAuthConfigSecretKeyParams{
		SecretKey: text(&key), Now: naive(now), ID: id, WorkspaceID: s.Workspace().ID(),
	})
	return err
}

// Update sets the fields given (nil leaves a field as it is).
func (Auth) Update(ctx context.Context, s db.Session, id uuid.UUID, name, description *string, config map[string]any, now time.Time) error {
	p := UpdateAuthConfigFieldsParams{Name: text(name), Description: text(description), Now: naive(now), ID: id, WorkspaceID: s.Workspace().ID()}
	if config != nil {
		p.Config = jsonObject(config)
	}
	_, err := New(s.Q()).UpdateAuthConfigFields(ctx, p)
	return err
}

// Delete removes the row; false when there is none.
func (Auth) Delete(ctx context.Context, s db.Session, id uuid.UUID) (bool, error) {
	n, err := New(s.Q()).DeleteAuthConfig(ctx, DeleteAuthConfigParams{ID: id, WorkspaceID: s.Workspace().ID()})
	return n > 0, err
}

// LinkedInstances are the MCP instances still using the config.
func (Auth) LinkedInstances(ctx context.Context, s db.Session, id uuid.UUID) ([]string, error) {
	ids, err := New(s.Q()).LinkedMCPInstanceIDs(ctx, LinkedMCPInstanceIDsParams{
		AuthConfigID: uuid.NullUUID{UUID: id, Valid: true}, WorkspaceID: s.Workspace().ID(),
	})
	return uuidStrings(ids), err
}

// LinkedConnections are the OpenAPI connections still using the config.
func (Auth) LinkedConnections(ctx context.Context, s db.Session, id uuid.UUID) ([]string, error) {
	ids, err := New(s.Q()).LinkedOpenAPIConnectionIDs(ctx, LinkedOpenAPIConnectionIDsParams{
		AuthConfigID: uuid.NullUUID{UUID: id, Valid: true}, WorkspaceID: s.Workspace().ID(),
	})
	return uuidStrings(ids), err
}

func uuidStrings(ids []uuid.UUID) []string {
	out := make([]string, len(ids))
	for i, id := range ids {
		out[i] = id.String()
	}
	return out
}
