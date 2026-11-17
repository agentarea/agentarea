package payment

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"math/big"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync"
	"testing"
	"time"

	walletapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/wallet/api"
)

const (
	testX402Key  = "0x4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f362318"
	testX402Addr = "0x2c7536E3605D9C16a7a3D7b1898e529396a65c23"
	testIdemKey  = "962603cd4d11cd0cd03167a4dc0564f7f696670481b9ae9a00cbf29ba073e49b"
)

func fixedProtocols(rpc http.RoundTripper) Protocols {
	return Protocols{
		RPC:  rpc,
		Now:  func() time.Time { return time.Unix(1_700_000_000, 0) },
		Rand: bytes.NewReader(bytes.Repeat([]byte{0xab}, 256)),
	}
}

const x402Challenge = `{"x402Version":2,"error":"pay","resource":{"url":"https://api.example.com/tool","description":"Tool","mimeType":"application/json","extraField":1},` +
	`"accepts":[` +
	`{"scheme":"exact","network":"eip155:84532","asset":"0x036CbD53842c5426634e7929541eC2318f3dCF7e","amount":"5000","payTo":"0x1111111111111111111111111111111111111111","maxTimeoutSeconds":60,"extra":{"name":"USDC","version":"2"}},` +
	`{"scheme":"exact","network":"eip155:8453","asset":"0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913","amount":"10000","payTo":"0x2222222222222222222222222222222222222222","maxTimeoutSeconds":300,"extra":{"name":"USD Coin","version":"2"},"unknown":"x"}],` +
	`"extensions":{"payment-identifier":{"info":{"required":false},"schema":{"type":"object"}},"bazaar":{"a":1}}}`

func x402Wallet(typ string) Wallet {
	return Wallet{Type: typ, Keys: walletapi.NewCredentials(testX402Key, "")}
}

func x402Challenged(header string) Challenge {
	h := http.Header{}
	h.Set("PAYMENT-REQUIRED", header)
	return Challenge{Header: h}
}

