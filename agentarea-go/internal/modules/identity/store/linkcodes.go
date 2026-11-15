package store

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/identity/domain"
)

// KV is the one Redis command issuing a link code needs: SET key value EX ttl.
type KV interface {
	SetEX(ctx context.Context, key, value string, ttl time.Duration) error
}

// LinkCodes issues the single-use codes that pair a messenger account with
// the signed-in user (identity/linking.py LinkCodes.issue); only a code's
// digest is stored.
type LinkCodes struct{ KV KV }

// LinkCodePrefix is where codes live in Redis.
const LinkCodePrefix = "identity:link:code"

// Issue stores a fresh code for userID and returns it.
func (l LinkCodes) Issue(ctx context.Context, userID string) (string, error) {
	raw := make([]byte, 24)
	if _, err := rand.Read(raw); err != nil {
		return "", err
	}
	code := base64.RawURLEncoding.EncodeToString(raw)
	sum := sha256.Sum256([]byte(code))
	return code, l.KV.SetEX(ctx, LinkCodePrefix+":"+hex.EncodeToString(sum[:]), userID, domain.LinkTTLSeconds*time.Second)
}
