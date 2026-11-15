package domain

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/hmac"
	"crypto/sha1" //nolint:gosec // providers sign with SHA-1 (hmac algorithm sha1)
	"crypto/sha256"
	"crypto/sha512"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
	"fmt"
	"hash"
	"math"
	"sort"
	"strconv"
	"strings"
	"time"
)

// VerificationError is a request that does not prove where it came from.
type VerificationError struct{ Msg string }

func (e *VerificationError) Error() string { return e.Msg }

func refuse(format string, args ...any) error {
	return &VerificationError{Msg: fmt.Sprintf(format, args...)}
}

// sourceSchemes are the schemes a source may switch itself to.
func sourceSchemes() []string { return []string{"hmac", "hmac_timestamped", "shared_token"} }

// BasicAuth is an api_lookup request's basic credentials.
type BasicAuth struct{ Username, Password string }

// APILookup reads the provider's API for api_lookup: (method, url, auth) -> (status, json body).
// An error is the provider being unreachable, or a VerificationError for a refused URL.
type APILookup func(ctx context.Context, method, url string, auth *BasicAuth) (int, any, error)

func headerOf(headers map[string]string, name *string) (string, error) {
	if name == nil || *name == "" {
		return "", refuse("the entry names no header to verify")
	}
	want := strings.ToLower(*name)
	for k, v := range headers {
		if strings.ToLower(k) == want {
			return v, nil
		}
	}
	return "", refuse("missing header %s", *name)
}

func secretBytes(secret string, v Verification) ([]byte, error) {
	if v.SecretFormat == "whsec" {
		b, err := pyB64Decode(strings.TrimPrefix(secret, "whsec_"))
		if err != nil {
			return nil, refuse("the stored secret is not whsec_<base64>")
		}
		return b, nil
	}
	return []byte(secret), nil
}

// pyB64Decode is base64.b64decode without validate: characters outside the alphabet are
// dropped, then the padding must be right.
func pyB64Decode(s string) ([]byte, error) {
	var b strings.Builder
	for _, r := range s {
		if r >= 'A' && r <= 'Z' || r >= 'a' && r <= 'z' || r >= '0' && r <= '9' || r == '+' || r == '/' || r == '=' {
			b.WriteRune(r)
		}
	}
	return base64.StdEncoding.DecodeString(b.String())
}

func hasher(algorithm string) func() hash.Hash {
	switch algorithm {
	case "sha1":
		return sha1.New
	case "sha384":
		return sha512.New384
	case "sha512":
		return sha512.New
	}
	return sha256.New
}

func digest(v Verification, key, payload []byte) string {
	m := hmac.New(hasher(v.Algorithm), key)
	m.Write(payload)
	raw := m.Sum(nil)
	if v.Encoding == "hex" {
		return hex.EncodeToString(raw)
	}
	return base64.StdEncoding.EncodeToString(raw)
}

func equal(a, b string) bool { return subtle.ConstantTimeCompare([]byte(a), []byte(b)) == 1 }

func fresh(timestamp string, tolerance int, now time.Time) error {
	sent, err := strconv.ParseInt(strings.TrimSpace(timestamp), 10, 64)
	if err != nil {
		return refuse("timestamp %s is not unix seconds", PyRepr(timestamp))
	}
	nowSecs := float64(now.UnixNano()) / 1e9
	if math.Abs(nowSecs-float64(sent)) > float64(tolerance) {
		return refuse("timestamp outside the replay window")
	}
	return nil
}

// VerifyHMAC is a header carrying prefix + HMAC(secret, body).
func VerifyHMAC(v Verification, headers map[string]string, body []byte, secret string) error {
	sig, err := headerOf(headers, v.Header)
	if err != nil {
		return err
	}
	key, err := secretBytes(secret, v)
	if err != nil {
		return err
	}
	if !equal(v.Prefix+digest(v, key, body), strings.TrimSpace(sig)) {
		return refuse("signature does not match")
	}
	return nil
}

