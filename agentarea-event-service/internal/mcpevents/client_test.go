package mcpevents

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

type seen struct {
	path    string
	headers http.Header
	body    map[string]any
}

func gateway(t *testing.T, answer func(w http.ResponseWriter, frame map[string]any)) (*Client, *[]seen) {
	t.Helper()
	var got []seen
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw, _ := io.ReadAll(r.Body)
		var frame map[string]any
		if err := json.Unmarshal(raw, &frame); err != nil {
			t.Fatalf("request is not JSON: %v", err)
		}
		got = append(got, seen{path: r.URL.Path, headers: r.Header.Clone(), body: frame})
		answer(w, frame)
	}))
	t.Cleanup(srv.Close)
	return NewClient(srv.URL+"/", "gateway-secret"), &got
}

func result(w http.ResponseWriter, frame map[string]any, result string) {
	w.Header().Set("Content-Type", "application/json")
	fmt.Fprintf(w, `{"jsonrpc":"2.0","id":%v,"result":%s}`, frame["id"], result)
}

func TestPollIsAStatelessRequestThroughTheGateway(t *testing.T) {
	client, got := gateway(t, func(w http.ResponseWriter, frame map[string]any) {
		result(w, frame, `{"resultType":"complete","events":[{"eventId":"e1","name":"ticket.created","timestamp":"2026-10-19T10:00:00Z","data":{"n":1}}],"cursor":"7","truncated":false,"hasMore":false,"nextPollMs":2000}`)
	})
	out, err := client.Poll(context.Background(), "inst-1", PollRequest{Name: "ticket.created", Arguments: map[string]any{"queue": "q"}})
	if err != nil {
		t.Fatal(err)
	}
	if len(out.Events) != 1 || out.Cursor == nil || *out.Cursor != "7" || out.NextPollMs != 2000 {
		t.Fatalf("result %+v", out)
	}
	req := (*got)[0]
	if req.path != "/mcp/inst-1/mcp" {
		t.Fatalf("path %s", req.path)
	}
	for header, want := range map[string]string{
		"X-AgentArea-Manager-Authorization": "Bearer gateway-secret",
		"Mcp-Method":                        "events/poll",
		"Mcp-Name":                          "ticket.created",
		"MCP-Protocol-Version":              "2026-07-28",
	} {
		if req.headers.Get(header) != want {
			t.Fatalf("%s = %q", header, req.headers.Get(header))
		}
	}
	params := req.body["params"].(map[string]any)
	if params["cursor"] != nil || params["name"] != "ticket.created" {
		t.Fatalf("params %v", params)
	}
	meta := params["_meta"].(map[string]any)
	if meta["io.modelcontextprotocol/protocolVersion"] != "2026-07-28" {
		t.Fatalf("meta %v", meta)
	}
}

func TestAnAnswerOnAnEventStreamIsRead(t *testing.T) {
	client, _ := gateway(t, func(w http.ResponseWriter, frame map[string]any) {
		w.Header().Set("Content-Type", "text/event-stream")
		fmt.Fprintf(w, "event: message\ndata: {\"jsonrpc\":\"2.0\",\"method\":\"notifications/message\",\"params\":{}}\n\n")
		fmt.Fprintf(w, "event: message\ndata: {\"jsonrpc\":\"2.0\",\"id\":%v,\"result\":{\"events\":[],\"cursor\":\"9\"}}\n\n", frame["id"])
	})
	out, err := client.Poll(context.Background(), "i", PollRequest{Name: "n", Arguments: map[string]any{}})
	if err != nil {
		t.Fatal(err)
	}
	if out.Cursor == nil || *out.Cursor != "9" {
		t.Fatalf("cursor %v", out.Cursor)
	}
}

func TestAServerErrorIsAnRPCError(t *testing.T) {
	client, _ := gateway(t, func(w http.ResponseWriter, frame map[string]any) {
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprintf(w, `{"jsonrpc":"2.0","id":%v,"error":{"code":-32023,"message":"NotFound","data":{"kind":"event"}}}`, frame["id"])
	})
	_, err := client.Poll(context.Background(), "i", PollRequest{Name: "gone", Arguments: map[string]any{}})
	var rpc *RPCError
	if !errors.As(err, &rpc) || rpc.Code != CodeNotFound {
		t.Fatalf("error %v", err)
	}
}

func TestAGatewayRefusalNamesItsStatus(t *testing.T) {
	client, _ := gateway(t, func(w http.ResponseWriter, _ map[string]any) {
		http.Error(w, "MCP instance authenticates through an auth config", http.StatusConflict)
	})
	_, err := client.Poll(context.Background(), "i", PollRequest{Name: "n", Arguments: map[string]any{}})
	if err == nil || !strings.Contains(err.Error(), "HTTP 409") || !strings.Contains(err.Error(), "auth config") {
		t.Fatalf("error %v", err)
	}
}

func TestSubscribeSendsTheWebhookDeliveryAndReadsTheGrant(t *testing.T) {
	client, got := gateway(t, func(w http.ResponseWriter, frame map[string]any) {
		result(w, frame, `{"resultType":"complete","id":"sub_1","refreshBefore":"2026-10-19T11:00:00.123456Z","cursor":"c0","truncated":false}`)
	})
	cursor := "c-prev"
	out, err := client.Subscribe(context.Background(), "i", SubscribeRequest{
		Name: "ticket.created", Arguments: map[string]any{"queue": "q"},
		Delivery: Delivery{URL: "https://api.example/webhooks/w1", Secret: "whsec_x"},
		Cursor:   &cursor, TTLMs: 3600000,
	})
	if err != nil {
		t.Fatal(err)
	}
	if out.ID != "sub_1" || out.RefreshBefore == nil || out.RefreshBefore.Minute() != 0 || *out.Cursor != "c0" {
		t.Fatalf("grant %+v", out)
	}
	params := (*got)[0].body["params"].(map[string]any)
	delivery := params["delivery"].(map[string]any)
	if delivery["mode"] != "webhook" || delivery["url"] != "https://api.example/webhooks/w1" || delivery["secret"] != "whsec_x" { // pragma: allowlist secret
		t.Fatalf("delivery %v", delivery)
	}
	if params["cursor"] != "c-prev" || params["ttlMs"] != float64(3600000) {
		t.Fatalf("params %v", params)
	}
}

func TestUnsubscribeNamesTheKeyWithoutTheSecret(t *testing.T) {
	client, got := gateway(t, func(w http.ResponseWriter, frame map[string]any) {
		result(w, frame, `{"resultType":"complete"}`)
	})
	err := client.Unsubscribe(context.Background(), "i", UnsubscribeRequest{
		Name: "ticket.created", Arguments: map[string]any{},
		Delivery: Delivery{URL: "https://api.example/webhooks/w1", Secret: "whsec_x", Mode: "webhook"},
	})
	if err != nil {
		t.Fatal(err)
	}
	delivery := (*got)[0].body["params"].(map[string]any)["delivery"].(map[string]any)
	if len(delivery) != 1 || delivery["url"] != "https://api.example/webhooks/w1" {
		t.Fatalf("delivery %v", delivery)
	}
	if (*got)[0].headers.Get("Mcp-Method") != "events/unsubscribe" {
		t.Fatal("method header")
	}
}

func TestANameThatIsNotPlainASCIIIsBase64Wrapped(t *testing.T) {
	if EncodeHeaderValue("ticket.created") != "ticket.created" {
		t.Fatal("plain name changed")
	}
	if got := EncodeHeaderValue("тикет"); got != "=?base64?0YLQuNC60LXRgg==?=" {
		t.Fatalf("encoded %q", got)
	}
}
