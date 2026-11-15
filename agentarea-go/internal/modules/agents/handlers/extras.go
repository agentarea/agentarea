package handlers

import (
	"net/http"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/service"
)

// Extras are the services of the other route groups.
type Extras struct {
	Skills   *service.Skills
	Clients  *service.Clients
	TaskDefs *service.TaskDefs
	A2A      *service.A2A
	Misc     *service.Misc
	// MaxBody bounds a body a handler reads itself: the edge's AGENTAREA_API_MAX_BODY.
	MaxBody int64
}

// Edge is the admission middleware: Workspace admits the caller into
// /v1/workspaces/{workspace}; Principal authenticates outside a workspace.
type Edge struct {
	Workspace func(http.Handler) http.Handler
	Principal func(http.Handler) http.Handler
}

func mapOthers(err error) (*httpx.Error, bool) {
	for _, m := range []func(error) (*httpx.Error, bool){
		mapCollectionError, mapSkillError, mapClientError, mapTaskDefError, mapA2AError, mapMiscError,
	} {
		if e, ok := m(err); ok {
			return e, true
		}
	}
	return nil, false
}

func mustUUID(s string) uuid.UUID { return uuid.MustParse(s) }