func signatureParts(v Verification, value string) (*string, []string) {
	switch v.SignatureFormat {
	case "kv":
		var ts *string
		var candidates []string
		for _, el := range strings.Split(value, ",") {
			k, part, _ := strings.Cut(strings.TrimSpace(el), "=")
			switch k {
			case v.TimestampKey:
				p := part
				ts = &p
			case v.SignatureKey:
				candidates = append(candidates, part)
			}
		}
		return ts, candidates
	case "list":
		var candidates []string
		for _, part := range strings.Fields(value) {
			k, sig, _ := strings.Cut(part, ",")
			if k == v.SignatureKey {
				candidates = append(candidates, sig)
			}
		}
		return nil, candidates
	}
	return nil, []string{strings.TrimPrefix(strings.TrimSpace(value), v.Prefix)}
}

// VerifyHMACTimestamped is HMAC over a text of timestamp, delivery id and body, in a replay window.
func VerifyHMACTimestamped(v Verification, headers map[string]string, body []byte, secret string, now time.Time) error {
	value, err := headerOf(headers, v.Header)
	if err != nil {
		return err
	}
	tsp, candidates := signatureParts(v, value)
	var ts string
	if tsp != nil {
		ts = *tsp
	} else if ts, err = headerOf(headers, v.TimestampHeader); err != nil {
		return err
	}
	if len(candidates) == 0 {
		return refuse("the signature header carries no signature")
	}
	if err := fresh(ts, v.ToleranceSecs, now); err != nil {
		return err
	}
	id := ""
	if strings.Contains(v.Payload, "{id}") {
		if id, err = headerOf(headers, v.IDHeader); err != nil {
			return err
		}
	}
	text := strings.ReplaceAll(strings.ReplaceAll(v.Payload, "{timestamp}", ts), "{id}", id)
	signed := bytes.ReplaceAll([]byte(text), []byte("{body}"), body)
	key, err := secretBytes(secret, v)
	if err != nil {
		return err
	}
	expected := digest(v, key, signed)
	ok := false
	for _, c := range candidates {
		if equal(expected, c) {
			ok = true
		}
	}
	if !ok {
		return refuse("signature does not match")
	}
	return nil
}

// VerifyEd25519 is a signature by the provider's key (hex) over timestamp and body.
func VerifyEd25519(v Verification, headers map[string]string, body []byte, publicKey string) error {
	sigHex, err := headerOf(headers, v.Header)
	if err != nil {
		return err
	}
	ts := ""
	if v.TimestampHeader != nil {
		if ts, err = headerOf(headers, v.TimestampHeader); err != nil {
			return err
		}
	}
	payload := bytes.ReplaceAll([]byte(strings.ReplaceAll(v.Payload, "{timestamp}", ts)), []byte("{body}"), body)
	key, kerr := hex.DecodeString(strings.TrimSpace(publicKey))
	sig, serr := hex.DecodeString(strings.TrimSpace(sigHex))
	if kerr != nil || serr != nil || len(key) != ed25519.PublicKeySize || !ed25519.Verify(ed25519.PublicKey(key), payload, sig) {
		return refuse("signature does not match")
	}
	return nil
}

// VerifySharedToken is the provider repeating the token it was given.
func VerifySharedToken(v Verification, headers map[string]string, secret string) error {
	got, err := headerOf(headers, v.Header)
	if err != nil {
		return err
	}
	if !equal(got, secret) {
		return refuse("token does not match")
	}
	return nil
}

// Configured is the entry's scheme with the settings this source may override taken from its
// config. A value the scheme cannot take is a ValidationError; a scheme outside the source
// schemes is a VerificationError, so no source is unsigned.
func Configured(v Verification, config map[string]any) (Verification, error) {
	overrides := map[string]string{}
	for _, key := range v.Configurable {
		raw, ok := config[key]
		if !ok || raw == nil {
			continue
		}
		text, isText := raw.(string)
		if !isText {
			text, _ = Scalar(raw)
		}
		if text == "" {
			continue
		}
		overrides[key] = text
	}
	if s, ok := overrides["scheme"]; ok {
		allowed := false
		for _, a := range sourceSchemes() {
			allowed = allowed || a == s
		}
		if !allowed {
			return v, refuse("a source verifies by %s, not %s", strings.Join(sourceSchemes(), ", "), PyRepr(s))
		}
	}
	if len(overrides) == 0 {
		return v, nil
	}
	out := v
	keys := make([]string, 0, len(overrides))
	for k := range overrides {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		if err := out.set(k, overrides[k]); err != nil {
			return v, err
		}
	}
	return out, out.validate()
}

