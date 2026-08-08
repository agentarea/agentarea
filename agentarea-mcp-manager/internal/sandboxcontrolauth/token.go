package sandboxcontrolauth

import (
	"crypto/hmac"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"strings"
	"time"
)

const (
	SecretEnv        = "SANDBOX_CONTROL_AUTH_SECRET"
	ScopeCreate      = "execution.create"
	ScopeRead        = "execution.read"
	ScopeCancel      = "execution.cancel"
	DefaultTokenTTL  = 5 * time.Minute
	minimumSecretLen = 32
)

type Identity struct {
	WorkspaceID string
	TaskID      string
	ExecutionID string
}

type claims struct {
	Version     int    `json:"v"`
	Scope       string `json:"scope"`
	WorkspaceID string `json:"workspace_id"`
	TaskID      string `json:"task_id"`
	ExecutionID string `json:"execution_id,omitempty"`
	BodySHA256  string `json:"body_sha256"`
	ExpiresAt   int64  `json:"expires_at"`
	Nonce       string `json:"nonce"`
}

func BodySHA256(body []byte) string {
	digest := sha256.Sum256(body)
	return hex.EncodeToString(digest[:])
}

func VerifyFromEnv(token, scope string, identity Identity, bodySHA256 string, now time.Time) error {
	secret := []byte(os.Getenv(SecretEnv))
	return Verify(token, secret, scope, identity, bodySHA256, now)
}

func Verify(token string, secret []byte, scope string, identity Identity, bodySHA256 string, now time.Time) error {
	if len(secret) < minimumSecretLen {
		return fmt.Errorf("%s must contain at least %d bytes", SecretEnv, minimumSecretLen)
	}
	if err := validateExpected(scope, identity, bodySHA256); err != nil {
		return err
	}
	parts := strings.Split(token, ".")
	if len(parts) != 2 || parts[0] == "" || parts[1] == "" {
		return errors.New("malformed sandbox control token")
	}
	expectedSignature := signature(parts[0], secret)
	if subtle.ConstantTimeCompare([]byte(parts[1]), []byte(expectedSignature)) != 1 {
		return errors.New("invalid sandbox control signature")
	}
	payload, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil {
		return errors.New("malformed sandbox control payload")
	}
	var value claims
	if err := json.Unmarshal(payload, &value); err != nil {
		return errors.New("malformed sandbox control claims")
	}
	if value.Version != 1 || value.Scope != scope || value.WorkspaceID != identity.WorkspaceID ||
		value.TaskID != identity.TaskID || value.ExecutionID != identity.ExecutionID ||
		subtle.ConstantTimeCompare([]byte(value.BodySHA256), []byte(bodySHA256)) != 1 {
		return errors.New("sandbox control claims do not match request")
	}
	if value.ExpiresAt <= now.Unix() {
		return errors.New("sandbox control token expired")
	}
	if len(value.Nonce) < 16 || len(value.Nonce) > 128 {
		return errors.New("sandbox control nonce is invalid")
	}
	return nil
}

// Sign exists for compatibility tests and non-Python control-plane clients.
// Production Python callers use the same documented claims/HMAC contract.
func Sign(secret []byte, scope string, identity Identity, bodySHA256 string, now time.Time, ttl time.Duration, nonce string) (string, error) {
	if len(secret) < minimumSecretLen {
		return "", errors.New("sandbox control secret must contain at least 32 bytes")
	}
	if ttl <= 0 || nonce == "" {
		return "", errors.New("sandbox control token TTL and nonce are required")
	}
	if err := validateExpected(scope, identity, bodySHA256); err != nil {
		return "", err
	}
	payload, err := json.Marshal(claims{
		Version:     1,
		Scope:       scope,
		WorkspaceID: identity.WorkspaceID,
		TaskID:      identity.TaskID,
		ExecutionID: identity.ExecutionID,
		BodySHA256:  bodySHA256,
		ExpiresAt:   now.Add(ttl).Unix(),
		Nonce:       nonce,
	})
	if err != nil {
		return "", fmt.Errorf("marshal sandbox control claims: %w", err)
	}
	encoded := base64.RawURLEncoding.EncodeToString(payload)
	return encoded + "." + signature(encoded, secret), nil
}

func BearerToken(header string) (string, error) {
	const prefix = "Bearer "
	if !strings.HasPrefix(header, prefix) {
		return "", errors.New("bearer authorization is required")
	}
	token := strings.TrimSpace(strings.TrimPrefix(header, prefix))
	if token == "" {
		return "", errors.New("bearer authorization is required")
	}
	return token, nil
}

func validateExpected(scope string, identity Identity, bodySHA256 string) error {
	if scope != ScopeCreate && scope != ScopeRead && scope != ScopeCancel {
		return fmt.Errorf("unsupported sandbox control scope %q", scope)
	}
	if identity.WorkspaceID == "" || identity.TaskID == "" || (scope != ScopeCreate && identity.ExecutionID == "") ||
		(scope == ScopeCreate && identity.ExecutionID != "") {
		return errors.New("sandbox control identity is incomplete")
	}
	if len(bodySHA256) != sha256.Size*2 {
		return errors.New("sandbox control body digest is invalid")
	}
	if _, err := hex.DecodeString(bodySHA256); err != nil {
		return errors.New("sandbox control body digest is invalid")
	}
	return nil
}

func signature(encoded string, secret []byte) string {
	mac := hmac.New(sha256.New, secret)
	_, _ = mac.Write([]byte(encoded))
	return base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
}
