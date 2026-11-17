package httpx

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"log/slog"
	"net"
	"net/http"
	"strconv"
	"strings"
)

// Rate-limit settings of api/rate_limit.py.
const (
	// RateLimitBucketTTL is how long an idle bucket is kept, in seconds.
	RateLimitBucketTTL = 120
	// A2ARPCLimit is the A2A JSON-RPC calls a caller may make a minute.
	A2ARPCLimit = 300
	// OAuthRegisterLimit is the anonymous OAuth client registrations an
	// address may make a minute.
	OAuthRegisterLimit = 10
)

// RateLimitScript is the token bucket every replica runs in Valkey, so all
// replicas draw from one bucket: KEYS[1] the bucket, ARGV[1]
// tokens a minute, ARGV[2] the TTL; it returns {allowed, retry_after}.
const RateLimitScript = `
local capacity = tonumber(ARGV[1])
if not capacity or capacity <= 0 then
    return {0, 60}
end

local time = redis.call('TIME')
local now = tonumber(time[1]) + tonumber(time[2]) / 1000000
local refill_per_second = capacity / 60
local state = redis.call('HMGET', KEYS[1], 'tokens', 'updated_at')
local tokens = tonumber(state[1]) or capacity
local updated_at = tonumber(state[2]) or now
tokens = math.min(capacity, tokens + math.max(0, now - updated_at) * refill_per_second)

local allowed = 0
local retry_after = 0
if tokens >= 1 then
    tokens = tokens - 1
    allowed = 1
else
    retry_after = math.max(1, math.ceil((1 - tokens) / refill_per_second))
end

redis.call('HSET', KEYS[1], 'tokens', tokens, 'updated_at', now)
redis.call('EXPIRE', KEYS[1], ARGV[2])
return {allowed, retry_after}
`

// RateLimitKey is the bucket of (scope, identity); the identity is hashed so
// no API key id or address sits in Valkey in the clear.
func RateLimitKey(scope, identity string) string {
	sum := sha256.Sum256([]byte(identity))
	return "agentarea:rate-limit:" + scope + ":" + hex.EncodeToString(sum[:])
}

// EnforceRateLimit is enforce_rate_limit: nil when allowed, the 429
// HTTPException with Retry-After when not. An unreachable limiter allows
// the request and logs a warning, as Python does.
func EnforceRateLimit(ctx context.Context, rl RateLimiter, log *slog.Logger, scope, identity string, limit int) error {
	allowed, retryAfter, err := rl.Take(ctx, scope, identity, limit)
	if err != nil {
		if log != nil {
			log.WarnContext(ctx, "Rate-limit Redis unavailable; allowing request", "error", err.Error())
		}
		return nil
	}
	if allowed {
		return nil
	}
	return HTTPError(http.StatusTooManyRequests, "Rate limit exceeded").
		WithHeader("Retry-After", strconv.Itoa(max(retryAfter, 1)))
}

// Rate-limit scopes.
const (
	A2ARPCScope        = "a2a-rpc"
	WebhookScope       = "webhook"
	OAuthRegisterScope = "oauth-register"
)

// A2AIdentity is limit_a2a_rpc's bucket: the API key or user that
// authenticated, else the peer address.
func A2AIdentity(r *http.Request, apiKeyID, userID string) string {
	switch {
	case apiKeyID != "":
		return "api-key:" + apiKeyID
	case userID != "":
		return "user:" + userID
	}
	return PeerIdentity(r)
}

// PeerIdentity is an anonymous caller's bucket: the peer address.
func PeerIdentity(r *http.Request) string {
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil || host == "" {
		host = "unknown"
	}
	return "ip:" + host
}

// ClientIdentity is an anonymous caller's bucket that survives a proxy: behind
// a private or loopback peer, the address that proxy appended last to
// X-Forwarded-For; otherwise the peer itself, so a direct caller cannot pick
// its own bucket.
func ClientIdentity(r *http.Request) string {
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	peer := net.ParseIP(host)
	if err == nil && peer != nil && (peer.IsPrivate() || peer.IsLoopback()) {
		hops := strings.Split(r.Header.Get("X-Forwarded-For"), ",")
		if last := net.ParseIP(strings.TrimSpace(hops[len(hops)-1])); last != nil {
			return "ip:" + last.String()
		}
	}
	return PeerIdentity(r)
}
