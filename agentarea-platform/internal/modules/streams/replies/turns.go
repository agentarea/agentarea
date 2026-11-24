package replies

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/redis/go-redis/v9"
)

const (
	turnPrefix = "reply:turn:"
	turnTTL    = 24 * time.Hour
)

// TurnAddresses is the delivery address of the message that started a task's current turn.
type TurnAddresses interface {
	// Address is false while no follow-up has been routed into the task.
	Address(ctx context.Context, taskID string) (map[string]any, bool, error)
}

// Turns keeps, under reply:turn:<task>, the delivery address of the last follow-up a session
// routed into a running task: the task's own address is the message that started it, and each
// later turn is answered at the message that started that turn.
type Turns struct{ Redis *redis.Client }

var _ TurnAddresses = Turns{}

// Begin records address as where the task's current turn replies.
func (t Turns) Begin(ctx context.Context, taskID string, address map[string]any) error {
	raw, err := json.Marshal(address)
	if err != nil {
		return fmt.Errorf("turn address of task %s: %w", taskID, err)
	}
	return t.Redis.Set(ctx, turnPrefix+taskID, raw, turnTTL).Err()
}

func (t Turns) Address(ctx context.Context, taskID string) (map[string]any, bool, error) {
	raw, err := t.Redis.Get(ctx, turnPrefix+taskID).Bytes()
	if errors.Is(err, redis.Nil) {
		return nil, false, nil
	}
	if err != nil {
		return nil, false, fmt.Errorf("turn address of task %s: %w", taskID, err)
	}
	var address map[string]any
	d := json.NewDecoder(bytes.NewReader(raw))
	d.UseNumber()
	if err := d.Decode(&address); err != nil {
		return nil, false, fmt.Errorf("turn address of task %s: %w", taskID, err)
	}
	return address, true, nil
}
