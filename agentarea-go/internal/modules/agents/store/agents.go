package store

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/domain"
)

// Agents reads and writes agents and their skill links inside the session's workspace.
type Agents struct{}

func text(p *string) pgtype.Text {
	if p == nil {
		return pgtype.Text{}
	}
	return pgtype.Text{String: *p, Valid: true}
}

func fromText(t pgtype.Text) *string {
	if !t.Valid {
		return nil
	}
	s := t.String
	return &s
}

func nullUUID(p *string) (uuid.NullUUID, error) {
	if p == nil {
		return uuid.NullUUID{}, nil
	}
	u, err := uuid.Parse(*p)
	if err != nil {
		return uuid.NullUUID{}, err
	}
	return uuid.NullUUID{UUID: u, Valid: true}, nil
}

func fromNullUUID(u uuid.NullUUID) *string {
	if !u.Valid {
		return nil
	}
	s := u.UUID.String()
	return &s
}

// naive is a timestamp without time zone holding t's wall clock, as Python's datetime.now() writes it.
func naive(t time.Time) pgtype.Timestamp {
	return pgtype.Timestamp{Time: t.Truncate(time.Microsecond), Valid: true}
}

func agent(r GetAgentRow) domain.Agent {
	a := domain.Agent{
		ID: r.ID.String(), WorkspaceID: r.WorkspaceID, CreatedBy: r.CreatedBy, Name: r.Name, Slug: r.Slug,
		Status: r.Status, Description: fromText(r.Description), Instruction: fromText(r.Instruction),
		ModelID: fromText(r.ModelID), ClientID: fromNullUUID(r.ClientID), HarnessClientID: fromNullUUID(r.HarnessClientID),
		Tools: r.Tools, AnswerCheck: r.AnswerCheck, AgentType: r.AgentType, RegistryItemID: fromText(r.RegistryItemID),
	}
	if r.Planning.Valid {
		v := r.Planning.Bool
		a.Planning = &v
	}
	if r.A2uiEnabled.Valid {
		v := r.A2uiEnabled.Bool
		a.A2UIEnabled = &v
	}
	a.ReasoningEffort = fromText(r.ReasoningEffort)
	if r.ReasoningMaxTokens.Valid {
		v := r.ReasoningMaxTokens.Int32
		a.ReasoningMaxTokens = &v
	}
	return a
}

func pgBool(b *bool) pgtype.Bool {
	if b == nil {
		return pgtype.Bool{}
	}
	return pgtype.Bool{Bool: *b, Valid: true}
}

func pgInt4(i *int32) pgtype.Int4 {
	if i == nil {
		return pgtype.Int4{}
	}
	return pgtype.Int4{Int32: *i, Valid: true}
}

// Insert writes a new agent row (id given, attributed to createdBy).
func (Agents) Insert(ctx context.Context, s db.Session, createdBy string, a domain.Agent, now time.Time) error {
	id, err := uuid.Parse(a.ID)
	if err != nil {
		return err
	}
	client, err := nullUUID(a.ClientID)
	if err != nil {
		return err
	}
	harness, err := nullUUID(a.HarnessClientID)
	if err != nil {
		return err
	}
	return New(s.Q()).InsertAgent(ctx, InsertAgentParams{
		ID: id, Now: naive(now), WorkspaceID: s.Workspace().ID(), CreatedBy: createdBy, Name: a.Name, Slug: a.Slug,
		Status: a.Status, Description: text(a.Description), Instruction: text(a.Instruction), ModelID: text(a.ModelID),
		ClientID: client, HarnessClientID: harness, Tools: a.Tools, Planning: pgBool(a.Planning), A2uiEnabled: pgBool(a.A2UIEnabled),
		ReasoningEffort: text(a.ReasoningEffort), ReasoningMaxTokens: pgInt4(a.ReasoningMaxTokens), AnswerCheck: a.AnswerCheck,
		AgentType: a.AgentType, RegistryItemID: text(a.RegistryItemID),
	})
}

// Get is the agent, false when the workspace has none.
func (Agents) Get(ctx context.Context, s db.Session, id uuid.UUID) (domain.Agent, bool, error) {
	r, err := New(s.Q()).GetAgent(ctx, GetAgentParams{WorkspaceID: s.Workspace().ID(), ID: id})
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.Agent{}, false, nil
	}
	if err != nil {
		return domain.Agent{}, false, err
	}
	return agent(r), true, nil
}

// BySlug is get_by_slug.
func (Agents) BySlug(ctx context.Context, s db.Session, slug string) (domain.Agent, bool, error) {
	r, err := New(s.Q()).GetAgentBySlug(ctx, GetAgentBySlugParams{WorkspaceID: s.Workspace().ID(), Slug: slug})
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.Agent{}, false, nil
	}
	if err != nil {
		return domain.Agent{}, false, err
	}
	return agent(GetAgentRow(r)), true, nil
}

