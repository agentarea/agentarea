// Package quota is the workspace event write quota, counted in Redis where events enter, over
// a sliding minute (infrastructure/write_quota.py).
package quota

import (
	"context"
	"errors"
	"math"
	"strconv"
	"time"

	"github.com/redis/go-redis/v9"
)

const window = 60

// WriteQuota counts this minute's events plus the previous minute's, weighted by how much of it
// the sliding window still covers.
type WriteQuota struct {
	rdb    *redis.Client
	prefix string
	now    func() time.Time
}

// New builds the quota under namespace (AGENTAREA_EVENT_NAMESPACE).
func New(rdb *redis.Client, namespace string) (*WriteQuota, error) {
	if rdb == nil {
		return nil, errors.New("WriteQuota needs a Redis client")
	}
	if namespace == "" {
		return nil, errors.New("WriteQuota needs a namespace (AGENTAREA_EVENT_NAMESPACE)")
	}
	return &WriteQuota{rdb: rdb, prefix: namespace + ".quota.stream-writes", now: time.Now}, nil
}

// Admit counts one event for the workspace; false, uncounted, when it would pass limit.
func (q *WriteQuota) Admit(ctx context.Context, workspaceID string, limit int) (bool, error) {
	return q.take(ctx, workspaceID, limit, q.now())
}

func (q *WriteQuota) take(ctx context.Context, workspaceID string, limit int, now time.Time) (bool, error) {
	secs := float64(now.UnixNano()) / 1e9
	minute := int64(math.Floor(secs)) / window
	key := q.prefix + ":" + workspaceID + ":" + strconv.FormatInt(minute, 10)
	prev := q.prefix + ":" + workspaceID + ":" + strconv.FormatInt(minute-1, 10)
	var incr *redis.IntCmd
	var get *redis.StringCmd
	_, err := q.rdb.TxPipelined(ctx, func(p redis.Pipeliner) error {
		incr = p.Incr(ctx, key)
		p.Expire(ctx, key, 2*window*time.Second)
		get = p.Get(ctx, prev)
		return nil
	})
	if err != nil && !errors.Is(err, redis.Nil) {
		return false, err
	}
	previous := 0
	if v, gerr := get.Result(); gerr == nil {
		previous, _ = strconv.Atoi(v)
	}
	covered := 1 - math.Mod(secs, window)/window
	if float64(incr.Val())+float64(previous)*covered > float64(limit) {
		if err := q.rdb.Decr(ctx, key).Err(); err != nil {
			return false, err
		}
		return false, nil
	}
	return true, nil
}
