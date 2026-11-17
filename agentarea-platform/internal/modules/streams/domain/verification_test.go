package domain

import (
	"context"
	"crypto/ed25519"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"strconv"
	"strings"
	"testing"
	"time"
)

var verifyBody = []byte(`{"action":"opened"}`)

func sp(s string) *string { return &s }

func noLookup(context.Context, string, string, *BasicAuth) (int, any, error) {
	return 0, nil, errors.New("no lookup expected")
}

func verify(v Verification, headers, creds map[string]string, body any, config map[string]any, lookup APILookup) error {
	if lookup == nil {
		lookup = noLookup
	}
	if config == nil {
		config = map[string]any{}
	}
	_, err := Verify(context.Background(), v, headers, verifyBody, body, creds, config, lookup, time.Now())
	return err
}

func scheme(v Verification) Verification {
	d := defaultVerification()
	if v.Algorithm == "" {
		v.Algorithm = d.Algorithm
	}
	if v.Encoding == "" {
		v.Encoding = d.Encoding
	}
	if v.Payload == "" {
		v.Payload = d.Payload
	}
	if v.SignatureFormat == "" {
		v.SignatureFormat = d.SignatureFormat
	}
	if v.TimestampKey == "" {
		v.TimestampKey = d.TimestampKey
	}
	if v.SignatureKey == "" {
		v.SignatureKey = d.SignatureKey
	}
	if v.SecretFormat == "" {
		v.SecretFormat = d.SecretFormat
	}
	if v.ToleranceSecs == 0 {
		v.ToleranceSecs = d.ToleranceSecs
	}
	return v
}

func hexMAC(secret string, payload []byte) string {
	m := hmac.New(sha256.New, []byte(secret))
	m.Write(payload)
	return hex.EncodeToString(m.Sum(nil))
}

func isRefusal(t *testing.T, err error, contains string) {
	t.Helper()
	var ve *VerificationError
	if !errors.As(err, &ve) {
		t.Fatalf("want a VerificationError, got %v", err)
	}
	if !strings.Contains(ve.Msg, contains) {
		t.Fatalf("%q does not say %q", ve.Msg, contains)
	}
}

func github() Verification {
	return scheme(Verification{Scheme: "hmac", Secret: sp("webhook_secret"), Header: sp("X-Hub-Signature-256"), Prefix: "sha256="})
}

func TestHMACPassesTheProvidersSignatureAndRefusesAnother(t *testing.T) {
	good := map[string]string{"x-hub-signature-256": "sha256=" + hexMAC("s3cret", verifyBody)}
	if err := verify(github(), good, map[string]string{"webhook_secret": "s3cret"}, nil, nil, nil); err != nil {
		t.Fatal(err)
	}
	isRefusal(t, verify(github(), good, map[string]string{"webhook_secret": "other"}, nil, nil, nil), "does not match")
	isRefusal(t, verify(github(), map[string]string{}, map[string]string{"webhook_secret": "s3cret"}, nil, nil, nil), "missing header")
	isRefusal(t, verify(github(), map[string]string{"x-hub-signature-256": "sha256=x"}, map[string]string{}, nil, nil, nil), "no webhook_secret")
}

func TestSlackSignsTimestampAndBodyWithinTheReplayWindow(t *testing.T) {
	slack := scheme(Verification{Scheme: "hmac_timestamped", Secret: sp("signing_secret"), Header: sp("X-Slack-Signature"),
		TimestampHeader: sp("X-Slack-Request-Timestamp"), Payload: "v0:{timestamp}:{body}", Prefix: "v0="})
	now := strconv.FormatInt(time.Now().Unix(), 10)
	sig := "v0=" + hexMAC("sec", append([]byte("v0:"+now+":"), verifyBody...))
	if err := verify(slack, map[string]string{"X-Slack-Signature": sig, "X-Slack-Request-Timestamp": now},
		map[string]string{"signing_secret": "sec"}, nil, nil, nil); err != nil {
		t.Fatal(err)
	}
	stale := strconv.FormatInt(time.Now().Unix()-3600, 10)
	staleSig := "v0=" + hexMAC("sec", append([]byte("v0:"+stale+":"), verifyBody...))
	isRefusal(t, verify(slack, map[string]string{"X-Slack-Signature": staleSig, "X-Slack-Request-Timestamp": stale},
		map[string]string{"signing_secret": "sec"}, nil, nil, nil), "replay window")
}