// ByRegistryItem is get_by_registry_item_id.
func (Agents) ByRegistryItem(ctx context.Context, s db.Session, item string) (domain.Agent, bool, error) {
	r, err := New(s.Q()).GetAgentByRegistryItem(ctx, GetAgentByRegistryItemParams{WorkspaceID: s.Workspace().ID(), RegistryItemID: text(&item)})
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.Agent{}, false, nil
	}
	if err != nil {
		return domain.Agent{}, false, err
	}
	return agent(GetAgentRow(r)), true, nil
}

// List is every agent of the workspace, archived and harness agents included, newest first.
func (Agents) List(ctx context.Context, s db.Session) ([]domain.Agent, error) {
	rows, err := New(s.Q()).ListAgents(ctx, s.Workspace().ID())
	if err != nil {
		return nil, err
	}
	out := make([]domain.Agent, len(rows))
	for i, r := range rows {
		out[i] = agent(GetAgentRow(r))
	}
	return out, nil
}

// ByHarnessClient lists the agents standing for a client.
func (Agents) ByHarnessClient(ctx context.Context, s db.Session, client uuid.UUID) ([]domain.Agent, error) {
	rows, err := New(s.Q()).ListAgentsByHarnessClient(ctx, ListAgentsByHarnessClientParams{
		WorkspaceID: s.Workspace().ID(), HarnessClientID: uuid.NullUUID{UUID: client, Valid: true}})
	if err != nil {
		return nil, err
	}
	out := make([]domain.Agent, len(rows))
	for i, r := range rows {
		out[i] = agent(GetAgentRow(r))
	}
	return out, nil
}

// Update writes every mutable column of a.
func (Agents) Update(ctx context.Context, s db.Session, a domain.Agent, now time.Time) error {
	id, err := uuid.Parse(a.ID)
	if err != nil {
		return err
	}
	client, err := nullUUID(a.ClientID)
	if err != nil {
		return err
	}
	return New(s.Q()).UpdateAgent(ctx, UpdateAgentParams{
		Name: a.Name, Description: text(a.Description), Instruction: text(a.Instruction), ModelID: text(a.ModelID),
		ClientID: client, Tools: a.Tools, Planning: pgBool(a.Planning), A2uiEnabled: pgBool(a.A2UIEnabled),
		ReasoningEffort: text(a.ReasoningEffort), ReasoningMaxTokens: pgInt4(a.ReasoningMaxTokens), AnswerCheck: a.AnswerCheck,
		AgentType: a.AgentType, Status: a.Status, Now: naive(now), WorkspaceID: s.Workspace().ID(), ID: id,
	})
}

// Delete removes the row for good.
func (Agents) Delete(ctx context.Context, s db.Session, id uuid.UUID) (bool, error) {
	n, err := New(s.Q()).DeleteAgent(ctx, DeleteAgentParams{WorkspaceID: s.Workspace().ID(), ID: id})
	return n > 0, err
}

// Skills are the agent's skills of this workspace.
func (Agents) Skills(ctx context.Context, s db.Session, id uuid.UUID) ([]domain.SkillRef, error) {
	rows, err := New(s.Q()).AgentSkillRows(ctx, AgentSkillRowsParams{AgentID: id, WorkspaceID: s.Workspace().ID()})
	if err != nil {
		return nil, err
	}
	out := make([]domain.SkillRef, len(rows))
	for i, r := range rows {
		out[i] = domain.SkillRef{ID: r.ID.String(), Name: r.Name, Description: fromText(r.Description),
			SourceType: r.SourceType, Package: fromText(r.S3Path), RegistryItemID: fromNullUUID(r.RegistryItemID)}
	}
	return out, nil
}

// SetSkills replaces the agent's skill links.
func (Agents) SetSkills(ctx context.Context, s db.Session, id uuid.UUID, skills []uuid.UUID, now time.Time) error {
	q := New(s.Q())
	if err := q.DeleteAgentSkills(ctx, id); err != nil {
		return err
	}
	for _, sk := range skills {
		if err := q.InsertAgentSkill(ctx, InsertAgentSkillParams{AgentID: id, SkillID: sk, Now: naive(now)}); err != nil {
			return err
		}
	}
	return nil
}

// ClientSummary is a client as an agent response names it.
type ClientSummary struct {
	ID           string
	Name         string
	Kind         string
	DefaultModel *string
}

// Clients reads the named clients of the workspace.
func (Agents) Clients(ctx context.Context, s db.Session, ids []uuid.UUID) (map[string]ClientSummary, error) {
	rows, err := New(s.Q()).ClientsForAgents(ctx, ClientsForAgentsParams{WorkspaceID: s.Workspace().ID(), Ids: ids})
	if err != nil {
		return nil, err
	}
	out := map[string]ClientSummary{}
	for _, r := range rows {
		out[r.ID.String()] = ClientSummary{ID: r.ID.String(), Name: r.Name, Kind: r.Kind, DefaultModel: fromText(r.DefaultModel)}
	}
	return out, nil
}
