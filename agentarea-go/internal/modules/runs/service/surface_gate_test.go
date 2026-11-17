package service

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
)

func TestArgumentsHashIsPythonsCanonicalJSON(t *testing.T) {
	// hashlib.sha256(json.dumps({"b": 1, "a": "é"}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
	if got := ArgumentsHash(map[string]any{"b": 1, "a": "é"}); got != "6d9eb45284090145dc16661b06abe01185a16a7dabba07c992a131bffa6b8114" {
		t.Fatalf("hash %q", got)
	}
	if ArgumentsHash(nil) != ArgumentsHash(map[string]any{}) {
		t.Fatal("no arguments and empty arguments differ")
	}
}

func TestAHeldCallWaitsRunsOnceAndAnswersARejection(t *testing.T) {
	d := openDB(t)
	wsID := uuid.NewString()
	ws, err := scope.NewWorkspace(wsID, "ws-"+wsID[:8])
	if err != nil {
		t.Fatal(err)
	}
	s := NewSurface(SurfaceDeps{DB: d, AppURL: "https://app.example.test", Now: time.Now})
	instance := uuid.NewString()
	call := api.HeldCall{UserID: "u1", MCPInstanceID: instance, Connector: "Mail", Tool: "send", PolicyName: "mail__send",
		Arguments: map[string]any{"to": "a@b.c"}, Reason: "needs a person", Approvers: []string{"user:boss"}}
	gate := func(c api.HeldCall) api.HeldOutcome {
		t.Helper()
		var out api.HeldOutcome
		if err := d.Write(context.Background(), ws, func(ctx context.Context, tx db.Session) error {
			var err error
			out, err = s.Gate(ctx, tx, ws, c)
			return err
		}); err != nil {
			t.Fatal(err)
		}
		return out
	}
	exec := func(q string, args ...any) {
		t.Helper()
		if err := d.Write(context.Background(), ws, func(ctx context.Context, tx db.Session) error {
			_, err := tx.Q().Exec(ctx, q, args...)
			return err
		}); err != nil {
			t.Fatal(err)
		}
	}

	first := gate(call)
	if first.Verdict != api.HeldPending || first.URL != "https://app.example.test/w/"+ws.Slug()+"/approve/"+first.ApprovalID {
		t.Fatalf("first %+v", first)
	}
	if again := gate(call); again.Verdict != api.HeldPending || again.ApprovalID != first.ApprovalID {
		t.Fatalf("the open request was not reused: %+v", again)
	}
	other := call
	other.Arguments = map[string]any{"to": "x@y.z"}
	if o := gate(other); o.ApprovalID == first.ApprovalID {
		t.Fatal("other arguments share an approval")
	}

	exec(`UPDATE tool_call_approvals SET status = 'approved', decided_by = 'boss', decided_at = now() WHERE id = $1`, first.ApprovalID)
	if ran := gate(call); ran.Verdict != api.HeldRun || ran.ApprovalID != first.ApprovalID || ran.DecidedBy != "boss" {
		t.Fatalf("approved %+v", ran)
	}
	next := gate(call)
	if next.Verdict != api.HeldPending || next.ApprovalID == first.ApprovalID {
		t.Fatalf("an approval ran twice: %+v", next)
	}

	exec(`UPDATE tool_call_approvals SET status = 'rejected', decided_by = 'boss', decided_at = now(), comment = 'no' WHERE id = $1`, next.ApprovalID)
	if r := gate(call); r.Verdict != api.HeldRejected || r.Comment == nil || *r.Comment != "no" {
		t.Fatalf("rejected %+v", r)
	}

	platform := api.HeldCall{UserID: "u1", Connector: "AgentArea", Tool: "runs_create", PolicyName: "runs_create", Reason: "r"}
	if p := gate(platform); p.Verdict != api.HeldPending || gate(platform).ApprovalID != p.ApprovalID {
		t.Fatalf("a platform tool's request was not reused: %+v", p)
	}
}
