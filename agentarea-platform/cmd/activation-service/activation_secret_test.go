package main

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/backends/activationauth"
)

func TestActivationSecretIsTrimmedLikeTheSigner(t *testing.T) {
	secret := strings.Repeat("s", 32)
	t.Setenv(activationauth.SecretEnv, secret+"\n")
	s := &server{config: config{activationSecret: loadActivationSecret()}}
	identity := activationauth.Identity{WorkspaceID: "ws", TaskID: "task", FencingToken: 1}
	digest := activationauth.BodySHA256(nil)
	token, err := activationauth.SignDefault([]byte(secret), activationauth.ScopeExecute, identity, digest, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	r := httptest.NewRequest(http.MethodPost, "/execute", nil)
	r.Header.Set("Authorization", "Bearer "+token)
	w := httptest.NewRecorder()
	if !s.authorizeActivationRequest(w, r, activationauth.ScopeExecute, identity, digest) {
		t.Fatalf("token signed with the trimmed secret was refused: %d %s", w.Code, w.Body.String())
	}
}
