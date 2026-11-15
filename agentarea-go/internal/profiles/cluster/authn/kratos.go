package authn

import (
	"encoding/base64"
	"encoding/json"
	"errors"
	"strings"
)

// kratos verifies Kratos session JWTs against the static JWKS
// (providers/kratos.py KratosAuthProvider).
type kratos struct {
	jwks any
	// initErr is the ValueError Python's constructor raises (empty or
	// undecodable JWKS); Python rebuilds the provider per request, so every
	// verification then "throws".
	initErr  error
	issuer   string
	audience string
}

func newKratos(cfg Config) *kratos {
	k := &kratos{issuer: cfg.Issuer, audience: cfg.Audience}
	if cfg.JWKSB64 == "" {
		k.initErr = errors.New("jwks_b64 is required for KratosAuthProvider")
		return k
	}
	text := cfg.JWKSB64
	if !strings.HasPrefix(strings.TrimLeft(text, " \t\n\r\v\f"), "{") {
		raw, err := pyB64Decode(text)
		if err != nil {
			k.initErr = errors.New("Failed to decode JWKS: " + err.Error()) //nolint:staticcheck // Python's message
			return k
		}
		text = string(raw)
	}
	v, err := loadJSON([]byte(text))
	if err != nil {
		k.initErr = errors.New("Failed to decode JWKS: " + err.Error()) //nolint:staticcheck // Python's message
		return k
	}
	k.jwks = v
	return k
}

// pyB64Decode is base64.b64decode without validation: characters outside
// the alphabet are dropped, padding is required.
func pyB64Decode(s string) ([]byte, error) {
	var b strings.Builder
	for i := range len(s) {
		c := s[i]
		if (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '+' || c == '/' || c == '=' {
			b.WriteByte(c)
		}
	}
	out, err := base64.StdEncoding.DecodeString(b.String())
	if err != nil {
		return nil, errors.New("Incorrect padding") //nolint:staticcheck // binascii's message
	}
	return out, nil
}

// kratosResult is AuthResult: authenticated with a user, or refused with error.
type kratosResult struct {
	userID string
	email  string
	error  string
}

func (r kratosResult) authenticated() bool { return r.userID != "" }

// verify is KratosAuthProvider.verify_token; err is set only where Python's
// provider construction raises.
func (k *kratos) verify(token string, now float64) (kratosResult, error) {
	if k.initErr != nil {
		return kratosResult{}, k.initErr
	}
	refuse := func(msg string) (kratosResult, error) { return kratosResult{error: msg}, nil }
	fromErr := func(err error) (kratosResult, error) {
		if je, ok := asJWTError(err); ok && je.invalidToken() {
			if je.class == clsExpired {
				return refuse("Token has expired")
			}
			return refuse("Invalid token: " + je.msg)
		}
		return refuse("Error verifying token: " + err.Error())
	}

	header, err := unverifiedHeader(token)
	if err != nil {
		return fromErr(err)
	}
	if !pyTruthy(header["kid"]) {
		return refuse("Token header missing key ID")
	}
	kid, _ := header["kid"].(string)
	jwkData, err := findKeyByKid(k.jwks, kid)
	if err != nil {
		return fromErr(err)
	}
	if jwkData == nil {
		return refuse("Key not found in JWKS")
	}
	key, err := ecFromJWK(jwkData)
	if err != nil {
		return fromErr(err)
	}
	audience, issuer := k.audience, k.issuer
	payload, err := decode(token, decodeOptions{
		verifySignature: true,
		key:             key,
		algorithms:      []string{"ES256"},
		audience:        &audience,
		issuer:          &issuer,
		require:         []string{"exp", "iat", "sub", "aud", "iss"},
		now:             now,
	})
	if err != nil {
		return fromErr(err)
	}
	if msg, failed := k.validateClaims(payload, now); failed {
		return refuse(msg)
	}
	userID, _ := payload["sub"].(string)
	if userID == "" {
		return refuse("Token missing user ID")
	}
	email, _ := payload["email"].(string)
	return kratosResult{userID: userID, email: email}, nil
}

// validateClaims is BaseAuthProvider._validate_claims after PyJWT has run:
// it can only fail on values PyJWT accepted as integers but Python then
// compares with a float.
func (k *kratos) validateClaims(payload map[string]any, now float64) (string, bool) {
	for _, c := range []struct{ claim, op string }{{"exp", "<"}, {"nbf", ">"}} {
		switch v := payload[c.claim].(type) {
		case string:
			if v != "" {
				return "Error verifying token: '" + c.op + "' not supported between instances of 'str' and 'float'", true
			}
		case json.Number:
			f, err := v.Float64()
			if err != nil || f == 0 {
				continue
			}
			if (c.op == "<" && f < now) || (c.op == ">" && f > now) {
				return "Invalid token claims", true
			}
		}
	}
	if iss, _ := payload["iss"].(string); iss != k.issuer {
		return "Invalid token claims", true
	}
	return "", false
}

// findKeyByKid is BaseAuthProvider._find_key_by_kid over whatever JSON the
// JWKS holds; err carries the AttributeError/TypeError text Python reports.
func findKeyByKid(jwks any, kid string) (map[string]any, error) {
	obj, ok := jwks.(map[string]any)
	if !ok {
		return nil, errors.New("'" + pyTypeName(jwks) + "' object has no attribute 'get'")
	}
	raw, present := obj["keys"]
	if !present {
		return nil, nil
	}
	var items []any
	switch v := raw.(type) {
	case []any:
		items = v
	case map[string]any:
		if len(v) > 0 {
			return nil, errors.New("'str' object has no attribute 'get'")
		}
	case string:
		if v != "" {
			return nil, errors.New("'str' object has no attribute 'get'")
		}
	default:
		return nil, errors.New("'" + pyTypeName(raw) + "' object is not iterable")
	}
	for _, item := range items {
		key, ok := item.(map[string]any)
		if !ok {
			return nil, errors.New("'" + pyTypeName(item) + "' object has no attribute 'get'")
		}
		if v, isStr := key["kid"].(string); isStr && v == kid {
			return key, nil
		}
	}
	return nil, nil
}

func pyTypeName(v any) string {
	switch x := v.(type) {
	case nil:
		return "NoneType"
	case bool:
		return "bool"
	case string:
		return "str"
	case json.Number:
		if strings.ContainsAny(x.String(), ".eE") {
			return "float"
		}
		return "int"
	case []any:
		return "list"
	case map[string]any:
		return "dict"
	}
	return "object"
}
