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
		Quota: &storetest.Quota{}, Settings: service.DefaultSettings(), Owners: owners{owner: "owner"}})
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

func TestOnlyItsSenderOrTheOwnerReplaysAnEvent(t *testing.T) {
	pool := storetest.Pool(t)
	ws := storetest.Workspace(t, pool)
	ownerCtx, _ := storetest.Caller(context.Background(), ws, "owner")
	bobCtx, _ := storetest.Caller(context.Background(), ws, "bob")
	secrets, lk := storetest.NewSecrets(), &links{holders: map[string]string{}}
	svc := service.New(service.Deps{DB: storetest.DB{Pool: pool}, Graph: &storetest.Graph{AllowAll: true},
		SourceTypes: storetest.ShippedSourceTypes(t), Secrets: secrets, SecretCatalog: secrets.Catalog, Blob: &storetest.Blob{},
		Bus: &storetest.Bus{}, Dedup: &storetest.Dedup{}, Quota: &storetest.Quota{}, Out: &botAPI{}, APIURL: "https://api.example.test",
		Links: lk, Owners: owners{owner: "owner"}, Notices: &storetest.Dedup{}, Settings: service.DefaultSettings()})
	st, err := svc.CreateStream(ownerCtx, "tg-"+uuid.NewString()[:8], "")
	if err != nil {
		t.Fatal(err)
	}
	src, _, err := svc.AddSource(ownerCtx, st.ID, service.NewSource{SourceType: "telegram", Kind: "webhook",
		Credentials: map[string]service.Credential{"bot_token": value("TOKEN")}})
	if err != nil {
		t.Fatal(err)
	}
	slug, sender := "telegram", "tg:42"
	e := domain.Event{ID: uuid.NewString(), Kind: "message", Source: "/sources/" + src.ID, OccurredAt: time.Now().UTC(),
		Data: map[string]any{"headers": map[string]any{}, "body": map[string]any{"message": map[string]any{
			"from": map[string]any{"id": 42, "is_bot": false}, "chat": map[string]any{"id": 42, "type": "private"}, "text": "hi"}}},
		StreamID: st.ID, WorkspaceID: ws.ID(), CreatedBy: "owner", EventKey: "update:7", ReceivedAt: time.Now().UTC(),
		SourceID: &src.ID, SourceType: &slug, Sender: &sender}
	if _, err := (store.Streams{}).RecordEvent(ownerCtx, db.NewSession(ws, pool), e); err != nil {
		t.Fatal(err)
	}
	if _, err := svc.ReplayEvent(bobCtx, e.ID); err == nil || !strings.Contains(err.Error(), "Only the person who sent this event") {
		t.Fatalf("an editor who is not the sender replayed it: %v", err)
	}
	lk.holders["42"] = "bob"
	if _, err := svc.ReplayEvent(bobCtx, e.ID); err != nil {
		t.Fatalf("the sender may replay their own message: %v", err)
	}
	if _, err := svc.ReplayEvent(ownerCtx, e.ID); err != nil {
		t.Fatalf("the owner may replay any event: %v", err)
	}
}
