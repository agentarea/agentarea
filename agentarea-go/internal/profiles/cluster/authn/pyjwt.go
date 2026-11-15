package authn

import (
	"bytes"
	"crypto"
	"crypto/ecdsa"
	"crypto/hmac"
	"crypto/rsa"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"math"
	"math/big"
	"strconv"
	"strings"
	"unicode/utf8"
)

// The decoder below is PyJWT 2.15.1's decode (api_jws.py, api_jwt.py), step
// for step: the same checks in the same order with the same messages, because
// Kratos refusals reach the client as "Invalid token: <message>" and the
// Hydra and turn paths branch on the exception class.

// jwtClass is a PyJWT exception class.
type jwtClass int

const (
	clsInvalidToken jwtClass = iota
	clsDecode
	clsInvalidSignature
	clsExpired
	clsInvalidAudience
	clsInvalidIssuer
	clsInvalidIssuedAt
	clsImmature
	clsInvalidAlgorithm
	clsMissingClaim
	clsInvalidSubject
	clsInvalidJTI
	// clsInvalidKey is a PyJWTError but not an InvalidTokenError.
	clsInvalidKey
)

type jwtError struct {
	class jwtClass
	msg   string
}

func (e *jwtError) Error() string { return e.msg }

// invalidToken: an InvalidTokenError (every class but InvalidKeyError).
func (e *jwtError) invalidToken() bool { return e.class != clsInvalidKey }

// decodeError: a DecodeError (InvalidSignatureError is one).
func (e *jwtError) decodeError() bool { return e.class == clsDecode || e.class == clsInvalidSignature }

func jwtErr(class jwtClass, msg string) *jwtError { return &jwtError{class: class, msg: msg} }

func asJWTError(err error) (*jwtError, bool) {
	var je *jwtError
	ok := errors.As(err, &je)
	return je, ok
}

const base64URLAlphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"

// decodeSegment is PyJWS._decode_base64url_segment.
func decodeSegment(segment, name string) ([]byte, error) {
	bad := jwtErr(clsDecode, "Invalid "+name+" padding")
	stripped := segment
	padding := 0
	for strings.HasSuffix(stripped, "=") {
		stripped = stripped[:len(stripped)-1]
		padding++
		if padding > 2 {
			return nil, bad
		}
	}
	if padding > 0 && len(segment)%4 != 0 {
		return nil, bad
	}
	if len(stripped)%4 == 1 {
		return nil, bad
	}
	for i := range len(stripped) {
		if strings.IndexByte(base64URLAlphabet, stripped[i]) < 0 {
			return nil, bad
		}
	}
	decoded, err := base64.RawURLEncoding.DecodeString(stripped)
	if err != nil {
		return nil, bad
	}
	if base64.RawURLEncoding.EncodeToString(decoded) != stripped {
		return nil, bad
	}
	return decoded, nil
}

// jws is a token split and decoded as PyJWS._load returns it.
type jws struct {
	payload      []byte
	signingInput []byte
	header       map[string]any
	signature    []byte
}

// loadJSON is json.loads of a segment: UTF-8 required, numbers kept exact.
func loadJSON(data []byte) (any, error) {
	if !utf8.Valid(data) {
		return nil, errors.New("'utf-8' codec can't decode bytes")
	}
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.UseNumber()
	var v any
	if err := dec.Decode(&v); err != nil {
		return nil, err
	}
	if strings.TrimLeft(string(data[dec.InputOffset():]), " \t\n\r") != "" {
		return nil, errors.New("extra data")
	}
	return v, nil
}