func TestStripeCarriesTimestampAndSignaturesInOneHeader(t *testing.T) {
	stripe := scheme(Verification{Scheme: "hmac_timestamped", Secret: sp("signing_secret"), Header: sp("Stripe-Signature"),
		SignatureFormat: "kv", Payload: "{timestamp}.{body}"})
	now := strconv.FormatInt(time.Now().Unix(), 10)
	sig := hexMAC("whsec_x", append([]byte(now+"."), verifyBody...))
	if err := verify(stripe, map[string]string{"Stripe-Signature": "t=" + now + ",v1=bogus,v1=" + sig},
		map[string]string{"signing_secret": "whsec_x"}, nil, nil, nil); err != nil {
		t.Fatal(err)
	}
}

func standardWebhooks(key []byte, id, ts string) string {
	m := hmac.New(sha256.New, key)
	m.Write(append([]byte(id+"."+ts+"."), verifyBody...))
	return "v1," + base64.StdEncoding.EncodeToString(m.Sum(nil))
}

func mcpEvents() Verification {
	return scheme(Verification{Scheme: "hmac_timestamped", Secret: sp("signing_secret"), Header: sp("webhook-signature"),
		TimestampHeader: sp("webhook-timestamp"), IDHeader: sp("webhook-id"), Payload: "{id}.{timestamp}.{body}",
		SignatureFormat: "list", Encoding: "base64", SecretFormat: "whsec", RequiredHeaders: []string{"X-MCP-Subscription-Id"}})
}

func TestStandardWebhooksSignIDTimestampAndBodyWithAWhsecSecret(t *testing.T) {
	v := mcpEvents()
	v.RequiredHeaders = nil
	key := []byte("0123456789abcdef")
	now := strconv.FormatInt(time.Now().Unix(), 10)
	headers := map[string]string{"webhook-id": "msg_1", "webhook-timestamp": now,
		"webhook-signature": "v1,AAAA " + standardWebhooks(key, "msg_1", now)}
	if err := verify(v, headers, map[string]string{"signing_secret": "whsec_" + base64.StdEncoding.EncodeToString(key)}, nil, nil, nil); err != nil {
		t.Fatal(err)
	}
}

func TestARequiredHeaderMustBePresentEvenWhenTheSignatureHolds(t *testing.T) {
	key := []byte(strings.Repeat("k", 32))
	whsec := "whsec_" + base64.StdEncoding.EncodeToString(key)
	now := strconv.FormatInt(time.Now().Unix(), 10)
	headers := map[string]string{"webhook-id": "evt_1", "webhook-timestamp": now, "webhook-signature": standardWebhooks(key, "evt_1", now)}
	isRefusal(t, verify(mcpEvents(), headers, map[string]string{"signing_secret": whsec}, nil, nil, nil), "X-MCP-Subscription-Id")
	headers["X-MCP-Subscription-Id"] = "sub_1"
	if err := verify(mcpEvents(), headers, map[string]string{"signing_secret": whsec}, nil, nil, nil); err != nil {
		t.Fatal(err)
	}
}

func TestEd25519ChecksTheProvidersKeyOverTimestampAndBody(t *testing.T) {
	v := scheme(Verification{Scheme: "ed25519", Secret: sp("public_key"), Header: sp("X-Signature-Ed25519"),
		TimestampHeader: sp("X-Signature-Timestamp"), Payload: "{timestamp}{body}"})
	pub, priv, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	sig := hex.EncodeToString(ed25519.Sign(priv, append([]byte("1700000000"), verifyBody...)))
	creds := map[string]string{"public_key": hex.EncodeToString(pub)}
	headers := map[string]string{"X-Signature-Ed25519": sig, "X-Signature-Timestamp": "1700000000"}
	if err := verify(v, headers, creds, nil, nil, nil); err != nil {
		t.Fatal(err)
	}
	headers["X-Signature-Timestamp"] = "1"
	isRefusal(t, verify(v, headers, creds, nil, nil, nil), "does not match")
	headers["X-Signature-Ed25519"] = "zz"
	isRefusal(t, verify(v, headers, creds, nil, nil, nil), "does not match")
}

func TestASharedTokenMustBeRepeatedExactly(t *testing.T) {
	v := scheme(Verification{Scheme: "shared_token", Secret: sp("secret_token"), Header: sp("X-Telegram-Bot-Api-Secret-Token")})
	if err := verify(v, map[string]string{"x-telegram-bot-api-secret-token": "t"}, map[string]string{"secret_token": "t"}, nil, nil, nil); err != nil {
		t.Fatal(err)
	}
	isRefusal(t, verify(v, map[string]string{"x-telegram-bot-api-secret-token": "u"}, map[string]string{"secret_token": "t"}, nil, nil, nil), "token")
}

