package connections

import (
	"context"
	"errors"
	"time"

	"github.com/redis/go-redis/v9"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/service"
)

// RedisKV is the OAuth state store over Redis; nil client gives nil.
func RedisKV(c *redis.Client) service.KV {
	if c == nil {
		return nil
	}
	return redisKV{c: c}
}

type redisKV struct{ c *redis.Client }

func (k redisKV) SetEx(ctx context.Context, key, value string, ttl time.Duration) error {
	return k.c.Set(ctx, key, value, ttl).Err()
}

func (k redisKV) GetDel(ctx context.Context, key string) (string, bool, error) {
	v, err := k.c.GetDel(ctx, key).Result()
	if errors.Is(err, redis.Nil) {
		return "", false, nil
	}
	if err != nil {
		return "", false, err
	}
	return v, true, nil
}
