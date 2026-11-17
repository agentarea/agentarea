package authn

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rsa"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"math/big"
	"strings"
)

// curveName is the cryptography name PyJWT puts in its curve message.
func curveName(pub *ecdsa.PublicKey) string {
	switch pub.Curve {
	case elliptic.P256():
		return "secp256r1"
	case elliptic.P384():
		return "secp384r1"
	case elliptic.P521():
		return "secp521r1"
	}
	return pub.Curve.Params().Name
}

// otherCurveKey is an EC key on a curve Go does not implement (secp256k1):
// PyJWT accepts it as a key, and refuses it for ES256 by its curve.
type otherCurveKey struct{ name string }

func (k otherCurveKey) verify(alg string, _, _ []byte) (bool, error) {
	if alg != "ES256" {
		return false, errors.New("EC key used for " + alg)
	}
	return false, jwtErr(clsInvalidKey, "The key's curve '"+k.name+"' does not match the expected curve 'secp256r1' for this algorithm")
}

// otherKey is a usable JWK of a kind no AgentArea path verifies with
// (oct, OKP); PyJWT's prepare_key fails on it outside InvalidTokenError.
type otherKey struct{ kty string }

func (k otherKey) verify(alg string, _, _ []byte) (bool, error) {
	return false, errors.New(k.kty + " key used for " + alg)
}