func TestX402QuoteAndAnswer(t *testing.T) {
	p := fixedProtocols(nil)
	q, err := p.Quote(context.Background(), "x402", x402Wallet("dual"),
		x402Challenged(base64.StdEncoding.EncodeToString([]byte(x402Challenge))), testIdemKey)
	if err != nil {
		t.Fatal(err)
	}
	if q.Protocol != "x402" || q.Amount.String() != "0.01" || q.Recipient != "0x2222222222222222222222222222222222222222" || q.Limit != nil {
		t.Errorf("quote %+v", q)
	}
	if q.Metadata["network"] != "eip155:8453" || q.Metadata["scheme"] != "exact" {
		t.Errorf("metadata %v", q.Metadata)
	}
	h, err := q.Answer(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if h.Get("Access-Control-Expose-Headers") != "PAYMENT-RESPONSE,X-PAYMENT-RESPONSE" {
		t.Errorf("expose headers %q", h.Get("Access-Control-Expose-Headers"))
	}
	raw, err := base64.StdEncoding.DecodeString(h.Get("PAYMENT-SIGNATURE"))
	if err != nil {
		t.Fatal(err)
	}
	var sent struct {
		Payload struct {
			Signature string `json:"signature"`
		} `json:"payload"`
	}
	if err := json.Unmarshal(raw, &sent); err != nil {
		t.Fatal(err)
	}
	nonce := "0x" + strings.Repeat("ab", 32)
	want := `{"x402Version":2,"payload":{"authorization":{"from":"` + testX402Addr + `","to":"0x2222222222222222222222222222222222222222","value":"10000","validAfter":"1699999400","validBefore":"1700000300","nonce":"` + nonce + `"},"signature":"` + sent.Payload.Signature + `"},` +
		`"accepted":{"scheme":"exact","network":"eip155:8453","asset":"0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913","amount":"10000","payTo":"0x2222222222222222222222222222222222222222","maxTimeoutSeconds":300,"extra":{"name":"USD Coin","version":"2"}},` +
		`"resource":{"url":"https://api.example.com/tool","description":"Tool","mimeType":"application/json"},` +
		`"extensions":{"payment-identifier":{"info":{"required":false,"id":"` + testIdemKey + `"},"schema":{"type":"object"}},"bazaar":{"a":1}}}`
	if string(raw) != want {
		t.Errorf("payload\n%s\nwant\n%s", raw, want)
	}

	td := typedData{
		Types: map[string][]typedField{"TransferWithAuthorization": {
			{"from", "address"}, {"to", "address"}, {"value", "uint256"},
			{"validAfter", "uint256"}, {"validBefore", "uint256"}, {"nonce", "bytes32"},
		}},
		PrimaryType: "TransferWithAuthorization",
		Domain: map[string]any{"name": "USD Coin", "version": "2", "chainId": big.NewInt(8453),
			"verifyingContract": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"},
		Message: map[string]any{"from": testX402Addr, "to": "0x2222222222222222222222222222222222222222",
			"value": big.NewInt(10000), "validAfter": big.NewInt(1699999400), "validBefore": big.NewInt(1700000300),
			"nonce": bytes.Repeat([]byte{0xab}, 32)},
	}
	digest, err := td.digest()
	if err != nil {
		t.Fatal(err)
	}
	if got := recoverAddress(t, mustHex(t, sent.Payload.Signature), digest); got != testX402Addr {
		t.Errorf("signature recovers to %s", got)
	}
}

func TestX402ChallengeShapes(t *testing.T) {
	plain := strings.Replace(x402Challenge, `"extensions":{"payment-identifier":{"info":{"required":false},"schema":{"type":"object"}},"bazaar":{"a":1}}`, `"extensions":null`, 1)
	for name, header := range map[string]string{
		"raw json":  plain,
		"base64url": base64.RawURLEncoding.EncodeToString([]byte(plain)),
		"base64":    base64.StdEncoding.EncodeToString([]byte(plain)),
	} {
		q, err := fixedProtocols(nil).Quote(context.Background(), "x402", x402Wallet("x402"), x402Challenged(header), testIdemKey)
		if err != nil {
			t.Errorf("%s: %v", name, err)
			continue
		}
		h, err := q.Answer(context.Background())
		if err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		raw, _ := base64.StdEncoding.DecodeString(h.Get("PAYMENT-SIGNATURE"))
		if strings.Contains(string(raw), `"extensions"`) {
			t.Errorf("%s: extensions sent for a challenge without any: %s", name, raw)
		}
	}
}

func TestX402DomainFromAssetTable(t *testing.T) {
	for name, c := range map[string]struct {
		extra     string
		wantExtra string
	}{
		"empty extra keeps empty":       {`{}`, `"extra":{}`},
		"extra without name gets it":    {`{"version":"9","x":1}`, `"extra":{"version":"2","x":1,"name":"USD Coin"}`},
		"missing extra echoes as empty": {``, `"extra":{}`},
	} {
		req := `{"scheme":"exact","network":"eip155:8453","asset":"0x833589fcd6edb6e08f4c7c32d4f71b54bda02913","amount":"1","payTo":"0x2222222222222222222222222222222222222222","maxTimeoutSeconds":"30"`
		if c.extra != "" {
			req += `,"extra":` + c.extra
		}
		header := `{"x402Version":2,"accepts":[` + req + `}]}`
		q, err := fixedProtocols(nil).Quote(context.Background(), "x402", x402Wallet("x402"), x402Challenged(header), testIdemKey)
		if err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		if q.Amount.String() != "0.000001" {
			t.Errorf("%s: amount %s", name, q.Amount)
		}
		h, err := q.Answer(context.Background())
		if err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		raw, _ := base64.StdEncoding.DecodeString(h.Get("PAYMENT-SIGNATURE"))
		if !strings.Contains(string(raw), c.wantExtra) || !strings.Contains(string(raw), `"maxTimeoutSeconds":30,`) {
			t.Errorf("%s: %s", name, raw)
		}
		if !strings.Contains(string(raw), `"validBefore":"1700000030"`) {
			t.Errorf("%s: validity window %s", name, raw)
		}
	}
}

func TestX402Unsupported(t *testing.T) {
	permit2 := strings.Replace(x402Challenge, `"extra":{"name":"USD Coin","version":"2"}`, `"extra":{"assetTransferMethod":"permit2"}`, 1)
	v1 := `{"x402Version":1,"accepts":[]}`
	for name, c := range map[string]struct {
		wallet Wallet
		header string
	}{
		"mpp wallet":    {Wallet{Type: "mpp", Keys: walletapi.NewCredentials(testX402Key, "")}, x402Challenge},
		"no key":        {Wallet{Type: "x402", Keys: walletapi.NewCredentials("", "k")}, x402Challenge},
		"other network": {Wallet{Type: "x402", X402Config: map[string]any{"network": "eip155:1"}, Keys: walletapi.NewCredentials(testX402Key, "")}, x402Challenge},
		"permit2":       {x402Wallet("x402"), permit2},
		"v1":            {x402Wallet("x402"), v1},
	} {
		_, err := fixedProtocols(nil).Quote(context.Background(), "x402", c.wallet, x402Challenged(c.header), testIdemKey)
		if !errors.Is(err, ErrUnsupported) {
			t.Errorf("%s: %v, want ErrUnsupported", name, err)
		}
	}
	q, err := fixedProtocols(nil).Quote(context.Background(), "x402",
		Wallet{Type: "x402", X402Config: map[string]any{"network": "eip155:*"}, Keys: walletapi.NewCredentials(testX402Key, "")},
		x402Challenged(x402Challenge), testIdemKey)
	if err != nil || q.Metadata["network"] != "eip155:84532" {
		t.Errorf("wildcard network picks the first eip155 requirement: %v %v", q.Metadata, err)
	}
	for name, header := range map[string]string{
		"not json":            "%%%",
		"amount not a string": strings.Replace(x402Challenge, `"amount":"10000"`, `"amount":10000`, 1),
		"no accepts":          `{"x402Version":2}`,
		"extra null":          strings.Replace(x402Challenge, `"extra":{"name":"USD Coin","version":"2"}`, `"extra":null`, 1),
		"unknown asset":       strings.Replace(x402Challenge, `"extra":{"name":"USD Coin","version":"2"},"unknown"`, `"asset2":1,"unknown"`, 1),
		"fractional amount":   strings.Replace(x402Challenge, `"amount":"10000"`, `"amount":"1.5"`, 1),
	} {
		hdr := header
		if name == "unknown asset" {
			hdr = strings.Replace(header, `"asset":"0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"`, `"asset":"0x3333333333333333333333333333333333333333"`, 1)
		}
		_, err := fixedProtocols(nil).Quote(context.Background(), "x402", x402Wallet("x402"), x402Challenged(hdr), testIdemKey)
		if err == nil || errors.Is(err, ErrUnsupported) {
			t.Errorf("%s: %v, want a read error", name, err)
		}
	}
}

// rpcRecorder serves JSON-RPC from an httptest server, whatever URL the
// payment asks for, and records the URLs and methods.
type rpcRecorder struct {
	mu      sync.Mutex
	server  *httptest.Server
	urls    []string
	methods []string
	answers map[string]any
}

func newRPC(t *testing.T, answers map[string]any) *rpcRecorder {
	r := &rpcRecorder{answers: answers}
	r.server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		var call struct {
			JSONRPC string `json:"jsonrpc"`
			Method  string `json:"method"`
			Params  []any  `json:"params"`
			ID      int    `json:"id"`
		}
		body, _ := io.ReadAll(req.Body)
		if err := json.Unmarshal(body, &call); err != nil || call.JSONRPC != "2.0" || call.ID != 1 || req.Method != http.MethodPost {
			http.Error(w, "bad call", http.StatusBadRequest)
			return
		}
		r.mu.Lock()
		r.methods = append(r.methods, call.Method)
		r.mu.Unlock()
		answer, ok := r.answers[call.Method]
		if !ok {
			_ = json.NewEncoder(w).Encode(map[string]any{"jsonrpc": "2.0", "id": 1, "error": map[string]any{"code": -32601}})
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"jsonrpc": "2.0", "id": 1, "result": answer})
	}))
	t.Cleanup(r.server.Close)
	return r
}