func (v *Verification) set(key, val string) error {
	p := func(s string) *string { return &s }
	switch key {
	case "scheme":
		v.Scheme = val
	case "secret":
		v.Secret = p(val)
	case "header":
		v.Header = p(val)
	case "algorithm":
		v.Algorithm = val
	case "encoding":
		v.Encoding = val
	case "prefix":
		v.Prefix = val
	case "timestamp_header":
		v.TimestampHeader = p(val)
	case "id_header":
		v.IDHeader = p(val)
	case "payload":
		v.Payload = val
	case "signature_format":
		v.SignatureFormat = val
	case "timestamp_key":
		v.TimestampKey = val
	case "signature_key":
		v.SignatureKey = val
	case "secret_format":
		v.SecretFormat = val
	case "collection_from":
		v.CollectionFrom = p(val)
	case "tolerance_seconds":
		n, err := strconv.Atoi(strings.TrimSpace(val))
		if err != nil {
			return &ValidationError{Msg: "tolerance_seconds: Input should be a valid integer, unable to parse string as an integer"}
		}
		v.ToleranceSecs = n
	default:
		return &ValidationError{Msg: key + ": the setting cannot be given as text"}
	}
	return nil
}

// Verify is verify_request: the body to record, or a VerificationError unless the request
// proves its sender. api_lookup records what the provider's API holds in place of the claim.
func Verify(ctx context.Context, v Verification, headers map[string]string, raw []byte, body any,
	credentials map[string]string, config map[string]any, lookup APILookup, now time.Time,
) (any, error) {
	switch v.Scheme {
	case "none":
		return body, nil
	case "api_lookup":
		return VerifyAPILookup(ctx, v, body, credentials, config, lookup)
	}
	secret := ""
	if v.Secret != nil {
		secret = credentials[*v.Secret]
	}
	if secret == "" {
		name := "secret"
		if v.Secret != nil && *v.Secret != "" {
			name = *v.Secret
		}
		return nil, refuse("the source has no %s to verify with", name)
	}
	for _, name := range v.RequiredHeaders {
		got, err := headerOf(headers, &name)
		if err != nil {
			return nil, err
		}
		if got == "" {
			return nil, refuse("empty header %s", name)
		}
	}
	var err error
	switch v.Scheme {
	case "hmac":
		err = VerifyHMAC(v, headers, raw, secret)
	case "hmac_timestamped":
		err = VerifyHMACTimestamped(v, headers, raw, secret, now)
	case "ed25519":
		err = VerifyEd25519(v, headers, raw, secret)
	default:
		err = VerifySharedToken(v, headers, secret)
	}
	if err != nil {
		return nil, err
	}
	return body, nil
}

