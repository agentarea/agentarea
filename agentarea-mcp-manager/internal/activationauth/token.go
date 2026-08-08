package activationauth

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
	"os"
	"strings"
	"time"
)

const (
	SecretEnv      = "SANDBOX_ACTIVATION_AUTH_SECRET"
	ScopeActivate  = "activate"
	ScopeExecute   = "execute"
	ScopeWriteback = "writeback"
	ScopeFiles     = "files"
	ScopeCleanup   = "cleanup"
	DefaultTTL     = 5 * time.Minute
)

type Identity struct {
	WorkspaceID  string
	TaskID       string
	Generation   int64
	FencingToken int64
}

type claims struct {
	Version      int    `json:"v"`
	Scope        string `json:"scope"`
	WorkspaceID  string `json:"workspace_id"`
	TaskID       string `json:"task_id"`
	Generation   int64  `json:"generation"`
	FencingToken int64  `json:"fencing_token"`
	BodySHA256   string `json:"body_sha256"`
	ExpiresAt    int64  `json:"expires_at"`
	Nonce        string `json:"nonce"`
}

func SecretFromEnv() ([]byte, error) {
	secret := []byte(os.Getenv(SecretEnv))
	if len(secret) < 32 {
		return nil, fmt.Errorf("%s must contain at least 32 bytes", SecretEnv)
	}
	return secret, nil
}

func BodySHA256(body []byte) string {
	digest := sha256.Sum256(body)
	return hex.EncodeToString(digest[:])
}

// TransferSHA256 binds a file authorization token to the complete canonical
// operation, not just to task identity or payload bytes. Size is -1 when it is
// not known before a read. The path must already be normalized by the caller.
func TransferSHA256(method, path string, size int64, mode uint32, contentSHA256 string) string {
	return BodySHA256([]byte(strings.ToUpper(method) + "\x00" + path + "\x00" + fmt.Sprintf("%d", size) + "\x00" + fmt.Sprintf("%o", mode) + "\x00" + contentSHA256))
}

// BoundTransferSHA256 additionally binds a file operation to one executor
// process incarnation. An empty incarnation preserves the Kubernetes contract,
// where pod UID and hydration revision provide the distributed fence.
func BoundTransferSHA256(method, path string, size int64, mode uint32, contentSHA256, executorIncarnation string) string {
	if executorIncarnation == "" {
		return TransferSHA256(method, path, size, mode, contentSHA256)
	}
	return BodySHA256([]byte(strings.ToUpper(method) + "\x00" + path + "\x00" + fmt.Sprintf("%d", size) + "\x00" + fmt.Sprintf("%o", mode) + "\x00" + contentSHA256 + "\x00" + executorIncarnation))
}

func SignFromEnv(scope string, identity Identity, bodySHA256 string, now time.Time) (string, error) {
	secret, err := SecretFromEnv()
	if err != nil {
		return "", err
	}
	return Sign(secret, scope, identity, bodySHA256, now, DefaultTTL)
}

func Sign(secret []byte, scope string, identity Identity, bodySHA256 string, now time.Time, ttl time.Duration) (string, error) {
	if len(secret) < 32 {
		return "", errors.New("activation auth secret must contain at least 32 bytes")
	}
	if scope != ScopeActivate && scope != ScopeExecute && scope != ScopeWriteback && scope != ScopeFiles && scope != ScopeCleanup {
		return "", fmt.Errorf("unsupported activation auth scope %q", scope)
	}
	if identity.WorkspaceID == "" || identity.TaskID == "" || identity.Generation < 0 || identity.FencingToken <= 0 {
		return "", errors.New("activation auth identity is incomplete")
	}
	if ttl <= 0 {
		return "", errors.New("activation auth TTL must be positive")
	}
	if !validSHA256(bodySHA256) {
		return "", errors.New("activation auth body digest is invalid")
	}
	nonceBytes := make([]byte, 16)
	if _, err := rand.Read(nonceBytes); err != nil {
		return "", fmt.Errorf("generate activation auth nonce: %w", err)
	}
	payload, err := json.Marshal(claims{
		Version:      2,
		Scope:        scope,
		WorkspaceID:  identity.WorkspaceID,
		TaskID:       identity.TaskID,
		Generation:   identity.Generation,
		FencingToken: identity.FencingToken,
		BodySHA256:   bodySHA256,
		ExpiresAt:    now.Add(ttl).Unix(),
		Nonce:        hex.EncodeToString(nonceBytes),
	})
	if err != nil {
		return "", fmt.Errorf("marshal activation auth claims: %w", err)
	}
	encoded := base64.RawURLEncoding.EncodeToString(payload)
	return encoded + "." + sign(encoded, secret), nil
}

func VerifyFromEnv(token, scope string, identity Identity, bodySHA256 string, now time.Time) error {
	secret, err := SecretFromEnv()
	if err != nil {
		return err
	}
	return Verify(token, secret, scope, identity, bodySHA256, now)
}

func Verify(token string, secret []byte, scope string, identity Identity, bodySHA256 string, now time.Time) error {
	if len(secret) < 32 {
		return errors.New("activation auth secret must contain at least 32 bytes")
	}
	parts := strings.Split(token, ".")
	if len(parts) != 2 || parts[0] == "" || parts[1] == "" {
		return errors.New("malformed activation auth token")
	}
	expectedSignature := sign(parts[0], secret)
	if subtle.ConstantTimeCompare([]byte(parts[1]), []byte(expectedSignature)) != 1 {
		return errors.New("invalid activation auth signature")
	}
	payload, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil {
		return errors.New("malformed activation auth payload")
	}
	var value claims
	if err := json.Unmarshal(payload, &value); err != nil {
		return errors.New("malformed activation auth claims")
	}
	if value.Version != 2 || value.Scope != scope || value.WorkspaceID != identity.WorkspaceID ||
		value.TaskID != identity.TaskID || value.Generation != identity.Generation ||
		value.FencingToken != identity.FencingToken || !validSHA256(bodySHA256) ||
		subtle.ConstantTimeCompare([]byte(value.BodySHA256), []byte(bodySHA256)) != 1 {
		return errors.New("activation auth claims do not match request")
	}
	if value.ExpiresAt <= now.Unix() {
		return errors.New("activation auth token expired")
	}
	if len(value.Nonce) != 32 {
		return errors.New("activation auth nonce is invalid")
	}
	return nil
}

func validSHA256(value string) bool {
	if len(value) != sha256.Size*2 {
		return false
	}
	_, err := hex.DecodeString(value)
	return err == nil
}

func BearerToken(header string) (string, error) {
	const prefix = "Bearer "
	if !strings.HasPrefix(header, prefix) || len(header) == len(prefix) {
		return "", errors.New("bearer authorization is required")
	}
	return strings.TrimSpace(strings.TrimPrefix(header, prefix)), nil
}

func sign(encodedPayload string, secret []byte) string {
	mac := hmac.New(sha256.New, secret)
	_, _ = mac.Write([]byte(encodedPayload))
	return base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
}