func (r *rpcRecorder) RoundTrip(req *http.Request) (*http.Response, error) {
	r.mu.Lock()
	r.urls = append(r.urls, req.URL.String())
	r.mu.Unlock()
	target, _ := url.Parse(r.server.URL)
	out := req.Clone(req.Context())
	out.URL.Scheme, out.URL.Host, out.Host = target.Scheme, target.Host, target.Host
	return http.DefaultTransport.RoundTrip(out)
}

func mppHeader(request string, extra string) string {
	return `Payment id="ch_1", realm="api.example.com", method="tempo", intent="charge", request="` +
		base64.RawURLEncoding.EncodeToString([]byte(request)) + `"` + extra
}

func mppChallenged(headers ...string) Challenge {
	h := http.Header{}
	for _, v := range headers {
		h.Add("WWW-Authenticate", v)
	}
	return Challenge{Header: h}
}

func mppWallet(cfg map[string]any) Wallet {
	return Wallet{Type: "mpp", MPPConfig: cfg, Keys: walletapi.NewCredentials("", hex.EncodeToString(keccak256([]byte("cow"))))}
}

const mppRequest = `{"amount":"10000","currency":"0x20c0000000000000000000000000000000000000","recipient":"0x1111111111111111111111111111111111111111","methodDetails":{"chainId":4217,"memo":""}}`