// load is PyJWS._load.
func load(token string) (*jws, error) {
	cut := strings.LastIndexByte(token, '.')
	if cut < 0 {
		return nil, jwtErr(clsDecode, "Not enough segments")
	}
	signingInput, crypto := token[:cut], token[cut+1:]
	headerSeg, payloadSeg, ok := strings.Cut(signingInput, ".")
	if !ok {
		return nil, jwtErr(clsDecode, "Not enough segments")
	}
	headerData, err := decodeSegment(headerSeg, "header")
	if err != nil {
		return nil, err
	}
	raw, err := loadJSON(headerData)
	if err != nil {
		return nil, jwtErr(clsDecode, "Invalid header string: "+err.Error())
	}
	header, ok := raw.(map[string]any)
	if !ok {
		return nil, jwtErr(clsDecode, "Invalid header string: must be a json object")
	}
	var payload []byte
	if b64False(header) {
		if payloadSeg != "" {
			return nil, jwtErr(clsDecode, "Payload segment must be empty when 'b64' is false.")
		}
	} else if payload, err = decodeSegment(payloadSeg, "payload"); err != nil {
		return nil, err
	}
	signature, err := decodeSegment(crypto, "crypto")
	if err != nil {
		return nil, err
	}
	return &jws{payload: payload, signingInput: []byte(signingInput), header: header, signature: signature}, nil
}

func b64False(header map[string]any) bool {
	v, ok := header["b64"]
	b, isBool := v.(bool)
	return ok && isBool && !b
}

// validateHeaders is PyJWS._validate_headers (decoding).
func validateHeaders(header map[string]any) error {
	if kid, ok := header["kid"]; ok {
		if _, isStr := kid.(string); !isStr {
			return jwtErr(clsInvalidToken, "Key ID header parameter must be a string")
		}
	}
	crit, ok := header["crit"]
	if !ok {
		return nil
	}
	list, isList := crit.([]any)
	if !isList || len(list) == 0 {
		return jwtErr(clsInvalidToken, "Invalid 'crit' header: must be a non-empty list")
	}
	for _, ext := range list {
		name, isStr := ext.(string)
		if !isStr {
			return jwtErr(clsInvalidToken, "Invalid 'crit' header: values must be strings")
		}
		if name != "b64" {
			return jwtErr(clsInvalidToken, "Unsupported critical extension: "+name)
		}
		if _, present := header[name]; !present {
			return jwtErr(clsInvalidToken, "Critical extension '"+name+"' is missing from headers")
		}
	}
	return nil
}

// unverifiedHeader is jwt.get_unverified_header.
func unverifiedHeader(token string) (map[string]any, error) {
	t, err := load(token)
	if err != nil {
		return nil, err
	}
	if err := validateHeaders(t.header); err != nil {
		return nil, err
	}
	return t.header, nil
}

// verifyKey checks a signature for one algorithm. A key of the wrong kind
// for the algorithm is an InvalidKeyError when PyJWT raises one, and a plain
// error (500 in Python) when PyJWT fails some other way.
type verifyKey interface {
	verify(alg string, signingInput, signature []byte) (bool, error)
}

type hmacKey []byte

func (k hmacKey) verify(alg string, msg, sig []byte) (bool, error) {
	if alg != "HS256" {
		return false, errors.New("HMAC key used for " + alg)
	}
	mac := hmac.New(sha256.New, k)
	mac.Write(msg)
	return hmac.Equal(sig, mac.Sum(nil)), nil
}

type ecKey struct{ pub *ecdsa.PublicKey }

func (k ecKey) verify(alg string, msg, sig []byte) (bool, error) {
	if alg != "ES256" {
		return false, errors.New("EC key used for " + alg)
	}
	if name := curveName(k.pub); name != "secp256r1" {
		return false, jwtErr(clsInvalidKey, "The key's curve '"+name+"' does not match the expected curve 'secp256r1' for this algorithm")
	}
	if len(sig) != 64 {
		return false, nil
	}
	digest := sha256.Sum256(msg)
	r := new(big.Int).SetBytes(sig[:32])
	s := new(big.Int).SetBytes(sig[32:])
	return ecdsa.Verify(k.pub, digest[:], r, s), nil
}

type rsaKey struct{ pub *rsa.PublicKey }

func (k rsaKey) verify(alg string, msg, sig []byte) (bool, error) {
	if alg != "RS256" {
		return false, errors.New("RSA key used for " + alg)
	}
	digest := sha256.Sum256(msg)
	return rsa.VerifyPKCS1v15(k.pub, crypto.SHA256, digest[:], sig) == nil, nil
}

