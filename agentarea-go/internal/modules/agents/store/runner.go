package store

import (
	"context"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
)

// RecordRunnerHello writes what a runner said on hello: models when setModels,
// the default model only while the client has none; false when the client is gone.
func (Clients) RecordRunnerHello(ctx context.Context, s db.Session, id uuid.UUID, setModels bool, models []byte, defaultModel *string, now time.Time) (bool, error) {
	n, err := New(s.Q()).RecordRunnerHello(ctx, RecordRunnerHelloParams{
		SetModels: setModels, Models: models, DefaultModel: text(defaultModel), Now: naive(now),
		WorkspaceID: s.Workspace().ID(), ID: id,
	})
	return n > 0, err
}
