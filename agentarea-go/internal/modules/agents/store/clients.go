package store

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
)

// Clients is the clients table and its link tables.
type Clients struct{}

// ClientRow is a clients row; JSON columns are as stored.
type ClientRow struct {
	ID           uuid.UUID
	WorkspaceID  string
	CreatedBy    string
	Name         string
	Description  *string
	Kind         string
	Models       []byte
	DefaultModel *string
	AllowDomains []byte
	Sandbox      bool
}

// ClientLink is one attached MCP instance or OpenAPI connection; AllowedTools is the JSON as stored.
type ClientLink struct {
	ClientID        uuid.UUID
	TargetID        uuid.UUID
	NamespacePrefix *string
	AllowedTools    []byte
}

// ClientSkillLink is one attached skill of the workspace.
type ClientSkillLink struct {
	ClientID uuid.UUID
	SkillID  uuid.UUID
	Name     string
}

// ClientToolsetLink is one attached platform toolset.
type ClientToolsetLink struct {
	ClientID        uuid.UUID
	Toolset         string
	DisabledMethods []byte
}

func clientRow(r GetClientRow) ClientRow {
	return ClientRow{
		ID: r.ID, WorkspaceID: r.WorkspaceID, CreatedBy: r.CreatedBy, Name: r.Name, Description: fromText(r.Description),
		Kind: r.Kind, Models: r.Models, DefaultModel: fromText(r.DefaultModel), AllowDomains: r.AllowDomains, Sandbox: r.Sandbox,
	}
}

// Insert writes a new client with the column defaults for the rest.
func (Clients) Insert(ctx context.Context, s db.Session, id uuid.UUID, createdBy, name string, description *string, kind string, now time.Time) error {
	return New(s.Q()).InsertClient(ctx, InsertClientParams{
		ID: id, Now: naive(now), WorkspaceID: s.Workspace().ID(), CreatedBy: createdBy, Name: name,
		Description: text(description), Kind: kind,
	})
}

// Get is the workspace's client, false when it has none.
func (Clients) Get(ctx context.Context, s db.Session, id uuid.UUID) (ClientRow, bool, error) {
	r, err := New(s.Q()).GetClient(ctx, GetClientParams{WorkspaceID: s.Workspace().ID(), ID: id})
	if errors.Is(err, pgx.ErrNoRows) {
		return ClientRow{}, false, nil
	}
	if err != nil {
		return ClientRow{}, false, err
	}
	return clientRow(r), true, nil
}

// List is the workspace's clients among ids, newest first.
func (Clients) List(ctx context.Context, s db.Session, ids []uuid.UUID, offset, limit int32) ([]ClientRow, error) {
	rows, err := New(s.Q()).ListClients(ctx, ListClientsParams{WorkspaceID: s.Workspace().ID(), Ids: ids, RowOffset: offset, RowLimit: limit})
	if err != nil {
		return nil, err
	}
	out := make([]ClientRow, len(rows))
	for i, r := range rows {
		out[i] = clientRow(GetClientRow(r))
	}
	return out, nil
}

// Update writes the mutable columns of r.
func (Clients) Update(ctx context.Context, s db.Session, r ClientRow, now time.Time) error {
	return New(s.Q()).UpdateClient(ctx, UpdateClientParams{
		Name: r.Name, Description: text(r.Description), Kind: r.Kind, DefaultModel: text(r.DefaultModel),
		AllowDomains: r.AllowDomains, Sandbox: r.Sandbox, Now: naive(now), WorkspaceID: s.Workspace().ID(), ID: r.ID,
	})
}

// Delete removes the client; the link tables cascade.
func (Clients) Delete(ctx context.Context, s db.Session, id uuid.UUID) (bool, error) {
	n, err := New(s.Q()).DeleteClient(ctx, DeleteClientParams{WorkspaceID: s.Workspace().ID(), ID: id})
	return n > 0, err
}

// AgentCount is how many of the workspace's agents run on the client.
func (Clients) AgentCount(ctx context.Context, s db.Session, id uuid.UUID) (int64, error) {
	return New(s.Q()).CountClientAgents(ctx, CountClientAgentsParams{WorkspaceID: s.Workspace().ID(), ClientID: uuid.NullUUID{UUID: id, Valid: true}})
}

// Skills are the attached skills of the workspace, per client.
func (Clients) Skills(ctx context.Context, s db.Session, ids []uuid.UUID) ([]ClientSkillLink, error) {
	rows, err := New(s.Q()).ClientSkillLinks(ctx, ClientSkillLinksParams{WorkspaceID: s.Workspace().ID(), Ids: ids})
	if err != nil {
		return nil, err
	}
	out := make([]ClientSkillLink, len(rows))
	for i, r := range rows {
		out[i] = ClientSkillLink{ClientID: r.ClientID, SkillID: r.ID, Name: r.Name}
	}
	return out, nil
}

