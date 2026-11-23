package store

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/domain"
)

// KV is the Redis commands link codes need: SET key value EX ttl (NX), GET, GETDEL and DEL.
type KV interface {
	SetEX(ctx context.Context, key, value string, ttl time.Duration) error
	// SetNX sets key only when it is not set; false when it was.
	SetNX(ctx context.Context, key, value string, ttl time.Duration) (bool, error)
	// Get is "" when key is not set.
	Get(ctx context.Context, key string) (string, error)
	// GetDel is "" when key is not set.
	GetDel(ctx context.Context, key string) (string, error)
	Del(ctx context.Context, key string) error
}

// LinkCodes issues the single-use codes that pair a messenger account with
// the signed-in user (identity/linking.py LinkCodes.issue); only a code's
// digest is stored.
type LinkCodes struct{ KV KV }

// Where codes, and redeemed codes waiting for confirmation, live in Redis.
const (
	LinkCodePrefix    = "identity:link:code"
	LinkPendingPrefix = "identity:link:pending"
	LinkOfferPrefix   = "identity:link:offer"
	// LinkOfferedPrefix names, per account and source, the digest of the code last offered.
	LinkOfferedPrefix = "identity:link:offered"
)

func digest(code string) string {
	sum := sha256.Sum256([]byte(code))
	return hex.EncodeToString(sum[:])
}

func newCode() (string, error) {
	raw := make([]byte, 24)
	if _, err := rand.Read(raw); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(raw), nil
}

// Issue stores a fresh code for userID and returns it.
func (l LinkCodes) Issue(ctx context.Context, userID string) (string, error) {
	code, err := newCode()
	if err != nil {
		return "", err
	}
	return code, l.KV.SetEX(ctx, LinkCodePrefix+":"+digest(code), userID, domain.LinkTTLSeconds*time.Second)
}

// Offer stores a fresh code, good for ttl, that names the account a bot offered it to. While a
// code offered to the same account through the same source is still unspent, none is issued
// and issued is false.
func (l LinkCodes) Offer(ctx context.Context, o domain.LinkOffer, ttl time.Duration) (string, bool, error) {
	code, err := newCode()
	if err != nil {
		return "", false, err
	}
	raw, err := json.Marshal(o)
	if err != nil {
		return "", false, err
	}
	d := digest(code)
	key := LinkOfferPrefix + ":" + d
	if err := l.KV.SetEX(ctx, key, string(raw), ttl); err != nil {
		return "", false, err
	}
	offered := LinkOfferedPrefix + ":" + o.Provider + ":" + o.ExternalID + ":" + o.SourceID
	first, err := l.KV.SetNX(ctx, offered, d, ttl)
	if err != nil || first {
		return code, err == nil, err
	}
	prev, err := l.KV.Get(ctx, offered)
	if err != nil {
		return "", false, err
	}
	live := ""
	if prev != "" {
		if live, err = l.KV.Get(ctx, LinkOfferPrefix+":"+prev); err != nil {
			return "", false, err
		}
	}
	if live != "" {
		return "", false, l.KV.Del(ctx, key)
	}
	return code, true, l.KV.SetEX(ctx, offered, d, ttl)
}

// PeekOffer is the account code was offered to, leaving the code in place.
func (l LinkCodes) PeekOffer(ctx context.Context, code string) (domain.LinkOffer, bool, error) {
	raw, err := l.KV.Get(ctx, LinkOfferPrefix+":"+digest(code))
	return offer(raw, err)
}

// TakeOffer spends code and returns the account it was offered to.
func (l LinkCodes) TakeOffer(ctx context.Context, code string) (domain.LinkOffer, bool, error) {
	raw, err := l.KV.GetDel(ctx, LinkOfferPrefix+":"+digest(code))
	return offer(raw, err)
}

func offer(raw string, err error) (domain.LinkOffer, bool, error) {
	var o domain.LinkOffer
	if err != nil || raw == "" {
		return o, false, err
	}
	if err := json.Unmarshal([]byte(raw), &o); err != nil {
		return o, false, err
	}
	return o, true, nil
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
