package service

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

// publishedSecret is PUBLISHED_SECRET_VALUES: secrets printed in the repository.
func publishedSecret(v string) bool {
	switch v {
	case "dev-sandbox-activation-hmac-secret-change-in-prod",
		"dev-sandbox-cleanup-hmac-secret-change-in-prod-00",
		"dev-sandbox-file-auth-secret-change-in-prod-000000",
		"dev-sandbox-control-auth-secret-change-in-prod-0000",
		"dev-mcp-gateway-auth-secret-change-in-prod-00000000",
		"agentarea-dev-sandbox-activation-secret-change-me",
		"agentarea-dev-sandbox-cleanup-secret-change-me",
		"agentarea-dev-sandbox-file-secret-change-me",
		"agentarea-dev-sandbox-control-secret-change-me",
		"agentarea-dev-mcp-gateway-secret-change-me":
		return true
	}
	return false
}

// ValidateSecrets is SandboxSettings' validator: FILE and CONTROL may not
// be a value published in the repository.
func ValidateSecrets(m Manager) error {
	for _, s := range []struct{ name, v string }{{"FILE_SECRET", m.FileSecret}, {"CONTROL_SECRET", m.ControlSecret}} {
		if s.v != "" && publishedSecret(s.v) {
			return fmt.Errorf("%s is set to a value published in the AgentArea repository; generate a new one (scripts/gen-dev-secrets.sh rotates it) and restart", s.name)
		}
	}
	return nil
}

// signer is SandboxControlSigner: workspace- and task-scoped HMAC tokens
// for the execution API.
type signer struct {
	secret, workspaceID, taskID string
	now                         func() time.Time
}

func newSigner(secret, workspaceID, taskID string, now func() time.Time) (signer, error) {
	if len(secret) < 32 {
		return signer{}, errors.New("sandbox control auth secret must contain at least 32 bytes")
	}
	if workspaceID == "" || taskID == "" {
		return signer{}, errors.New("workspace_id and task_id are required for sandbox control auth")
	}
	return signer{secret: secret, workspaceID: workspaceID, taskID: taskID, now: now}, nil
}

func b64url(b []byte) string { return base64.RawURLEncoding.EncodeToString(b) }

func (s signer) headers(scope, executionID string, body []byte) (http.Header, error) {
	switch scope {
	case "execution.create", "execution.read", "execution.cancel":
	default:
		return nil, fmt.Errorf("unsupported sandbox control scope: %s", scope)
	}
	if scope == "execution.create" && executionID != "" {
		return nil, errors.New("create authorization cannot bind an execution id")
	}
	if scope != "execution.create" && executionID == "" {
		return nil, errors.New("execution id is required for read/cancel authorization")
	}
	sum := sha256.Sum256(body)
	var nonce [16]byte
	_, _ = rand.Read(nonce[:])
	claims := map[string]any{
		"v": 1, "scope": scope, "workspace_id": s.workspaceID, "task_id": s.taskID,
		"body_sha256": hex.EncodeToString(sum[:]), "expires_at": s.now().Unix() + 300,
		"nonce": hex.EncodeToString(nonce[:]),
	}
	if executionID != "" {
		claims["execution_id"] = executionID
	}
	payload, err := dumpsSorted(claims)
	if err != nil {
		return nil, err
	}
	encoded := b64url(payload)
	mac := hmac.New(sha256.New, []byte(s.secret))
	mac.Write([]byte(encoded))
	h := http.Header{}
	h.Set("Authorization", "Bearer "+encoded+"."+b64url(mac.Sum(nil)))
	h.Set("X-Agentarea-Workspace-ID", s.workspaceID)
	h.Set("X-Agentarea-Task-ID", s.taskID)
	return h, nil
}

// managerResponse is a buffered answer of the manager.
type managerResponse struct {
	Status int
	Header http.Header
	Body   []byte
}

func (r managerResponse) text() string { return string(r.Body) }

func (s *Service) managerURL(path string, q url.Values) string {
	u := strings.TrimRight(s.d.Manager.URL, "/") + path
	if len(q) > 0 {
		u += "?" + q.Encode()
	}
	return u
}

// call sends one request to the manager and reads the whole answer; a
// transport failure is an error, any status is a response.
func (s *Service) call(ctx context.Context, method, rawURL string, h http.Header, body []byte, timeout time.Duration) (managerResponse, error) {
	if timeout > 0 {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, timeout)
		defer cancel()
	}
	var rd io.Reader
	if body != nil {
		rd = bytes.NewReader(body)
	}
	req, err := http.NewRequestWithContext(ctx, method, rawURL, rd)
	if err != nil {
		return managerResponse{}, err
	}
	for k, vs := range h {
		req.Header[k] = vs
	}
	resp, err := s.d.HTTP.Do(req)
	if err != nil {
		return managerResponse{}, err
	}
	defer func() { _ = resp.Body.Close() }()
	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		return managerResponse{}, err
	}
	return managerResponse{Status: resp.StatusCode, Header: resp.Header, Body: raw}, nil
}

func bearer(secret string) http.Header {
	h := http.Header{}
	h.Set("Authorization", "Bearer "+secret)
	return h
}

func decodeObject(raw []byte) (map[string]any, error) {
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	var v any
	if err := dec.Decode(&v); err != nil {
		return nil, err
	}
	m, ok := v.(map[string]any)
	if !ok {
		return nil, errors.New("JSON object expected")
	}
	return m, nil
}

func itoa(n int64) string { return strconv.FormatInt(n, 10) }
