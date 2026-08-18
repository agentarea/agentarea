package connectorauth

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"testing"
	"time"
)

const (
	testPlaneID = "d1f74c88-cc04-4cc7-b4e3-6054901d572a"
	testSecret  = "node-credential-must-not-leak"
)

func testIncoming() IncomingConnector {
	return IncomingConnector{
		NodeCredential: testSecret,
		Hello: Hello{
			ProtocolVersion:     "v1",
			DataPlaneID:         testPlaneID,
			ConnectorInstanceID: "connector-a",
			Capabilities:        map[string]bool{"mcp": true, "sandbox": false},
			AgentVersion:        "1.2.3",
		},
	}
}

func testClient(t *testing.T, baseURL string) *Client {
	t.Helper()
	client, err := NewClient(Config{
		PlatformAPIURL:           baseURL,
		AllowInsecureDevelopment: strings.HasPrefix(baseURL, "http://"),
		Timeout:                  time.Second,
		MaxResponseBytes:         64,
	}, nil)
	if err != nil {
		t.Fatal(err)
	}
	return client
}

func TestAuthenticateSendsExactHeartbeatAndReturnsLogicalPlane(t *testing.T) {
	var got heartbeatRequest
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			t.Errorf("method = %s, want POST", r.Method)
		}
		if r.URL.Path != "/v1/data-planes/"+testPlaneID+"/heartbeat" || r.URL.RawQuery != "" {
			t.Errorf("URL = %s", r.URL.String())
		}
		if r.Header.Get("Authorization") != "Bearer "+testSecret {
			t.Errorf("authorization = %q", r.Header.Get("Authorization"))
		}
		if r.Header.Get("Content-Type") != "application/json" {
			t.Errorf("content type = %q", r.Header.Get("Content-Type"))
		}
		body, err := io.ReadAll(r.Body)
		if err != nil {
			t.Error(err)
		}
		if strings.Contains(string(body), testSecret) {
			t.Error("credential appeared in heartbeat body")
		}
		if err := json.Unmarshal(body, &got); err != nil {
			t.Error(err)
		}
		w.WriteHeader(http.StatusNoContent)
	}))
	defer server.Close()

	plane, err := testClient(t, server.URL).Authenticate(context.Background(), testIncoming())
	if err != nil {
		t.Fatal(err)
	}
	if want := (heartbeatRequest{
		ProtocolVersion: "v1", DataPlaneID: testPlaneID, ConnectorInstanceID: "connector-a",
		Capabilities: map[string]bool{"mcp": true, "sandbox": false}, AgentVersion: "1.2.3", State: "ready",
	}); !reflect.DeepEqual(got, want) {
		t.Fatalf("heartbeat = %#v, want %#v", got, want)
	}
	if plane.DataPlaneID != testPlaneID || plane.ConnectorInstanceID != "connector-a" || plane.ProtocolVersion != "v1" || plane.AgentVersion != "1.2.3" || plane.State != "ready" || !plane.Capabilities["mcp"] {
		t.Fatalf("authenticated plane = %#v", plane)
	}
}

func TestAuthenticateRejectsUnauthorizedAndNotFoundWithoutLeakingResponse(t *testing.T) {
	for _, status := range []int{http.StatusUnauthorized, http.StatusNotFound, http.StatusUnprocessableEntity} {
		t.Run(http.StatusText(status), func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				w.WriteHeader(status)
				_, _ = w.Write([]byte("platform response contains " + testSecret))
			}))
			defer server.Close()

			_, err := testClient(t, server.URL).Authenticate(context.Background(), testIncoming())
			if !errors.Is(err, ErrAuthenticationFailed) || err.Error() != ErrAuthenticationFailed.Error() || strings.Contains(err.Error(), testSecret) || strings.Contains(err.Error(), "platform response") {
				t.Fatalf("error = %v", err)
			}
		})
	}
}

func TestAuthenticateRejectsInputMismatchGenerically(t *testing.T) {
	incoming := testIncoming()
	incoming.Hello.DataPlaneID = "not-a-data-plane-id"
	_, err := testClient(t, "http://example.test").Authenticate(context.Background(), incoming)
	if !errors.Is(err, ErrAuthenticationFailed) || err.Error() != ErrAuthenticationFailed.Error() || strings.Contains(err.Error(), testSecret) {
		t.Fatalf("error = %v", err)
	}
}

func TestAuthenticateTimesOutWithoutLeakingCredential(t *testing.T) {
	release := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		<-release
	}))
	client, err := NewClient(Config{PlatformAPIURL: server.URL, AllowInsecureDevelopment: true, Timeout: 20 * time.Millisecond, MaxResponseBytes: 64}, nil)
	if err != nil {
		t.Fatal(err)
	}
	_, err = client.Authenticate(context.Background(), testIncoming())
	if !errors.Is(err, ErrPlatformUnavailable) || strings.Contains(err.Error(), testSecret) {
		t.Fatalf("error = %v", err)
	}
	close(release)
	server.Close()
}

func TestAuthenticateRefusesUntrustedTLS(t *testing.T) {
	server := httptest.NewTLSServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		t.Fatal("untrusted TLS endpoint must not receive a request")
	}))
	defer server.Close()

	_, err := testClient(t, server.URL).Authenticate(context.Background(), testIncoming())
	if !errors.Is(err, ErrPlatformUnavailable) || strings.Contains(err.Error(), testSecret) {
		t.Fatalf("error = %v", err)
	}
}

func TestAuthenticateHonorsContextCancellation(t *testing.T) {
	started := make(chan struct{})
	release := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		close(started)
		<-release
	}))
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	result := make(chan error, 1)
	go func() {
		_, err := testClient(t, server.URL).Authenticate(ctx, testIncoming())
		result <- err
	}()
	<-started
	cancel()
	err := <-result
	if !errors.Is(err, ErrPlatformUnavailable) || !errors.Is(err, context.Canceled) || strings.Contains(err.Error(), testSecret) {
		t.Fatalf("error = %v", err)
	}
	close(release)
	server.Close()
}

func TestNewClientRejectsInsecureAndUnsafeURLs(t *testing.T) {
	for _, baseURL := range []string{
		"http://platform.example",
		"https://credential@platform.example",
		"https://platform.example?token=leak",
		"https://platform.example#fragment",
		"https://platform.example/v1",
	} {
		t.Run(baseURL, func(t *testing.T) {
			if _, err := NewClient(Config{PlatformAPIURL: baseURL}, nil); err == nil {
				t.Fatal("expected configuration rejection")
			}
		})
	}
}
