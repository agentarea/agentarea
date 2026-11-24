package store_test

import (
	"context"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/store"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/store/storetest"
)

func TestPollingRecordsWhatThePollersDid(t *testing.T) {
	ctx := context.Background()
	pool := storetest.Pool(t)
	ws := storetest.Workspace(t, pool)
	stream, poll, hook, bad := uuid.New(), uuid.New(), uuid.New(), uuid.New()
	exec := func(sql string, args ...any) {
		t.Helper()
		if _, err := pool.Exec(ctx, sql, args...); err != nil {
			t.Fatal(err)
		}
	}
	exec(`INSERT INTO streams (id, workspace_id, created_by, name, kind) VALUES ($1, $2, 'u1', 's', 'inbound')`, stream, ws.ID())
	insert := `INSERT INTO stream_sources (id, workspace_id, created_by, stream_id, kind, webhook_id, webhook_type, webhook_config, credential_key, poll_cursor)
		VALUES ($1, $2, 'u1', $3, $4, $5, $6, $7::json, $8, $9)`
	exec(insert, poll, ws.ID(), stream, "poll", nil, "rss", `{"url":"https://feed.example/rss"}`, uuid.New(), "c0")
	exec(insert, hook, ws.ID(), stream, "webhook", "w-"+hook.String()[:8], "telegram", `{}`, uuid.New(), nil)
	exec(insert, bad, ws.ID(), stream, "poll", nil, "rss", `"not an object"`, uuid.New(), nil)

	q := db.NewSession(ws, pool).Q()
	var p store.Polling
	find := func() map[string]store.PolledSource {
		t.Helper()
		rows, badRows, err := p.Sources(ctx, q)
		if err != nil {
			t.Fatal(err)
		}
		out := map[string]store.PolledSource{}
		for _, r := range rows {
			if r.WorkspaceID == ws.ID() {
				out[r.ID] = r
			}
		}
		named := false
		for _, e := range badRows {
			named = named || strings.Contains(e.Error(), bad.String())
		}
		if !named {
			t.Fatalf("the unreadable source is not named: %v", badRows)
		}
		return out
	}
	got := find()
	if len(got) != 2 || got[poll.String()].Config["url"] != "https://feed.example/rss" || got[poll.String()].Cursor != "c0" ||
		got[hook.String()].Slug != "telegram" || got[hook.String()].CredentialKey == "" || got[hook.String()].CreatedBy != "u1" {
		t.Fatalf("sources = %+v", got)
	}

	now := time.Now().UTC().Truncate(time.Microsecond)
	if err := p.Failed(ctx, q, poll.String(), "HTTP 502", now); err != nil {
		t.Fatal(err)
	}
	if err := p.Polled(ctx, q, poll.String(), "", now); err != nil {
		t.Fatal(err)
	}
	if s := find()[poll.String()]; s.Cursor != "c0" || s.PollError != "" || s.PolledAt == nil || !s.PolledAt.Equal(now) {
		t.Fatalf("after an empty poll = %+v", s)
	}
	if err := p.Polled(ctx, q, poll.String(), "c1", now); err != nil {
		t.Fatal(err)
	}
	if s := find()[poll.String()]; s.Cursor != "c1" {
		t.Fatalf("cursor = %q", s.Cursor)
	}

	if err := p.Registered(ctx, q, hook.String(), "https://api.example/webhooks/w1"); err != nil {
		t.Fatal(err)
	}
	if s := find()[hook.String()]; s.RegisteredURL != "https://api.example/webhooks/w1" {
		t.Fatalf("registered = %+v", s)
	}
	retry := now.Add(time.Minute)
	if err := p.SubscribeFailed(ctx, q, hook.String(), "subscription: refused", now, retry); err != nil {
		t.Fatal(err)
	}
	if s := find()[hook.String()]; s.PollError != "subscription: refused" || s.RefreshBefore == nil || !s.RefreshBefore.Equal(retry) {
		t.Fatalf("subscribe failed = %+v", s)
	}
	if err := p.Subscribed(ctx, q, hook.String(), "https://api.example/webhooks/w1", "sub_1", nil, "w0"); err != nil {
		t.Fatal(err)
	}
	if s := find()[hook.String()]; s.SubscriptionID != "sub_1" || s.RefreshBefore != nil || s.PollError != "" || s.Cursor != "w0" {
		t.Fatalf("subscribed = %+v", s)
	}
	if err := p.Registered(ctx, q, hook.String(), ""); err != nil {
		t.Fatal(err)
	}
	if s := find()[hook.String()]; s.RegisteredURL != "" {
		t.Fatalf("unregistered = %+v", s)
	}
}