// MCPInstances are the attached MCP instance links, per client.
func (Clients) MCPInstances(ctx context.Context, s db.Session, ids []uuid.UUID) ([]ClientLink, error) {
	rows, err := New(s.Q()).ClientMCPInstanceLinks(ctx, ClientMCPInstanceLinksParams{WorkspaceID: s.Workspace().ID(), Ids: ids})
	if err != nil {
		return nil, err
	}
	out := make([]ClientLink, len(rows))
	for i, r := range rows {
		out[i] = ClientLink{ClientID: r.ClientID, TargetID: r.McpInstanceID, NamespacePrefix: fromText(r.NamespacePrefix), AllowedTools: r.AllowedTools}
	}
	return out, nil
}

// OpenAPIConnections are the attached OpenAPI connection links, per client.
func (Clients) OpenAPIConnections(ctx context.Context, s db.Session, ids []uuid.UUID) ([]ClientLink, error) {
	rows, err := New(s.Q()).ClientOpenAPILinks(ctx, ClientOpenAPILinksParams{WorkspaceID: s.Workspace().ID(), Ids: ids})
	if err != nil {
		return nil, err
	}
	out := make([]ClientLink, len(rows))
	for i, r := range rows {
		out[i] = ClientLink{ClientID: r.ClientID, TargetID: r.OpenapiConnectionID, NamespacePrefix: fromText(r.NamespacePrefix), AllowedTools: r.AllowedTools}
	}
	return out, nil
}

// Toolsets are the attached platform toolsets, per client, by namespace.
func (Clients) Toolsets(ctx context.Context, s db.Session, ids []uuid.UUID) ([]ClientToolsetLink, error) {
	rows, err := New(s.Q()).ClientPlatformToolsetLinks(ctx, ClientPlatformToolsetLinksParams{WorkspaceID: s.Workspace().ID(), Ids: ids})
	if err != nil {
		return nil, err
	}
	out := make([]ClientToolsetLink, len(rows))
	for i, r := range rows {
		out[i] = ClientToolsetLink(r)
	}
	return out, nil
}

// AddSkill links a skill; linking it twice changes nothing.
func (Clients) AddSkill(ctx context.Context, s db.Session, client, skill uuid.UUID) error {
	return New(s.Q()).AddClientSkill(ctx, AddClientSkillParams{ClientID: client, SkillID: skill})
}

// RemoveSkill unlinks a skill.
func (Clients) RemoveSkill(ctx context.Context, s db.Session, client, skill uuid.UUID) error {
	return New(s.Q()).RemoveClientSkill(ctx, RemoveClientSkillParams{ClientID: client, SkillID: skill})
}

// SetMCPInstance attaches an instance or replaces how an attached one is served.
func (Clients) SetMCPInstance(ctx context.Context, s db.Session, client, instance uuid.UUID, prefix *string, allowed []byte) error {
	return New(s.Q()).SetClientMCPInstance(ctx, SetClientMCPInstanceParams{
		ClientID: client, McpInstanceID: instance, NamespacePrefix: text(prefix), AllowedTools: allowed})
}

// RemoveMCPInstance detaches an instance.
func (Clients) RemoveMCPInstance(ctx context.Context, s db.Session, client, instance uuid.UUID) error {
	return New(s.Q()).RemoveClientMCPInstance(ctx, RemoveClientMCPInstanceParams{ClientID: client, McpInstanceID: instance})
}

// SetOpenAPIConnection attaches a connection or replaces how an attached one is served.
func (Clients) SetOpenAPIConnection(ctx context.Context, s db.Session, client, conn uuid.UUID, prefix *string, allowed []byte) error {
	return New(s.Q()).SetClientOpenAPIConnection(ctx, SetClientOpenAPIConnectionParams{
		ClientID: client, OpenapiConnectionID: conn, NamespacePrefix: text(prefix), AllowedTools: allowed})
}

// RemoveOpenAPIConnection detaches a connection.
func (Clients) RemoveOpenAPIConnection(ctx context.Context, s db.Session, client, conn uuid.UUID) error {
	return New(s.Q()).RemoveClientOpenAPIConnection(ctx, RemoveClientOpenAPIConnectionParams{ClientID: client, OpenapiConnectionID: conn})
}

// SetToolset attaches a platform toolset or replaces the methods it leaves out.
func (Clients) SetToolset(ctx context.Context, s db.Session, client uuid.UUID, toolset string, disabled []byte) error {
	return New(s.Q()).SetClientPlatformToolset(ctx, SetClientPlatformToolsetParams{ClientID: client, Toolset: toolset, DisabledMethods: disabled})
}

// RemoveToolset detaches a platform toolset by namespace.
func (Clients) RemoveToolset(ctx context.Context, s db.Session, client uuid.UUID, toolset string) error {
	return New(s.Q()).RemoveClientPlatformToolset(ctx, RemoveClientPlatformToolsetParams{ClientID: client, Toolset: toolset})
}
