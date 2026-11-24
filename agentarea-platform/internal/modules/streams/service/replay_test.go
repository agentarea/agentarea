package service_test

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/service"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/store"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/store/storetest"
)

func TestAReplayedEventArrivesAgainAsItCame(t *testing.T) {
	pool := storetest.Pool(t)
	ws := storetest.Workspace(t, pool)
	ctx, c := storetest.Caller(context.Background(), ws, "owner")
	graph, bus := &storetest.Graph{AllowAll: true}, &storetest.Bus{}
	svc := service.New(service.Deps{DB: storetest.DB{Pool: pool}, Graph: graph, Bus: bus, Dedup: &storetest.Dedup{},
		Quota: &storetest.Quota{}, Settings: service.DefaultSettings()})
	st, err := svc.CreateStream(ctx, "tg-"+uuid.NewString()[:8], "")
	if err != nil {
		t.Fatal(err)
	}
	streamID := st.ID
	session, sender, source, slug, size := "42", "tg:42", uuid.NewString(), "telegram", int64(20155031)
	orig := domain.Event{ID: uuid.NewString(), Kind: "message", Source: "/sources/" + source, OccurredAt: time.Now().UTC().Add(-time.Hour),
		Data: map[string]any{"body": map[string]any{"message": map[string]any{"caption": "Сделай субтитры."}}}, StreamID: streamID,
		WorkspaceID: c.Workspace.ID(), CreatedBy: "owner", EventKey: "update:1", ReceivedAt: time.Now().UTC().Add(-time.Hour),
		SourceID: &source, SourceType: &slug, SessionKey: &session, Sender: &sender,
		Attachments: []domain.Attachment{{Name: "IMG_6110.MOV", Size: &size, Ref: `{"fetch":"telegram.getFile","item":{"file_id":"F1"}}`}}}
	if _, err := (store.Streams{}).RecordEvent(ctx, db.NewSession(c.Workspace, pool), orig); err != nil {
		t.Fatal(err)
	}
	out, err := svc.ReplayEvent(ctx, orig.ID)
	if err != nil {
		t.Fatal(err)
	}
	if out.Of != orig.ID || out.StreamID != streamID || out.EventID == orig.ID {
		t.Fatalf("replayed %+v", out)
	}
	published := bus.Events()
	if len(published) != 1 {
		t.Fatalf("published %d", len(published))
	}
	e := published[0].Event
	if e.ID != out.EventID || e.CausationID != orig.ID || e.Extensions["sessionkey"] != session || e.Extensions["sender"] != sender ||
		e.Extensions["sourceid"] != source || !strings.Contains(e.Extensions["attachments"], "IMG_6110.MOV") ||
		!strings.HasPrefix(e.Extensions["eventkey"], "replay:"+orig.ID+":") {
		t.Fatalf("the copy is not the event as it came: %+v", e)
	}
	if at, _ := time.Parse(time.RFC3339Nano, e.Extensions["receivedat"]); time.Since(at) > time.Minute {
		t.Fatalf("the copy is received now, not %s", e.Extensions["receivedat"])
	}
	if _, err := svc.ReplayEvent(ctx, uuid.NewString()); !errors.Is(err, domain.ErrEventNotFound) {
		t.Fatalf("an unknown event: %v", err)
	}
	graph.AllowAll = false
	if _, err := svc.ReplayEvent(ctx, orig.ID); err == nil {
		t.Fatal("a caller who cannot edit the stream replayed its event")
	}
}