func TestExternalSubscribersForDelivery(t *testing.T) {
	ctx := context.Background()
	pool := storetest.Pool(t)
	ws := storetest.Workspace(t, pool)
	stream, live, expired := uuid.New(), uuid.New(), uuid.New()
	if _, err := pool.Exec(ctx, `INSERT INTO streams (id, workspace_id, created_by, name, kind) VALUES ($1, $2, 'u1', 's', 'inbound')`, stream, ws.ID()); err != nil {
		t.Fatal(err)
	}
	insert := `INSERT INTO stream_subscriptions (id, workspace_id, created_by, stream_id, kind, external_id, subscriber, callback_url, secret_name, expires_at)
		VALUES ($1, $2, 'u1', $3, 'external', $4, 'u1', 'https://cb.example', $5, $6)`
	if _, err := pool.Exec(ctx, insert, live, ws.ID(), stream, "ext-"+live.String()[:8], "whsec-live", time.Now().Add(time.Hour)); err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(ctx, insert, expired, ws.ID(), stream, "ext-"+expired.String()[:8], "whsec-old", time.Now().Add(-time.Hour)); err != nil {
		t.Fatal(err)
	}
	s := db.NewSession(ws, pool)
	var st store.Streams
	if _, ok, err := st.ExternalSubscription(ctx, s, expired.String()); ok || err != nil {
		t.Fatalf("an expired subscriber is active: %v %v", ok, err)
	}
	sub, ok, err := st.ExternalSubscription(ctx, s, live.String())
	if err != nil || !ok || sub.CallbackURL == nil || *sub.CallbackURL != "https://cb.example" || *sub.SecretName != "whsec-live" {
		t.Fatalf("live = %+v %v %v", sub, ok, err)
	}
	if _, ok, _ := st.ExternalSubscription(ctx, db.NewSession(storetest.Workspace(t, pool), pool), live.String()); ok {
		t.Fatal("another workspace sees the subscriber")
	}

	first := time.Now().UTC().Truncate(time.Microsecond)
	if err := st.RecordDelivery(ctx, s, live.String(), first, "http_5xx"); err != nil {
		t.Fatal(err)
	}
	if err := st.RecordDelivery(ctx, s, live.String(), first.Add(time.Minute), "timeout"); err != nil {
		t.Fatal(err)
	}
	sub, _, _ = st.ExternalSubscription(ctx, s, live.String())
	if sub.LastError == nil || *sub.LastError != "timeout" || sub.FailedSince == nil || !sub.FailedSince.Equal(first) {
		t.Fatalf("after failures = %+v", sub)
	}
	if err := st.RecordDelivery(ctx, s, live.String(), first.Add(2*time.Minute), ""); err != nil {
		t.Fatal(err)
	}
	sub, _, _ = st.ExternalSubscription(ctx, s, live.String())
	if sub.LastError != nil || sub.FailedSince != nil || sub.LastDeliveryAt == nil {
		t.Fatalf("after success = %+v", sub)
	}

	var p store.Polling
	all, err := p.ExpiredExternalSubscriptions(ctx, s.Q())
	if err != nil {
		t.Fatal(err)
	}
	found := false
	for _, e := range all {
		found = found || e.ID == expired.String()
		if e.ID == live.String() {
			t.Fatal("a live subscriber is expired")
		}
	}
	if !found {
		t.Fatal("the expired subscriber is not listed")
	}

	if err := st.MarkSubscriptionFailed(ctx, s, live.String()); err != nil {
		t.Fatal(err)
	}
	if _, ok, _ := st.ExternalSubscription(ctx, s, live.String()); ok {
		t.Fatal("a failed subscriber is still active")
	}
	if gone, err := st.DeleteExternalSubscription(ctx, s, live.String()); !gone || err != nil {
		t.Fatalf("delete = %v %v", gone, err)
	}
	if gone, _ := st.DeleteExternalSubscription(ctx, s, live.String()); gone {
		t.Fatal("deleted twice")
	}
}
