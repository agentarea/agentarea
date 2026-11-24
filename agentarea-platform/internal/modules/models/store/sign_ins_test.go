package store

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/domain"
)

func TestASecondLockerOfAConfigurationGivesUpAtTheLockTimeout(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s, other := workspace(t, pool), workspace(t, pool)
	var st Store
	c := newConfig(providerSpec(t, pool))
	if err := st.InsertConfig(ctx, s, c, time.Now()); err != nil {
		t.Fatal(err)
	}
	id := uuid.MustParse(c.ID)
	holder, err := pool.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = holder.Rollback(ctx) }()
	if held, err := st.LockConfig(ctx, db.NewTxSession(s.Workspace(), holder), id); err != nil || !held {
		t.Fatalf("holder: %v %v", held, err)
	}
	waiter, err := pool.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = waiter.Rollback(ctx) }()
	start := time.Now()
	_, err = st.LockConfig(ctx, db.NewTxSession(s.Workspace(), waiter), id)
	if !errors.Is(err, ErrLockBusy) || time.Since(start) > 10*time.Second {
		t.Fatalf("waiter: %v after %v", err, time.Since(start))
	}
	another, err := pool.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = another.Rollback(ctx) }()
	if held, err := st.LockConfig(ctx, db.NewTxSession(other.Workspace(), another), id); err != nil || held {
		t.Fatalf("another workspace locked the config: %v %v", held, err)
	}
}

func TestAPendingSignInBelongsToItsMemberAndConfiguration(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s, other := workspace(t, pool), workspace(t, pool)
	var st Store
	c := newConfig(providerSpec(t, pool))
	if err := st.InsertConfig(ctx, s, c, time.Now()); err != nil {
		t.Fatal(err)
	}
	id := uuid.MustParse(c.ID)
	exp := time.Date(2026, 1, 1, 0, 15, 0, 0, time.UTC)
	for _, code := range []string{"OLD", "NEW"} {
		if err := st.PutSignIn(ctx, s, domain.SignIn{ConfigID: c.ID, UserID: "u1", DeviceAuthID: "dev-" + code, UserCode: code, ExpiresAt: exp}); err != nil {
			t.Fatal(err)
		}
	}
	got, ok, err := st.SignIn(ctx, s, id, "u1")
	if err != nil || !ok || got.DeviceAuthID != "dev-NEW" || got.UserCode != "NEW" || !got.ExpiresAt.Equal(exp) {
		t.Fatalf("got %+v %v %v", got, ok, err)
	}
	if _, ok, _ := st.SignIn(ctx, s, id, "u2"); ok {
		t.Fatal("another member read the sign-in")
	}
	if _, ok, _ := st.SignIn(ctx, other, id, "u1"); ok {
		t.Fatal("another workspace read the sign-in")
	}
	if err := st.DeleteSignIn(ctx, s, id, "u1"); err != nil {
		t.Fatal(err)
	}
	if _, ok, _ := st.SignIn(ctx, s, id, "u1"); ok {
		t.Fatal("the sign-in outlived its delete")
	}
}
