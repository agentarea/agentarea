package store

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/projects/domain"
)

//go:generate sqlc generate

// Projects reads and writes projects and their link rows inside the
// session's workspace.
type Projects struct{}

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

// naive is a timestamp without time zone holding t's wall clock, as
// Python's datetime.now() writes it.
func naive(t time.Time) pgtype.Timestamp {
	return pgtype.Timestamp{Time: t.Truncate(time.Microsecond), Valid: true}
}

func project(id uuid.UUID, ws, by, name string, desc, instr pgtype.Text, parent uuid.NullUUID) domain.Project {
	return domain.Project{
		ID: id.String(), WorkspaceID: ws, CreatedBy: by, Name: name,
		Description: fromText(desc), Instructions: fromText(instr), ParentProjectID: fromNullUUID(parent),
	}
}

// Create inserts a project with the given id, attributed to createdBy.
func (Projects) Create(ctx context.Context, s db.Session, id uuid.UUID, createdBy string, n domain.New, now time.Time) (domain.Project, error) {
	parent, err := nullUUID(n.ParentProjectID)
	if err != nil {
		return domain.Project{}, err
	}
	r, err := New(s.Q()).CreateProject(ctx, CreateProjectParams{
		ID: id, Now: naive(now), WorkspaceID: s.Workspace().ID(), CreatedBy: createdBy, Name: n.Name,
		Description: text(n.Description), Instructions: text(n.Instructions), ParentProjectID: parent,
	})
	if err != nil {
		return domain.Project{}, err
	}
	return project(r.ID, r.WorkspaceID, r.CreatedBy, r.Name, r.Description, r.Instructions, r.ParentProjectID), nil
}

// Get is the project, false when the workspace has none with this id.
func (Projects) Get(ctx context.Context, s db.Session, id uuid.UUID) (domain.Project, bool, error) {
	r, err := New(s.Q()).GetProject(ctx, GetProjectParams{WorkspaceID: s.Workspace().ID(), ID: id})
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.Project{}, false, nil
	}
	if err != nil {
		return domain.Project{}, false, err
	}
	return project(r.ID, r.WorkspaceID, r.CreatedBy, r.Name, r.Description, r.Instructions, r.ParentProjectID), true, nil
}

// List is a page of the workspace's projects, in no particular order.
func (Projects) List(ctx context.Context, s db.Session, limit, offset int32) ([]domain.Project, error) {
	rows, err := New(s.Q()).ListProjects(ctx, ListProjectsParams{WorkspaceID: s.Workspace().ID(), Lim: limit, Off: offset})
	if err != nil {
		return nil, err
	}
	out := make([]domain.Project, len(rows))
	for i, r := range rows {
		out[i] = project(r.ID, r.WorkspaceID, r.CreatedBy, r.Name, r.Description, r.Instructions, r.ParentProjectID)
	}
	return out, nil
}

// Node is the project's name, instructions and parent, false when absent.
func (Projects) Node(ctx context.Context, s db.Session, id uuid.UUID) (domain.Node, bool, error) {
	r, err := New(s.Q()).GetInstructions(ctx, GetInstructionsParams{WorkspaceID: s.Workspace().ID(), ID: id})
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.Node{}, false, nil
	}
	if err != nil {
		return domain.Node{}, false, err
	}
	return domain.Node{Name: r.Name, Instructions: fromText(r.Instructions), ParentProjectID: fromNullUUID(r.ParentProjectID)}, true, nil
}

// Update writes the fields p sets; updated_at moves only when a value
// changes. It reports false when the workspace has no such project.
func (Projects) Update(ctx context.Context, s db.Session, id uuid.UUID, p domain.Patch, now time.Time) (bool, error) {
	parent, err := nullUUID(p.ParentProjectID.Value)
	if err != nil {
		return false, err
	}
	arg := UpdateProjectParams{
		SetName:         p.Name != nil,
		SetDescription:  p.Description.Set,
		Description:     text(p.Description.Value),
		SetInstructions: p.Instructions.Set,
		Instructions:    text(p.Instructions.Value),
		SetParent:       p.ParentProjectID.Set,
		ParentProjectID: parent,
		Now:             naive(now),
		WorkspaceID:     s.Workspace().ID(),
		ID:              id,
	}
	if p.Name != nil {
		arg.Name = *p.Name
	}
	_, err = New(s.Q()).UpdateProject(ctx, arg)
	if errors.Is(err, pgx.ErrNoRows) {
		return false, nil
	}
	return err == nil, err
}

// Delete removes the project; children are re-parented to NULL and link
// rows go with it (FK actions). It reports false when there was none.
func (Projects) Delete(ctx context.Context, s db.Session, id uuid.UUID) (bool, error) {
	n, err := New(s.Q()).DeleteProject(ctx, DeleteProjectParams{WorkspaceID: s.Workspace().ID(), ID: id})
	return n > 0, err
}