// decodeOptions are the arguments of jwt.decode the callers use.
type decodeOptions struct {
	verifySignature bool
	key             verifyKey
	algorithms      []string
	audience        *string
	issuer          *string
	require         []string
	now             float64
}

// decode is jwt.decode: the token's claims, or the error PyJWT raises.
func decode(token string, o decodeOptions) (map[string]any, error) {
	_, payload, err := decodeComplete(token, o)
	return payload, err
}

// decodeComplete is jwt.decode_complete: header and claims.
func decodeComplete(token string, o decodeOptions) (map[string]any, map[string]any, error) {
	t, err := load(token)
	if err != nil {
		return nil, nil, err
	}
	if err := validateHeaders(t.header); err != nil {
		return nil, nil, err
	}
	if b64False(t.header) {
		crit, _ := t.header["crit"].([]any)
		listed := false
		for _, c := range crit {
			if c == "b64" {
				listed = true
			}
		}
		if !listed {
			return nil, nil, jwtErr(clsInvalidToken, "The 'b64' header parameter requires 'b64' to be listed in 'crit'.")
		}
		return nil, nil, jwtErr(clsDecode, `It is required that you pass in a value for the "detached_payload" argument to decode a message having the b64 header set to false.`)
	}
	if o.verifySignature {
		if err := verifySignature(t, o); err != nil {
			return nil, nil, err
		}
	}
	raw, err := loadJSON(t.payload)
	if err != nil {
		return nil, nil, jwtErr(clsDecode, "Invalid payload string: "+err.Error())
	}
	payload, ok := raw.(map[string]any)
	if !ok {
		return nil, nil, jwtErr(clsDecode, "Invalid payload string: must be a json object")
	}
	if err := validateClaims(payload, o); err != nil {
		return nil, nil, err
	}
	return t.header, payload, nil
}

func verifySignature(t *jws, o decodeOptions) error {
	rawAlg, ok := t.header["alg"]
	if !ok {
		return jwtErr(clsInvalidAlgorithm, "Algorithm not specified")
	}
	alg, isStr := rawAlg.(string)
	allowed := false
	for _, a := range o.algorithms {
		if isStr && alg == a {
			allowed = true
		}
	}
	if !allowed {
		return jwtErr(clsInvalidAlgorithm, "The specified alg value is not allowed")
	}
	valid, err := o.key.verify(alg, t.signingInput, t.signature)
	if err != nil {
		return err
	}
	if !valid {
		return jwtErr(clsInvalidSignature, "Signature verification failed")
	}
	return nil
}

// validateClaims is PyJWT._validate_claims with every verify_* option on
// when the signature is verified and off otherwise (PyJWT._merge_options).
func validateClaims(payload map[string]any, o decodeOptions) error {
	for _, claim := range o.require {
		if v, ok := payload[claim]; !ok || v == nil {
			return missingClaim(claim)
		}
	}
	if !o.verifySignature {
		return nil
	}
	if v, ok := payload["iat"]; ok {
		iat, ok := pyInt(v)
		if !ok {
			return jwtErr(clsInvalidIssuedAt, "Issued At claim (iat) must be an integer.")
		}
		if iat > o.now {
			return jwtErr(clsImmature, "The token is not yet valid (iat)")
		}
	}
	if v, ok := payload["nbf"]; ok {
		nbf, ok := pyInt(v)
		if !ok {
			return jwtErr(clsDecode, "Not Before claim (nbf) must be an integer.")
		}
		if nbf > o.now {
			return jwtErr(clsImmature, "The token is not yet valid (nbf)")
		}
	}
	if v, ok := payload["exp"]; ok {
		exp, ok := pyInt(v)
		if !ok {
			return jwtErr(clsDecode, "Expiration Time claim (exp) must be an integer.")
		}
		if exp <= o.now {
			return jwtErr(clsExpired, "Signature has expired")
		}
	}
	if o.issuer != nil {
		v, ok := payload["iss"]
		if !ok {
			return missingClaim("iss")
		}
		iss, isStr := v.(string)
		if !isStr {
			return jwtErr(clsInvalidIssuer, "Payload Issuer (iss) must be a string")
		}
		if iss != *o.issuer {
			return jwtErr(clsInvalidIssuer, "Invalid issuer")
		}
	}
	if err := validateAudience(payload, o.audience); err != nil {
		return err
	}
	if v, ok := payload["sub"]; ok {
		if _, isStr := v.(string); !isStr {
			return jwtErr(clsInvalidSubject, "Subject must be a string")
		}
	}
	if v, ok := payload["jti"]; ok {
		if _, isStr := v.(string); !isStr {
			return jwtErr(clsInvalidJTI, "JWT ID must be a string")
		}
	}
	return nil
}

