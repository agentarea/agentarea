package domain

import "errors"

// Project is a workspace's grouping of agents, skills and MCP instances
// (agentarea_projects/domain/models.py). Ids are canonical UUID strings.
type Project struct {
	ID              string
	WorkspaceID     string
	CreatedBy       string
	Name            string
	Description     *string
	Instructions    *string
	ParentProjectID *string
	Skills          []Ref
	MCPInstances    []Ref
	Agents          []Ref
}

// Ref is a linked child the project's workspace can see.
type Ref struct {
	ID   string
	Name string
}

// Links are the child ids linked to one project, before visibility.
type Links struct {
	Skills       []string
	MCPInstances []string
	Agents       []string
}

// New is ProjectCreate after validation: Name is stripped and non-empty.
type New struct {
	Name            string
	Description     *string
	Instructions    *string
	ParentProjectID *string
}

// Field is a nullable field of a partial update: Set when the key was sent.
type Field struct {
	Set   bool
	Value *string
}

// Patch is ProjectUpdate's exclude_unset dump. Name may be left out but
// never set to null.
type Patch struct {
	Name            *string
	Description     Field
	Instructions    Field
	ParentProjectID Field
}

// Node is a project's name, instructions and parent (get_instructions).
type Node struct {
	Name            string
	Instructions    *string
	ParentProjectID *string
}

// ErrProjectNotFound is the route's HTTPException(404, "Project not found").
var ErrProjectNotFound = errors.New("Project not found")

// NotFoundError is the service's NotFoundError(f"{label} not found").
type NotFoundError struct{ Label string }

func (e *NotFoundError) Error() string { return e.Label + " not found" }

// CycleDetail is the BadRequestError of a parent that would close a cycle.
const CycleDetail = "A project cannot be nested under itself or its own subproject"

// ErrCycle refuses nesting a project under itself or its own subproject.
var ErrCycle = errors.New("project nesting cycle")

// LinkKind names one of a project's link tables.
type LinkKind int

const (
	LinkSkill LinkKind = iota
	LinkMCPInstance
	LinkAgent
)

// Label is the child's name in a NotFoundError.
func (k LinkKind) Label() string {
	switch k {
	case LinkSkill:
		return "Skill"
	case LinkMCPInstance:
		return "MCP instance"
	case LinkAgent:
		return "Agent"
	}
	return "Agent"
}