// pyB64URL is jwt.utils.base64url_decode over a JSON value: a TypeError for
// anything but a string, then urlsafe_b64decode, which drops characters
// outside the alphabet.
func pyB64URL(v any) ([]byte, error) {
	s, ok := v.(string)
	if !ok {
		return nil, errors.New("Expected a string or bytes value") //nolint:staticcheck // PyJWT's message
	}
	if rem := len(s) % 4; rem > 0 {
		s += strings.Repeat("=", 4-rem)
	}
	var b strings.Builder
	for i := range len(s) {
		c := s[i]
		switch {
		case c == '-':
			b.WriteByte('+')
		case c == '_':
			b.WriteByte('/')
		case (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '+' || c == '/':
			b.WriteByte(c)
		}
	}
	out, err := base64.RawStdEncoding.DecodeString(b.String())
	if err != nil {
		return nil, errors.New("Incorrect padding") //nolint:staticcheck // binascii's message
	}
	return out, nil
}

// pyRepr is str() of a JSON value as Python prints it in a message.
func pyRepr(v any) string {
	switch x := v.(type) {
	case nil:
		return "None"
	case bool:
		if x {
			return "True"
		}
		return "False"
	case string:
		return x
	case json.Number:
		return x.String()
	}
	b, _ := json.Marshal(v)
	return string(b)
}

var errNotEC = jwtErr(clsInvalidKey, "Not an Elliptic curve key")

// ecFromJWK is ECAlgorithm.from_jwk; the public half of a private key.
func ecFromJWK(obj map[string]any) (verifyKey, error) {
	if obj["kty"] != "EC" {
		return nil, errNotEC
	}
	rawX, hasX := obj["x"]
	rawY, hasY := obj["y"]
	if !hasX || !hasY {
		return nil, errNotEC
	}
	x, err := pyB64URL(rawX)
	if err != nil {
		return nil, err
	}
	y, err := pyB64URL(rawY)
	if err != nil {
		return nil, err
	}
	crv := obj["crv"]
	var curve elliptic.Curve
	var size int
	switch crv {
	case "P-256":
		curve, size = elliptic.P256(), 32
	case "P-384":
		curve, size = elliptic.P384(), 48
	case "P-521":
		curve, size = elliptic.P521(), 66
	case "secp256k1":
		size = 32
	default:
		return nil, jwtErr(clsInvalidKey, "Invalid curve: "+pyRepr(crv))
	}
	if len(x) != size || len(y) != size {
		return nil, jwtErr(clsInvalidKey, fmt.Sprintf("Coords should be %d bytes for curve %s", size, crv))
	}
	if rawD, hasD := obj["d"]; hasD {
		d, err := pyB64URL(rawD)
		if err != nil {
			return nil, err
		}
		if len(d) != len(x) {
			return nil, jwtErr(clsInvalidKey, fmt.Sprintf("('D should be {} bytes for curve {}', %d, '%s')", len(x), crv))
		}
	}
	if curve == nil {
		return otherCurveKey{name: "secp256k1"}, nil
	}
	point := append([]byte{4}, append(x, y...)...)
	pub, err := ecdsa.ParseUncompressedPublicKey(curve, point)
	if err != nil {
		return nil, errors.New("Invalid EC key.") //nolint:staticcheck // cryptography's message
	}
	return ecKey{pub: pub}, nil
}

// rsaFromJWK is RSAAlgorithm.from_jwk's public half.
func rsaFromJWK(obj map[string]any) (verifyKey, error) {
	if obj["kty"] != "RSA" {
		return nil, jwtErr(clsInvalidKey, "Not an RSA key")
	}
	rawN, hasN := obj["n"]
	rawE, hasE := obj["e"]
	if !hasN || !hasE {
		return nil, jwtErr(clsInvalidKey, "Not a public or private key")
	}
	n, err := pyB64URL(rawN)
	if err != nil {
		return nil, err
	}
	e, err := pyB64URL(rawE)
	if err != nil {
		return nil, err
	}
	exp := new(big.Int).SetBytes(e)
	if !exp.IsInt64() || exp.Int64() < 3 || exp.Int64() > 1<<31-1 || exp.Bit(0) == 0 {
		return nil, errors.New("invalid RSA public exponent")
	}
	mod := new(big.Int).SetBytes(n)
	if mod.Sign() == 0 || mod.Bit(0) == 0 {
		return nil, errors.New("invalid RSA modulus")
	}
	return rsaKey{pub: &rsa.PublicKey{N: mod, E: int(exp.Int64())}}, nil
}

// jwk is one key of a JWK set as PyJWK reads it.
type jwk struct {
	kid string
	use any
	key verifyKey
}

// jwkFamily is the key type get_default_algorithms() (with cryptography)
// builds for alg; ok is false for an algorithm PyJWT does not know.
func jwkFamily(alg string) (string, bool) {
	switch alg {
	case "HS256", "HS384", "HS512":
		return "oct", true
	case "RS256", "RS384", "RS512", "PS256", "PS384", "PS512":
		return "RSA", true
	case "ES256", "ES256K", "ES384", "ES521", "ES512":
		return "EC", true
	case "EdDSA":
		return "OKP", true
	}
	return "", false
}

// parseJWK is PyJWK(data): the key, or an error when PyJWKSet skips it.
func parseJWK(obj map[string]any) (jwk, error) {
	kty, _ := obj["kty"].(string)
	if !pyTruthy(obj["kty"]) {
		return jwk{}, errors.New("kty is not found")
	}
	alg, _ := obj["alg"].(string)
	if !pyTruthy(obj["alg"]) {
		crv := obj["crv"]
		switch kty {
		case "EC":
			switch {
			case crv == "P-256" || !pyTruthy(crv):
				alg = "ES256"
			case crv == "P-384":
				alg = "ES384"
			case crv == "P-521":
				alg = "ES512"
			case crv == "secp256k1":
				alg = "ES256K"
			default:
				return jwk{}, errors.New("unsupported crv")
			}
		case "RSA":
			alg = "RS256"
		case "oct":
			alg = "HS256"
		case "OKP":
			if crv != "Ed25519" {
				return jwk{}, errors.New("unsupported crv")
			}
			alg = "EdDSA"
		default:
			return jwk{}, errors.New("unsupported kty")
		}
	}
	family, ok := jwkFamily(alg)
	if !ok {
		return jwk{}, errors.New("unable to find an algorithm for key")
	}
	var key verifyKey
	var err error
	switch family {
	case "RSA":
		key, err = rsaFromJWK(obj)
	case "EC":
		key, err = ecFromJWK(obj)
	case "oct":
		if kty != "oct" {
			return jwk{}, errors.New("not an HMAC key")
		}
		if _, err = pyB64URL(obj["k"]); err == nil {
			key = otherKey{kty: kty}
		}
	case "OKP":
		if kty != "OKP" || (obj["crv"] != "Ed25519" && obj["crv"] != "Ed448") {
			return jwk{}, errors.New("not an OKP key")
		}
		if _, err = pyB64URL(obj["x"]); err == nil {
			key = otherKey{kty: kty}
		}
	}
	if err != nil {
		return jwk{}, err
	}
	kid, _ := obj["kid"].(string)
	return jwk{kid: kid, use: obj["use"], key: key}, nil
}

// signingKeys is PyJWKSet.from_dict then PyJWKClient's signing-key filter.
func signingKeys(data any) ([]jwk, error) {
	obj, ok := data.(map[string]any)
	if !ok {
		return nil, errors.New("The JWKS endpoint did not return a JSON object") //nolint:staticcheck // PyJWT's message
	}
	raw, present := obj["keys"]
	if !present || !pyTruthy(raw) {
		return nil, errors.New("The JWK Set did not contain any keys") //nolint:staticcheck // PyJWT's message
	}
	list, ok := raw.([]any)
	if !ok {
		return nil, errors.New("Invalid JWK Set value") //nolint:staticcheck // PyJWT's message
	}
	var usable []jwk
	for _, item := range list {
		m, ok := item.(map[string]any)
		if !ok {
			continue
		}
		if k, err := parseJWK(m); err == nil {
			usable = append(usable, k)
		}
	}
	if len(usable) == 0 {
		return nil, errors.New("The JWK Set did not contain any usable keys") //nolint:staticcheck // PyJWT's message
	}
	var signing []jwk
	for _, k := range usable {
		if (k.use == nil || k.use == "sig") && k.kid != "" {
			signing = append(signing, k)
		}
	}
	if len(signing) == 0 {
		return nil, errors.New("The JWKS endpoint did not contain any signing keys") //nolint:staticcheck // PyJWT's message
	}
	return signing, nil
}