// VerifyAPILookup believes the notification only when the provider's API holds the object in
// that state, and returns the body with the record paths taken from the fetched object.
func VerifyAPILookup(ctx context.Context, v Verification, body any, credentials map[string]string,
	config map[string]any, lookup APILookup,
) (any, error) {
	if v.Request == nil {
		return nil, refuse("an api_lookup entry names no request")
	}
	values := map[string]any{"credentials": stringMap(credentials), "config": config}
	c := TemplateContext{Body: body, Values: values}
	if v.CollectionFrom != nil {
		notified, _ := Render(*v.CollectionFrom, c)
		object, state, _ := strings.Cut(notified, ".")
		collection, ok := v.Collections[object]
		if !ok {
			return nil, refuse("%s names no object the API can be asked about", PyRepr(notified))
		}
		values["collection"] = collection
		values["notified"] = map[string]any{"object": object, "state": state}
	}
	c = TemplateContext{Body: body, Values: values}
	rest := map[string]any{}
	for k, val := range v.Request {
		if k != "url" {
			rest[k] = val
		}
	}
	request, _ := RenderValue(rest, c).(map[string]any)
	urlTpl, _ := v.Request["url"].(string)
	url, ok := RenderURL(urlTpl, c)
	if urlTpl == "" || !ok {
		return nil, refuse("the lookup URL could not be filled in from this notification")
	}
	var auth *BasicAuth
	if a, isMap := request["auth"].(map[string]any); isMap {
		u, _ := Scalar(a["username"])
		pw, _ := Scalar(a["password"])
		auth = &BasicAuth{Username: u, Password: pw}
	}
	method := "GET"
	if m, _ := Scalar(request["method"]); m != "" {
		method = m
	}
	status, fetchedAny, err := lookup(ctx, method, url, auth)
	if err != nil {
		return nil, err
	}
	fetched, isMap := fetchedAny.(map[string]any)
	if status != 200 || !isMap {
		return nil, refuse("the provider's API answered %d", status)
	}
	fields := make([]string, 0, len(v.Expect))
	for f := range v.Expect {
		fields = append(fields, f)
	}
	sort.Strings(fields)
	for _, field := range fields {
		var wanted any
		if w, ok := Render(v.Expect[field], c); ok {
			wanted = w
		}
		current := fetched[field]
		if JSONEqual(current, wanted) {
			continue
		}
		if w, isText := wanted.(string); isText {
			later := false
			for _, s := range v.Later[w] {
				later = later || JSONEqual(current, s)
			}
			if later {
				continue
			}
		}
		return nil, refuse("the API holds %s=%v, not %v", field, current, wanted)
	}
	if len(v.Record) == 0 {
		return body, nil
	}
	recorded, isObj := body.(map[string]any)
	if !isObj {
		return nil, refuse("a notification recorded from the lookup must be an object")
	}
	withFetched := map[string]any{"fetched": fetched}
	for k, val := range values {
		withFetched[k] = val
	}
	fc := TemplateContext{Body: body, Values: withFetched}
	paths := make([]string, 0, len(v.Record))
	for p := range v.Record {
		paths = append(paths, p)
	}
	sort.Strings(paths)
	for _, path := range paths {
		value := RenderValue(v.Record[path], fc)
		if value == nil {
			return nil, refuse("%s could not be recorded from the provider's object", path)
		}
		recorded = withPath(recorded, strings.Split(path, "."), value)
	}
	return recorded, nil
}

func withPath(data map[string]any, steps []string, value any) map[string]any {
	out := make(map[string]any, len(data)+1)
	for k, v := range data {
		out[k] = v
	}
	if len(steps) == 1 {
		out[steps[0]] = value
		return out
	}
	inner, _ := out[steps[0]].(map[string]any)
	out[steps[0]] = withPath(inner, steps[1:], value)
	return out
}

// HandshakeAnswer is what to answer a provider's endpoint check, false when the request is an event.
func HandshakeAnswer(e SourceTypeEntry, headers map[string]string, body any) (any, bool) {
	c := TemplateContext{Body: body, Headers: headers}
	for _, h := range e.Handshake {
		if got, ok := Render(h.When, c); ok && got == h.Equals {
			return RenderValue(h.Respond, c), true
		}
	}
	return nil, false
}

// SourceSignal is a webhook request that reports on its source.
type SourceSignal struct {
	Signal, Key, Reason string
}

// SignalOf is the signal a request is, nil when it is an event; a matching signal with no key
// is an error.
func SignalOf(e SourceTypeEntry, headers map[string]string, body any) (*SourceSignal, error) {
	c := TemplateContext{Body: body, Headers: headers}
	for _, s := range e.Signals {
		if got, ok := Render(s.When, c); !ok || got != s.Equals {
			continue
		}
		key, ok := Render(s.Key, c)
		if !ok || key == "" {
			return nil, Invalid(fmt.Sprintf("the %s signal of %s renders no key", s.Signal, e.Slug))
		}
		reason, _ := Render(s.Reason, c)
		return &SourceSignal{Signal: s.Signal, Key: key, Reason: reason}, nil
	}
	return nil, nil
}
