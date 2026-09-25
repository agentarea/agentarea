package mcpgateway

import (
	"context"
	"database/sql"
	"errors"
	"sync"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/models"
	"github.com/google/uuid"
)

type participantStub struct {
	mu      sync.Mutex
	changes []LifecycleChange
	fail    Transition
}

func (p *participantStub) BeforeCommit(_ context.Context, statements TxStatements, change LifecycleChange) error {
	if _, raw := statements.(*sql.Tx); raw {
		return errors.New("participant received the raw transaction")
	}
	if _, commits := statements.(interface{ Commit() error }); commits {
		return errors.New("participant can end the owner's transaction")
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	if change.Transition == p.fail {
		return errors.New("participant refused")
	}
	p.changes = append(p.changes, change)
	return nil
}

func (p *participantStub) generations(transition Transition) []int64 {
	p.mu.Lock()
	defer p.mu.Unlock()
	var generations []int64
	for _, change := range p.changes {
		if change.Transition == transition {
			generations = append(generations, change.Generation)
		}
	}
	return generations
}

func TestLifecycleParticipantSeesGenerationsAcrossWarmRequestsAndReaping(t *testing.T) {
	repository := openRepository(t)
	participant := &participantStub{}
	repository.SetLifecycleParticipant(participant)
	db := openRawDB(t)
	ctx := context.Background()
	instanceID := uuid.NewString()
	seedInstance(t, db, instanceID, "docker")
	for range 4 {
		requestID := uuid.NewString()
		if err := repository.WithInstanceLock(ctx, instanceID, func(ctx context.Context) error {
			if err := repository.MarkStarting(ctx, instanceID); err != nil {
				return err
			}
			return repository.MarkReadyAndBeginRequest(ctx, instanceID, requestID, time.Minute)
		}); err != nil {
			t.Fatal(err)
		}
		if err := repository.FinishRequest(ctx, instanceID, requestID); err != nil {
			t.Fatal(err)
		}
	}
	for _, transition := range []Transition{TransitionStarting, TransitionReady} {
		if generations := participant.generations(transition); len(generations) != 1 || generations[0] != 1 {
			t.Fatalf("warm %s generations = %v", transition, generations)
		}
	}
	if _, err := db.Exec(`UPDATE mcp_runtime_instances SET last_used_at=now()-interval '2 hours' WHERE instance_id=$1::uuid`, instanceID); err != nil {
		t.Fatal(err)
	}
	removed, err := repository.ReapIfIdle(ctx, instanceID, time.Minute, func(context.Context, *models.MCPServerInstance) error { return nil })
	if err != nil || !removed {
		t.Fatalf("reaped=%v err=%v", removed, err)
	}
	if generations := participant.generations(TransitionRetired); len(generations) != 1 || generations[0] != 1 {
		t.Fatalf("reaper retirement = %v", generations)
	}
	if err := repository.MarkStarting(ctx, instanceID); err != nil {
		t.Fatal(err)
	}
	if generations := participant.generations(TransitionStarting); len(generations) != 2 || generations[1] != 2 {
		t.Fatalf("restart generations = %v", generations)
	}
	for _, change := range participant.changes {
		if change.WorkspaceID != "ws-test" || change.InstanceID != instanceID || change.UpdatedAt.IsZero() {
			t.Fatalf("change is not the committed row: %+v", change)
		}
	}
}

func TestLifecycleParticipantFailureRollsBackTransitionAndLease(t *testing.T) {
	repository := openRepository(t)
	participant := &participantStub{fail: TransitionReady}
	repository.SetLifecycleParticipant(participant)
	db := openRawDB(t)
	ctx := context.Background()
	instanceID := uuid.NewString()
	seedInstance(t, db, instanceID, "docker")
	if err := repository.MarkStarting(ctx, instanceID); err != nil {
		t.Fatal(err)
	}
	if err := repository.MarkReadyAndBeginRequest(ctx, instanceID, uuid.NewString(), time.Minute); err == nil {
		t.Fatal("refused transition was committed")
	}
	if state := runtimeState(t, db, instanceID); state != "starting" {
		t.Fatalf("refused transition changed state to %s", state)
	}
	if leases := liveLeases(t, db, instanceID); leases != 0 {
		t.Fatalf("refused transition kept %d request leases", leases)
	}
}
