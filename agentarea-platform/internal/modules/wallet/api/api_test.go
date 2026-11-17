package api

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
)

// Vectors are sha256 of "<call_ref>:<sequence>" computed outside Go; the
// call refs are the ones test_paid_tool_retry_idempotency.py uses.
func TestIdempotencyKeyVectors(t *testing.T) {
	cases := []struct {
		ref  string
		seq  int
		want string
	}{
		{"task-1:call_1", 0, "962603cd4d11cd0cd03167a4dc0564f7f696670481b9ae9a00cbf29ba073e49b"},
		{"task-1:call_1", 1, "ca1e1165dd1a70cb88f3d53f083ab3e1a14d43d166e74e3cea84766643551cc3"},
		{"wf-1:run-1:7", 3, "1576b4097c62f090ccf2396f3bbe1590fc01c059af2dcb8ce46dc211caeee855"},
	}
	for _, c := range cases {
		if got := IdempotencyKey(c.ref, c.seq); got != c.want {
			t.Errorf("IdempotencyKey(%q, %d) = %s, want %s", c.ref, c.seq, got, c.want)
		}
	}
	if IdempotencyKey("task-1:call_1", 0) == IdempotencyKey("task-2:call_1", 0) {
		t.Error("calls of different tasks share a key")
	}
}

func TestCallRefFallsBackToTheActivityIdentity(t *testing.T) {
	if got := CallRef("task-1", "call_1", "wf", "run", "7"); got != "task-1:call_1" {
		t.Errorf("with task and call: %q", got)
	}
	for _, c := range [][2]string{{"", "call_1"}, {"task-1", ""}, {"", ""}} {
		if got := CallRef(c[0], c[1], "wf-1", "run-1", "7"); got != "wf-1:run-1:7" {
			t.Errorf("CallRef(%q, %q) = %q", c[0], c[1], got)
		}
	}
}

func TestSettlementStatus(t *testing.T) {
	for _, c := range []struct {
		ok   bool
		tx   string
		want string
	}{
		{true, "", PaymentCompleted},
		{true, "0xabc", PaymentCompleted},
		{false, "0xabc", PaymentCompleted},
		{false, "", PaymentFailed},
	} {
		if got := SettlementStatus(c.ok, c.tx); got != c.want {
			t.Errorf("SettlementStatus(%v, %q) = %s, want %s", c.ok, c.tx, got, c.want)
		}
	}
}

// Cases are test_protocol_detection.py's TestPaymentProtocolDetector.
func TestDetectProtocol(t *testing.T) {
	payment := `Payment id="chal_1", method="tempo", intent="charge", request="eyJhbW91bnQiOiIwLjAxIn0"`
	for name, c := range map[string]struct {
		status  int
		headers map[string]string
		want    string
	}{
		"x402 header":        {402, map[string]string{"PAYMENT-REQUIRED": "base64data..."}, ProtocolX402},
		"x402 lowercase":     {402, map[string]string{"payment-required": "base64data..."}, ProtocolX402},
		"x402 empty value":   {402, map[string]string{"Payment-Required": ""}, ProtocolX402},
		"mpp realm":          {402, map[string]string{"WWW-Authenticate": "MPP realm=test"}, ProtocolMPP},
		"mpp payment scheme": {402, map[string]string{"WWW-Authenticate": payment}, ProtocolMPP},
		"mpp lowercase":      {402, map[string]string{"www-authenticate": "mpp challenge=abc"}, ProtocolMPP},
		"unknown":            {402, map[string]string{"Content-Type": "application/json"}, ""},
		"not 402":            {200, map[string]string{"PAYMENT-REQUIRED": "data"}, ""},
		"no headers":         {402, nil, ""},
		"x402 wins":          {402, map[string]string{"PAYMENT-REQUIRED": "data", "WWW-Authenticate": "MPP realm=test"}, ProtocolX402},
		"basic auth":         {402, map[string]string{"WWW-Authenticate": "Basic realm=x"}, ""},
	} {
		if got := DetectProtocol(c.status, c.headers); got != c.want {
			t.Errorf("%s: %q, want %q", name, got, c.want)
		}
	}
}

func TestCredentialsNeverPrint(t *testing.T) {
	key := "0xdeadbeefprivatekey"
	c := NewCredentials(key, "tempo-secret")
	var out strings.Builder
	logger := slog.New(slog.NewTextHandler(&out, nil))
	logger.Info("loaded", "creds", c)
	raw, err := json.Marshal(map[string]any{"c": c})
	if err != nil {
		t.Fatal(err)
	}
	for _, s := range []string{
		fmt.Sprint(c), fmt.Sprintf("%v", c), fmt.Sprintf("%+v", c), fmt.Sprintf("%#v", c),
		fmt.Sprintf("%+v", &c), out.String(), string(raw),
		fmt.Sprintf("%+v", Payable{Wallet: Wallet{Type: "x402"}}),
	} {
		if strings.Contains(s, key) || strings.Contains(s, "tempo-secret") {
			t.Errorf("a key leaked into %q", s)
		}
	}
	if c.X402PrivateKey() != key || c.MPPTempoKey() != "tempo-secret" {
		t.Error("accessors lost the keys")
	}
}

func TestAdjustedNeverBuildsTheHugeNumber(t *testing.T) {
	for in, want := range map[string]int64{
		"1234.5": 3, "0.0123": -2, "1E+3": 3, "999999999999.9999995": 11, "1000000000000": 12, "0.000001": -6,
		"1E+2147483646": 2147483646,
	} {
		if got := Adjusted(money.MustParse(in)); got != want {
			t.Errorf("Adjusted(%s) = %d, want %d", in, got, want)
		}
	}
	if Adjusted(money.Zero()) > -1_000_000 {
		t.Error("zero is not tiny")
	}
	if Adjusted(money.MustParse("0E-2147483648")) > -1_000_000 {
		t.Error("a zero with a huge exponent is not tiny")
	}
}