func missingClaim(claim string) *jwtError {
	return jwtErr(clsMissingClaim, `Token is missing the "`+claim+`" claim`)
}

func validateAudience(payload map[string]any, audience *string) error {
	v, present := payload["aud"]
	if audience == nil {
		if !present || !pyTruthy(v) {
			return nil
		}
		return jwtErr(clsInvalidAudience, "Invalid audience")
	}
	if !present || !pyTruthy(v) {
		return missingClaim("aud")
	}
	var claims []any
	switch a := v.(type) {
	case string:
		claims = []any{a}
	case []any:
		claims = a
	default:
		return jwtErr(clsInvalidAudience, "Invalid claim format in token")
	}
	matched := false
	for _, c := range claims {
		s, isStr := c.(string)
		if !isStr {
			return jwtErr(clsInvalidAudience, "Invalid claim format in token")
		}
		if s == *audience {
			matched = true
		}
	}
	if !matched {
		return jwtErr(clsInvalidAudience, "Audience doesn't match")
	}
	return nil
}

// pyTruthy is Python's bool() of a JSON value.
func pyTruthy(v any) bool {
	switch x := v.(type) {
	case nil:
		return false
	case bool:
		return x
	case string:
		return x != ""
	case json.Number:
		f, err := x.Float64()
		return err != nil || f != 0
	case []any:
		return len(x) > 0
	case map[string]any:
		return len(x) > 0
	}
	return true
}

// pyInt is int(v) of a JSON value as a float for comparison with the clock;
// ok is false where Python raises ValueError, TypeError or OverflowError.
func pyInt(v any) (float64, bool) {
	switch x := v.(type) {
	case bool:
		if x {
			return 1, true
		}
		return 0, true
	case json.Number:
		s := x.String()
		if !strings.ContainsAny(s, ".eE") {
			f, err := strconv.ParseFloat(s, 64)
			return f, err == nil || errors.Is(err, strconv.ErrRange)
		}
		f, err := strconv.ParseFloat(s, 64)
		if err != nil || math.IsInf(f, 0) || math.IsNaN(f) {
			return 0, false
		}
		return math.Trunc(f), true
	case string:
		return pyIntString(x)
	}
	return 0, false
}

// pyIntString is int(str) for ASCII digits: surrounding whitespace, a sign,
// and single underscores between digits.
func pyIntString(s string) (float64, bool) {
	s = strings.Trim(s, " \t\n\r\v\f")
	if s == "" {
		return 0, false
	}
	sign := 1.0
	if s[0] == '+' || s[0] == '-' {
		if s[0] == '-' {
			sign = -1
		}
		s = s[1:]
	}
	if s == "" || s[0] == '_' || s[len(s)-1] == '_' || strings.Contains(s, "__") {
		return 0, false
	}
	digits := strings.ReplaceAll(s, "_", "")
	for i := range len(digits) {
		if digits[i] < '0' || digits[i] > '9' {
			return 0, false
		}
	}
	f, err := strconv.ParseFloat(digits, 64)
	if err != nil && !errors.Is(err, strconv.ErrRange) {
		return 0, false
	}
	return sign * f, true
}
