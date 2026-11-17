package store

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/domain"
)

// KV is the Redis commands link codes need: SET key value EX ttl, and GETDEL.
type KV interface {
	SetEX(ctx context.Context, key, value string, ttl time.Duration) error
	// GetDel is "" when key is not set.
	GetDel(ctx context.Context, key string) (string, error)
}

// LinkCodes issues the single-use codes that pair a messenger account with
// the signed-in user (identity/linking.py LinkCodes.issue); only a code's
// digest is stored.
type LinkCodes struct{ KV KV }

// Where codes, and redeemed codes waiting for confirmation, live in Redis.
const (
	LinkCodePrefix    = "identity:link:code"
	LinkPendingPrefix = "identity:link:pending"
)

func digest(code string) string {
	sum := sha256.Sum256([]byte(code))
	return hex.EncodeToString(sum[:])
}

// Issue stores a fresh code for userID and returns it.
func (l LinkCodes) Issue(ctx context.Context, userID string) (string, error) {
	raw := make([]byte, 24)
	if _, err := rand.Read(raw); err != nil {
		return "", err
	}
	code := base64.RawURLEncoding.EncodeToString(raw)
	return code, l.KV.SetEX(ctx, LinkCodePrefix+":"+digest(code), userID, domain.LinkTTLSeconds*time.Second)
}

// Redeem spends code from externalID; the user it was issued to then waits for the account's
// confirmation.
func (l LinkCodes) Redeem(ctx context.Context, code, provider, externalID string) (string, bool, error) {
	userID, err := l.KV.GetDel(ctx, LinkCodePrefix+":"+digest(code))
	if err != nil || userID == "" {
		return "", false, err
	}
	if err := l.KV.SetEX(ctx, pendingKey(provider, externalID), userID, domain.LinkTTLSeconds*time.Second); err != nil {
		return "", false, err
	}
	return userID, true, nil
}

// Confirm consumes the user externalID redeemed a code for.
func (l LinkCodes) Confirm(ctx context.Context, provider, externalID string) (string, bool, error) {
	userID, err := l.KV.GetDel(ctx, pendingKey(provider, externalID))
	return userID, err == nil && userID != "", err
}

func pendingKey(provider, externalID string) string {
	return LinkPendingPrefix + ":" + provider + ":" + externalID
}
