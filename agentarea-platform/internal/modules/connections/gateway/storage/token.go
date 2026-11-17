package storage

import (
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"
)

// scopeStorage is the activation-auth scope of a storage token. The claims
// keep the shape mcp-manager signed (version 2, the task fields zero, the
// digest of an empty body), so tokens already handed to running containers
// still verify.
const scopeStorage = "storage"

// errClaimsMismatch is a correctly signed token presented for a request it
// does not grant.
var errClaimsMismatch = errors.New("storage token claims do not match request")

type claims struct {
	Version      int    `json:"v"`
	Scope        string `json:"scope"`
	WorkspaceID  string `json:"workspace_id"`
	TaskID       string `json:"task_id"`
	InstanceID   string `json:"instance_id,omitempty"`
	Generation   int64  `json:"generation"`
	FencingToken int64  `json:"fencing_token"`
	BodySHA256   string `json:"body_sha256"`
	ExpiresAt    int64  `json:"expires_at"`
	Nonce        string `json:"nonce"`
}

func emptyBodySHA256() string {
	digest := sha256.Sum256(nil)
	return hex.EncodeToString(digest[:])
}

func signToken(secret []byte, workspaceID, instanceID string, now time.Time, ttl time.Duration) (string, error) {
	if len(secret) < 32 {
		return "", errors.New("storage token secret must contain at least 32 bytes")
	}
	if workspaceID == "" || instanceID == "" {
		return "", errors.New("storage token identity is incomplete")
	}
	if ttl <= 0 {
		return "", errors.New("storage token TTL must be positive")
	}
	nonce := make([]byte, 16)
	if _, err := rand.Read(nonce); err != nil {
		return "", fmt.Errorf("generate storage token nonce: %w", err)
	}
	payload, err := json.Marshal(claims{
		Version: 2, Scope: scopeStorage, WorkspaceID: workspaceID, InstanceID: instanceID,
		BodySHA256: emptyBodySHA256(), ExpiresAt: now.Add(ttl).Unix(), Nonce: hex.EncodeToString(nonce),
	})
	if err != nil {
		return "", fmt.Errorf("marshal storage token claims: %w", err)
	}
	encoded := base64.RawURLEncoding.EncodeToString(payload)
	return encoded + "." + mac(encoded, secret), nil
}

func verifyToken(token string, secret []byte, workspaceID, instanceID string, now time.Time) error {
	if len(secret) < 32 {
		return errors.New("storage token secret must contain at least 32 bytes")
	}
	parts := strings.Split(token, ".")
	if len(parts) != 2 || parts[0] == "" || parts[1] == "" {
		return errors.New("malformed storage token")
	}
	if subtle.ConstantTimeCompare([]byte(parts[1]), []byte(mac(parts[0], secret))) != 1 {
		return errors.New("invalid storage token signature")
	}
	payload, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil {
		return errors.New("malformed storage token payload")
	}
	var c claims
	if err := json.Unmarshal(payload, &c); err != nil {
		return errors.New("malformed storage token claims")
	}
	if c.Version != 2 || c.Scope != scopeStorage || c.WorkspaceID != workspaceID || c.InstanceID != instanceID ||
		c.TaskID != "" || c.Generation != 0 || c.FencingToken != 0 ||
		subtle.ConstantTimeCompare([]byte(c.BodySHA256), []byte(emptyBodySHA256())) != 1 {
		return errClaimsMismatch
	}
	if c.ExpiresAt <= now.Unix() {
		return errors.New("storage token expired")
	}
	if len(c.Nonce) != 32 {
		return errors.New("storage token nonce is invalid")
	}
	return nil
}

func bearerToken(header string) (string, bool) {
	const prefix = "Bearer "
	if !strings.HasPrefix(header, prefix) || len(header) == len(prefix) {
		return "", false
	}
	return strings.TrimSpace(strings.TrimPrefix(header, prefix)), true
}

func mac(encodedPayload string, secret []byte) string {
	h := hmac.New(sha256.New, secret)
	_, _ = h.Write([]byte(encodedPayload))
	return base64.RawURLEncoding.EncodeToString(h.Sum(nil))
}