func TestMPPQuoteAndAnswerEndToEnd(t *testing.T) {
	rpc := newRPC(t, map[string]any{
		"eth_chainId": "0x1079", "eth_getTransactionCount": "0x5", "eth_gasPrice": "0x1", "eth_estimateGas": "0x10",
	})
	p := fixedProtocols(rpc)
	header := mppHeader(mppRequest, `, expires="2030-01-01T00:00:00Z"`)
	ch := mppChallenged(
		"Bearer realm=x",
		`Payment id="s", realm="r", method="stripe", intent="charge", request="`+base64.RawURLEncoding.EncodeToString([]byte(`{"amount":"1"}`))+`"`,
		header,
	)
	q, err := p.Quote(context.Background(), "mpp", mppWallet(map[string]any{"session_budget_usd": float64(5), "decimals": float64(6)}), ch, testIdemKey)
	if err != nil {
		t.Fatal(err)
	}
	if q.Protocol != "mpp" || q.Amount.String() != "0.01" || q.Recipient != "0x1111111111111111111111111111111111111111" ||
		q.Limit == nil || q.Limit.String() != "5.0" || q.Metadata["payment_method"] != "charge" {
		t.Errorf("quote %+v limit %v", q, q.Limit)
	}
	h, err := q.Answer(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	auth := h.Get("Authorization")
	if !strings.HasPrefix(auth, "Payment ") || strings.ContainsAny(auth[len("Payment "):], "=+/") {
		t.Fatalf("authorization %q", auth)
	}
	raw, err := base64.RawURLEncoding.DecodeString(auth[len("Payment "):])
	if err != nil {
		t.Fatal(err)
	}
	var cred struct {
		Payload struct {
			Signature string `json:"signature"`
		} `json:"payload"`
	}
	if err := json.Unmarshal(raw, &cred); err != nil {
		t.Fatal(err)
	}
	key := cowKey(t)
	txBytes := mustHex(t, cred.Payload.Signature)
	sig := txBytes[len(txBytes)-65:]
	preimage := mustHex(t, "76"+"f885"+vecHead+"80"+"05"+"80"+"80"+"94"+vecCurrency+"80"+"c0")
	if got := recoverAddress(t, sig, keccak256(preimage)); got != key.checksumAddress() {
		t.Fatalf("signature recovers to %s", got)
	}
	wantTx := "0x76f8c8" + vecHead + "80" + "05" + "80" + "80" + "94" + vecCurrency + "80" + "c0" + "b841" + hex.EncodeToString(sig)
	if cred.Payload.Signature != wantTx {
		t.Errorf("tx\n%s\nwant\n%s", cred.Payload.Signature, wantTx)
	}
	wantCred := `{"challenge":{"expires":"2030-01-01T00:00:00Z","id":"ch_1","intent":"charge","method":"tempo","realm":"api.example.com","request":"` +
		base64.RawURLEncoding.EncodeToString([]byte(mppRequest)) + `"},"payload":{"signature":"` + wantTx + `","type":"transaction"},` +
		`"source":"did:pkh:eip155:4217:0xCD2a3d9F938E13CD947Ec05AbC7FE734Df8DD826"}`
	if string(raw) != wantCred {
		t.Errorf("credential\n%s\nwant\n%s", raw, wantCred)
	}
	for _, u := range rpc.urls {
		if u != "https://rpc.tempo.xyz" {
			t.Errorf("RPC went to %s", u)
		}
	}
	if got := strings.Join(rpc.methods, ","); got != "eth_chainId,eth_getTransactionCount,eth_gasPrice,eth_estimateGas" {
		t.Errorf("RPC methods %s", got)
	}
}

func TestMPPFeePayerAndAttribution(t *testing.T) {
	rpc := newRPC(t, map[string]any{"eth_chainId": "0xa5bf", "eth_getTransactionCount": "0x9", "eth_gasPrice": "0x2"})
	p := fixedProtocols(rpc)
	request := `{"amount":10000,"currency":"0x20c0000000000000000000000000000000000000","recipient":"0x1111111111111111111111111111111111111111","nonce_key":"0x10","methodDetails":{"feePayer":true}}`
	cfg := map[string]any{"session_budget_usd": "1.25", "rpc_url": "https://custom.example/rpc", "chain_id": float64(42431)}
	q, err := p.Quote(context.Background(), "mpp", mppWallet(cfg), mppChallenged(mppHeader(request, `, opaque="`+base64.RawURLEncoding.EncodeToString([]byte(`{"k":"é"}`))+`"`)), testIdemKey)
	if err != nil {
		t.Fatal(err)
	}
	h, err := q.Answer(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := base64.RawURLEncoding.DecodeString(strings.TrimPrefix(h.Get("Authorization"), "Payment "))
	var cred struct {
		Challenge map[string]string `json:"challenge"`
		Payload   map[string]string `json:"payload"`
		Source    string            `json:"source"`
	}
	if err := json.Unmarshal(raw, &cred); err != nil {
		t.Fatal(err)
	}
	if cred.Challenge["opaque"] != base64.RawURLEncoding.EncodeToString([]byte(`{"k":"é"}`)) {
		t.Errorf("opaque echo %q", cred.Challenge["opaque"])
	}
	if cred.Source != "did:pkh:eip155:42431:0xCD2a3d9F938E13CD947Ec05AbC7FE734Df8DD826" {
		t.Errorf("source %s", cred.Source)
	}
	tx := mustHex(t, cred.Payload["signature"])
	if tx[0] != 0x78 {
		t.Fatalf("fee payer credential is not a 0x78 envelope: %x", tx[:4])
	}
	memo := hex.EncodeToString(keccak256([]byte("mpp"))[:4]) + "01" + hex.EncodeToString(keccak256([]byte("api.example.com"))[:10]) +
		strings.Repeat("00", 10) + strings.Repeat("ab", 7)
	if !strings.Contains(hex.EncodeToString(tx), "95777d59") || !strings.Contains(hex.EncodeToString(tx), memo) {
		t.Errorf("no attribution memo in %x", tx)
	}
	if !strings.Contains(hex.EncodeToString(tx), "a0"+strings.Repeat("ff", 32)+"80"+"846553f119"+"80"+"80"+"94"+cowAddressHex(t)) {
		t.Errorf("envelope fields: %x", tx)
	}
	for _, u := range rpc.urls {
		if u != "https://custom.example/rpc" {
			t.Errorf("RPC went to %s", u)
		}
	}
}

func TestMPPChainMismatch(t *testing.T) {
	rpc := newRPC(t, map[string]any{"eth_chainId": "0xa5bf", "eth_getTransactionCount": "0x0", "eth_gasPrice": "0x1"})
	q, err := fixedProtocols(rpc).Quote(context.Background(), "mpp", mppWallet(map[string]any{"session_budget_usd": 1.0}), mppChallenged(mppHeader(mppRequest, "")), testIdemKey)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := q.Answer(context.Background()); err == nil || !strings.Contains(err.Error(), "chain ID mismatch") {
		t.Errorf("answer: %v", err)
	}
}

func TestMPPUnsupportedAndErrors(t *testing.T) {
	cfg := map[string]any{"session_budget_usd": 1.0}
	for name, c := range map[string]struct {
		wallet Wallet
		ch     Challenge
	}{
		"x402 wallet":   {Wallet{Type: "x402", MPPConfig: cfg, Keys: walletapi.NewCredentials("", "0x01")}, mppChallenged(mppHeader(mppRequest, ""))},
		"no key":        {Wallet{Type: "dual", MPPConfig: cfg, Keys: walletapi.NewCredentials(testX402Key, "")}, mppChallenged(mppHeader(mppRequest, ""))},
		"no tempo":      {mppWallet(cfg), mppChallenged(strings.Replace(mppHeader(mppRequest, ""), `method="tempo"`, `method="stripe"`, 1))},
		"expired":       {mppWallet(cfg), mppChallenged(mppHeader(mppRequest, `, expires="2020-01-01T00:00:00Z"`))},
		"session":       {mppWallet(cfg), mppChallenged(strings.Replace(mppHeader(mppRequest, ""), `intent="charge"`, `intent="session"`, 1))},
		"duplicate id":  {mppWallet(cfg), mppChallenged(mppHeader(mppRequest, `, id="again"`))},
		"bad request":   {mppWallet(cfg), mppChallenged(`Payment id="a", realm="r", method="tempo", intent="charge", request="!!!"`)},
		"missing realm": {mppWallet(cfg), mppChallenged(`Payment id="a", method="tempo", intent="charge", request="e30"`)},
	} {
		_, err := fixedProtocols(nil).Quote(context.Background(), "mpp", c.wallet, c.ch, testIdemKey)
		if !errors.Is(err, ErrUnsupported) {
			t.Errorf("%s: %v, want ErrUnsupported", name, err)
		}
	}
	for name, c := range map[string]struct {
		cfg     map[string]any
		expires string
	}{
		"no session budget": {map[string]any{}, ""},
		"unknown chain":     {map[string]any{"session_budget_usd": 1.0, "chain_id": 7.0}, ""},
		"naive expires":     {cfg, `, expires="2030-01-01T00:00:00"`},
	} {
		_, err := fixedProtocols(nil).Quote(context.Background(), "mpp", mppWallet(c.cfg), mppChallenged(mppHeader(mppRequest, c.expires)), testIdemKey)
		if err == nil || errors.Is(err, ErrUnsupported) {
			t.Errorf("%s: %v, want an error", name, err)
		}
	}
	q, err := fixedProtocols(nil).Quote(context.Background(), "mpp", mppWallet(cfg), mppChallenged(mppHeader(mppRequest, `, expires="not a date"`)), testIdemKey)
	if err != nil || q.Amount.String() != "0.01" {
		t.Errorf("an unreadable expires is not expired: %v", err)
	}
}

func TestParseMPPChallengeEscapes(t *testing.T) {
	ch, err := parseMPPChallenge(`payment  id="a\"b", realm=api.example.com, method="tempo", intent="charge", request="e30", description="x\\y"`)
	if err != nil {
		t.Fatal(err)
	}
	if ch.ID != `a"b` || ch.Realm != "api.example.com" || ch.Description != `x\y` || len(ch.Request) != 0 || ch.RequestB64 != "e30" {
		t.Errorf("%+v", ch)
	}
}

func TestReceipt(t *testing.T) {
	b64 := func(s string) string { return base64.StdEncoding.EncodeToString([]byte(s)) }
	url64 := func(s string) string { return base64.RawURLEncoding.EncodeToString([]byte(s)) }
	for name, c := range map[string]struct {
		protocol string
		headers  map[string]string
		want     string
	}{
		"x402 transaction":      {"x402", map[string]string{"PAYMENT-RESPONSE": b64(`{"success":true,"transaction":"0xabc","txHash":"0xdef"}`)}, "0xabc"},
		"x402 txHash":           {"x402", map[string]string{"PAYMENT-RESPONSE": b64(`{"txHash":"0xdef","transaction_hash":"0x1"}`)}, "0xdef"},
		"x402 transaction_hash": {"x402", map[string]string{"X-PAYMENT-RESPONSE": b64(`{"transaction":"","transaction_hash":"0x1"}`)}, "0x1"},
		"x402 garbage":          {"x402", map[string]string{"PAYMENT-RESPONSE": "!!"}, ""},
		"x402 none":             {"x402", nil, ""},
		"mpp externalId":        {"mpp", map[string]string{"X-MPP-Receipt": url64(`{"status":"success","timestamp":"2025-01-01T00:00:00Z","reference":"0xref","method":"tempo","externalId":"ext"}`)}, "ext"},
		"mpp reference":         {"mpp", map[string]string{"X-MPP-Receipt": url64(`{"status":"success","timestamp":"2025-01-01T00:00:00Z","reference":"0xref","method":"tempo"}`)}, "0xref"},
		"mpp failed status":     {"mpp", map[string]string{"X-MPP-Receipt": url64(`{"status":"failed","timestamp":"2025-01-01T00:00:00Z","reference":"0xref","method":"tempo"}`)}, ""},
		"mpp raw json":          {"mpp", map[string]string{"X-MPP-Receipt": `{"transactionHash":"0x9"}`}, "0x9"},
		"mpp none":              {"mpp", nil, ""},
	} {
		h := http.Header{}
		for k, v := range c.headers {
			h.Set(k, v)
		}
		if got := Receipt(c.protocol, h); got != c.want {
			t.Errorf("%s: %q, want %q", name, got, c.want)
		}
	}
}

func cowAddressHex(t *testing.T) string {
	k := cowKey(t)
	return hex.EncodeToString(k.address[:])
}

func TestX402PaysOnlyTheNetworksUSDC(t *testing.T) {
	const usdc = `"asset":"0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"`
	const other = `"asset":"0x4200000000000000000000000000000000000006"`
	foreign := strings.Replace(x402Challenge, usdc, other, 1)
	_, err := fixedProtocols(nil).Quote(context.Background(), "x402", x402Wallet("x402"), x402Challenged(foreign), testIdemKey)
	if err == nil || errors.Is(err, ErrUnsupported) {
		t.Fatalf("a token that is not the network's USDC was quoted: %v", err)
	}
	both := strings.Replace(x402Challenge, `"accepts":[`, `"accepts":[`+
		`{"scheme":"exact","network":"eip155:8453",`+other+`,"amount":"1","payTo":"0x3333333333333333333333333333333333333333","maxTimeoutSeconds":60,"extra":{"name":"Wrapped Ether","version":"1"}},`, 1)
	q, err := fixedProtocols(nil).Quote(context.Background(), "x402", x402Wallet("x402"), x402Challenged(both), testIdemKey)
	if err != nil || q.Recipient != "0x2222222222222222222222222222222222222222" || q.Amount.String() != "0.01" {
		t.Fatalf("the USDC requirement was not the one paid: %+v %v", q, err)
	}
}

func TestMPPPaysOnlyTempoUSDStablecoins(t *testing.T) {
	cfg := map[string]any{"session_budget_usd": 1.0}
	usdc := strings.Replace(mppRequest, tempoPathUSD, tempoUSDC, 1)
	if _, err := fixedProtocols(nil).Quote(context.Background(), "mpp", mppWallet(cfg), mppChallenged(mppHeader(usdc, "")), testIdemKey); err != nil {
		t.Fatalf("mainnet USDC: %v", err)
	}
	for name, c := range map[string]struct {
		request string
		cfg     map[string]any
	}{
		"other token":      {strings.Replace(mppRequest, tempoPathUSD, "0x20c0000000000000000000000000000000000077", 1), cfg},
		"testnet USDC":     {strings.Replace(usdc, `"chainId":4217`, `"chainId":42431`, 1), cfg},
		"unknown chain":    {strings.Replace(mppRequest, `"methodDetails":{"chainId":4217,"memo":""}`, `"methodDetails":{"memo":""}`, 1), map[string]any{"session_budget_usd": 1.0, "rpc_url": "https://custom.example/rpc"}},
		"18 decimals read": {mppRequest, map[string]any{"session_budget_usd": 1.0, "decimals": 18.0}},
	} {
		_, err := fixedProtocols(nil).Quote(context.Background(), "mpp", mppWallet(c.cfg), mppChallenged(mppHeader(c.request, "")), testIdemKey)
		if err == nil || errors.Is(err, ErrUnsupported) {
			t.Errorf("%s: %v, want a refusal", name, err)
		}
	}
}
