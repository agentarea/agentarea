package handlers_test

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/handlers"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/service"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/store/storetest"
)

type platformRig struct {
	c       authn.Caller
	graph   *storetest.Graph
	streams api.PlatformStreams
	events  api.PlatformStreamEvents
	trigs   api.PlatformTriggers
}

func newPlatformRig(t *testing.T) platformRig {
	t.Helper()
	pool := storetest.Pool(t)
	ws := storetest.Workspace(t, pool)
	graph := &storetest.Graph{AllowAll: true}
	svc := service.New(service.Deps{DB: storetest.DB{Pool: pool}, Graph: graph, Agents: storetest.Agents{}})
	return platformRig{
		c:     authn.Caller{Principal: authn.Principal{UserID: "u1"}, Workspace: ws},
		graph: graph, streams: handlers.NewPlatformStreams(svc, nil), events: handlers.NewPlatformStreamEvents(svc),
		trigs: handlers.NewPlatformTriggers(svc),
	}
}

func wantErr(t *testing.T, err error, text string) {
	t.Helper()
	if err == nil || !strings.Contains(err.Error(), text) {
		t.Fatalf("err = %v, want %q", err, text)
	}
}

func TestPlatformStreamsRequireAsTheRoutesDo(t *testing.T) {
	g := newPlatformRig(t)
	ctx := context.Background()
	made, err := g.streams.Create(ctx, g.c, "orders", "")
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := json.Marshal(made)
	var st struct {
		ID   string `json:"id"`
		Name string `json:"name"`
	}
	if err := json.Unmarshal(raw, &st); err != nil || st.Name != "orders" {
		t.Fatalf("created %s", raw)
	}
	g.graph.Readable = append(g.graph.Readable, st.ID)

	_, err = g.streams.Get(ctx, g.c, "orders")
	wantErr(t, err, "stream_id must be a UUID")
	_, err = g.streams.Create(ctx, g.c, "", "")
	wantErr(t, err, "name: String should have at least 1 character")
	_, err = g.streams.CreateForward(ctx, g.c, st.ID, nil, nil)
	wantErr(t, err, "output_stream_ids: List should have at least 1 item")

	read, err := g.events.Read(ctx, g.c, "orders", 0, 10, nil)
	if err != nil || read.Stream.ID != st.ID || read.HasMore || read.NextAfter != 0 || read.Untrusted == "" {
		t.Fatalf("read %+v %v", read, err)
	}
	_, err = g.events.Read(ctx, g.c, "nowhere", 0, 10, nil)
	wantErr(t, err, "nowhere")
	if _, err := g.streams.ListEvents(ctx, g.c, api.EventQuery{StreamID: &st.ID, Limit: 10}); err != nil {
		t.Fatal(err)
	}

	g.graph.AllowAll = false
	_, err = g.streams.Get(ctx, g.c, st.ID)
	wantErr(t, err, "Permission denied")
	_, err = g.streams.ListSubscriptions(ctx, g.c, st.ID)
	wantErr(t, err, "Permission denied")
	wantErr(t, g.streams.Delete(ctx, g.c, st.ID), "Permission denied")
	_, err = g.streams.ListEvents(ctx, g.c, api.EventQuery{StreamID: &st.ID, Limit: 10})
	wantErr(t, err, "Permission denied")
	_, err = g.events.Read(ctx, g.c, "orders", 0, 10, nil)
	wantErr(t, err, "Permission denied")

	g.graph.AllowAll = true
	if err := g.streams.Delete(ctx, g.c, st.ID); err != nil {
		t.Fatal(err)
	}
}

func TestPlatformTriggersAnswerMissingTriggers(t *testing.T) {
	g := newPlatformRig(t)
	ctx := context.Background()
	gone := uuid.NewString()
	if _, err := g.trigs.Get(ctx, g.c, gone); !errors.Is(err, api.ErrTriggerNotFound) {
		t.Fatalf("get: %v", err)
	}
	for name, f := range map[string]func(context.Context, authn.Caller, string) (bool, error){
		"delete": g.trigs.Delete, "enable": g.trigs.Enable, "disable": g.trigs.Disable,
	} {
		if ok, err := f(ctx, g.c, gone); ok || err != nil {
			t.Fatalf("%s: %v %v", name, ok, err)
		}
		_, err := f(ctx, g.c, "t1")
		wantErr(t, err, "trigger_id must be a UUID")
	}
	rows, err := g.trigs.History(ctx, g.c, gone, 10, 0)
	if err != nil || len(rows) != 0 {
		t.Fatalf("history %v %v", rows, err)
	}
	expr := "0 9 * * *"
	_, err = g.trigs.Create(ctx, g.c, api.TriggerCreate{Type: "cron", Name: "n", AgentID: uuid.NewString(), CronExpression: &expr, FailureThreshold: 0})
	wantErr(t, err, "failure_threshold: Input should be between 1 and 100")
	_, err = g.trigs.Create(ctx, g.c, api.TriggerCreate{Type: "cron", AgentID: uuid.NewString(), CronExpression: &expr, FailureThreshold: 5})
	wantErr(t, err, "name: String should have at least 1 character")
	sid := "not-a-stream"
	_, err = g.trigs.Create(ctx, g.c, api.TriggerCreate{Type: "stream", Name: "n", AgentID: uuid.NewString(), StreamID: &sid, FailureThreshold: 5})
	wantErr(t, err, "stream_id must be a UUID")
}