func examplePay() Verification {
	return scheme(Verification{Scheme: "api_lookup",
		Request: map[string]any{"method": "GET", "url": "https://api.payments.example/v3/{collection}/{body:object.id}",
			"auth": map[string]any{"username": "{config.shop_id}", "password": "{credentials.secret_key}"}},
		CollectionFrom: sp("{body:event}"), Collections: map[string]string{"payment": "payments"},
		Expect: map[string]string{"id": "{body:object.id}", "status": "{body:object.status}"},
		Later:  map[string][]string{"waiting_for_capture": {"succeeded", "canceled"}}})
}

func TestAPILookupBelievesANotificationTheAPIConfirms(t *testing.T) {
	var calls []string
	lookup := func(_ context.Context, method, url string, auth *BasicAuth) (int, any, error) {
		calls = append(calls, method+" "+url+" "+auth.Username+":"+auth.Password)
		return 200, map[string]any{"id": "p1", "status": "succeeded"}, nil
	}
	note := map[string]any{"event": "payment.succeeded", "object": map[string]any{"id": "p1", "status": "succeeded"}}
	if err := verify(examplePay(), nil, map[string]string{"secret_key": "live_x"}, note, map[string]any{"shop_id": "42"}, lookup); err != nil {
		t.Fatal(err)
	}
	if len(calls) != 1 || calls[0] != "GET https://api.payments.example/v3/payments/p1 42:live_x" {
		t.Fatalf("calls %v", calls)
	}
}

func TestAPILookupAcceptsALaterStateAndRefusesOthers(t *testing.T) {
	waiting := map[string]any{"event": "payment.waiting_for_capture", "object": map[string]any{"id": "p1", "status": "waiting_for_capture"}}
	answer := func(status string) APILookup {
		return func(context.Context, string, string, *BasicAuth) (int, any, error) {
			return 200, map[string]any{"id": "p1", "status": status}, nil
		}
	}
	cfg := map[string]any{"shop_id": "42"}
	if err := verify(examplePay(), nil, map[string]string{"secret_key": "k"}, waiting, cfg, answer("succeeded")); err != nil {
		t.Fatal(err)
	}
	isRefusal(t, verify(examplePay(), nil, map[string]string{"secret_key": "k"}, waiting, cfg, answer("pending")), "the API holds status")
}

func TestNoVerificationPassesEverything(t *testing.T) {
	if err := verify(scheme(Verification{Scheme: "none"}), nil, nil, nil, nil, nil); err != nil {
		t.Fatal(err)
	}
}

func TestASourceOverridesOnlyTheSettingsItsEntryMakesConfigurable(t *testing.T) {
	generic := scheme(Verification{Scheme: "hmac", Secret: sp("signing_secret"), Header: sp("X-Webhook-Signature"),
		Configurable: []string{"header", "algorithm", "prefix"}})
	mine, err := Configured(generic, map[string]any{"header": "X-Hasura-Sig", "algorithm": "sha1", "secret": "x"})
	if err != nil {
		t.Fatal(err)
	}
	if *mine.Header != "X-Hasura-Sig" || mine.Algorithm != "sha1" || *mine.Secret != "signing_secret" {
		t.Fatalf("got %+v", mine)
	}
	var inv *ValidationError
	if _, err := Configured(generic, map[string]any{"algorithm": "md5"}); !errors.As(err, &inv) {
		t.Fatalf("md5 accepted: %v", err)
	}
}

func TestASourceCannotSwitchToASchemeThatSignsNothingOfItsOwn(t *testing.T) {
	generic := scheme(Verification{Scheme: "hmac", Secret: sp("signing_secret"), Header: sp("X-Webhook-Signature"), Configurable: []string{"scheme"}})
	for _, s := range []string{"none", "api_lookup", "ed25519"} {
		_, err := Configured(generic, map[string]any{"scheme": s})
		isRefusal(t, err, "a source verifies by")
	}
	for _, s := range []string{"hmac", "hmac_timestamped", "shared_token"} {
		v, err := Configured(generic, map[string]any{"scheme": s})
		if err != nil || v.Scheme != s {
			t.Fatalf("%s: %v", s, err)
		}
	}
}
