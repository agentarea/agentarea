package authn

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"errors"
	"fmt"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	port "github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
)

// The turn token (auth/turn_token.py, ADR-0051).
const (
	turnTokenKID   = "agentarea-turn"
	turnIssuer     = "agentarea"
	turnDerivation = "agentarea/turn-token/v1"
	turnAudPrefix  = "task:"
	turnClientPref = "client:"
)

// turnHeaderJSON is PyJWT's header for the turn token, keys sorted.
const turnHeaderJSON = `{"alg":"HS256","kid":"agentarea-turn","typ":"JWT"}`

// turnSigningKey is HMAC-SHA256(gateway secret, derivation label).
func turnSigningKey(secret string) []byte {
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write([]byte(turnDerivation))
	return mac.Sum(nil)
}

// TurnTokens issues and decodes turn tokens with Python's key and encoding;
// for the same claims and second Issue returns Python's token byte for byte.
type TurnTokens struct {
	key []byte
	now func() time.Time
}

var _ port.TurnTokens = (*TurnTokens)(nil)

// NewTurnTokens keys tokens with the MCP gateway secret.
func NewTurnTokens(secret string, now func() time.Time) (*TurnTokens, error) {
	if secret == "" {
		return nil, errors.New("AGENTAREA_MCP_GATEWAY_SECRET is required for container-backed MCP")
	}
	if utf8.RuneCountInString(secret) < 32 {
		return nil, errors.New("AGENTAREA_MCP_GATEWAY_SECRET must contain at least 32 bytes")
	}
	if now == nil {
		now = time.Now
	}
	return &TurnTokens{key: turnSigningKey(secret), now: now}, nil
}

// Issue is issue_turn_token; ttl is whole seconds.
func (t *TurnTokens) Issue(c port.TurnClaims, ttl time.Duration) (string, error) {
	if c.ActorType != port.SubjectUser && c.ActorType != port.SubjectAgent {
		return "", fmt.Errorf("turn actor must be user or agent, got %q", c.ActorType)
	}
	issuedAt := t.now().Unix()
	ttlSeconds := int64(ttl / time.Second)
	var b strings.Builder
	b.WriteString(`{"iss":`)
	b.WriteString(pyJSONString(turnIssuer))
	b.WriteString(`,"sub":`)
	b.WriteString(pyJSONString(string(c.ActorType) + ":" + c.ActorID))
	b.WriteString(`,"act":{"sub":`)
	b.WriteString(pyJSONString(turnClientPref + c.ClientID))
	b.WriteString(`},"aud":`)
	b.WriteString(pyJSONString(turnAudPrefix + c.TaskID))
	b.WriteString(`,"iat":`)
	b.WriteString(strconv.FormatInt(issuedAt, 10))
	b.WriteString(`,"exp":`)
	b.WriteString(strconv.FormatInt(issuedAt+ttlSeconds, 10))
	b.WriteString(`,"jti":`)
	b.WriteString(pyJSONString(c.TurnID))
	b.WriteString(`,"workspace_id":`)
	b.WriteString(pyJSONString(c.WorkspaceID))
	b.WriteString(`,"obo":`)
	b.WriteString(pyJSONString(c.OnBehalfOf))
	b.WriteString(`}`)
	enc := base64.RawURLEncoding
	signingInput := enc.EncodeToString([]byte(turnHeaderJSON)) + "." + enc.EncodeToString([]byte(b.String()))
	mac := hmac.New(sha256.New, t.key)
	mac.Write([]byte(signingInput))
	return signingInput + "." + enc.EncodeToString(mac.Sum(nil)), nil
}

// Decode is decode_turn_token.
func (t *TurnTokens) Decode(token string) (port.TurnClaims, bool) {
	claims, ok, err := decodeTurn(token, t.key, unixSeconds(t.now()))
	return claims, ok && err == nil
}

// isTurnToken is is_turn_token: the unverified header names the turn key.
func isTurnToken(token string) bool {
	header, err := unverifiedHeader(token)
	if err != nil {
		return false
	}
	kid, _ := header["kid"].(string)
	return kid == turnTokenKID
}

// errNoTurnKey is Python's RuntimeError when no gateway secret is set.
var errNoTurnKey = errors.New("AGENTAREA_MCP_GATEWAY_SECRET is required for container-backed MCP")

// decodeTurn is decode_turn_token: claims and true for a valid token of this
// platform; err where Python raises past the decoder (no key; a signed token
// missing workspace_id or obo, or with a non-object act).
func decodeTurn(token string, key []byte, now float64) (port.TurnClaims, bool, error) {
	unverified, err := decode(token, decodeOptions{})
	if err != nil {
		return port.TurnClaims{}, false, nil
	}
	audience, isStr := unverified["aud"].(string)
	if !isStr || !strings.HasPrefix(audience, turnAudPrefix) {
		return port.TurnClaims{}, false, nil
	}
	if key == nil {
		return port.TurnClaims{}, false, errNoTurnKey
	}
	issuer := turnIssuer
	payload, err := decode(token, decodeOptions{
		verifySignature: true,
		key:             hmacKey(key),
		algorithms:      []string{"HS256"},
		audience:        &audience,
		issuer:          &issuer,
		require:         []string{"sub", "act", "aud", "exp", "jti"},
		now:             now,
	})
	if err != nil {
		if je, ok := asJWTError(err); ok && je.invalidToken() {
			return port.TurnClaims{}, false, nil
		}
		return port.TurnClaims{}, false, err
	}
	actorType, actorID, _ := strings.Cut(payload["sub"].(string), ":")
	var client string
	switch act := payload["act"].(type) {
	case map[string]any:
		if sub, present := act["sub"]; present {
			client = pyStr(sub)
		}
	default:
		if pyTruthy(act) {
			return port.TurnClaims{}, false, errors.New("'act' claim is not an object")
		}
	}
	if (actorType != "user" && actorType != "agent") || actorID == "" || !strings.HasPrefix(client, turnClientPref) {
		return port.TurnClaims{}, false, nil
	}
	workspaceID, hasWS := payload["workspace_id"]
	obo, hasOBO := payload["obo"]
	if !hasWS || !hasOBO {
		return port.TurnClaims{}, false, errors.New("turn token lacks workspace_id or obo")
	}
	return port.TurnClaims{
		TurnID:      payload["jti"].(string),
		TaskID:      strings.TrimPrefix(audience, turnAudPrefix),
		WorkspaceID: pyStr(workspaceID),
		ClientID:    strings.TrimPrefix(client, turnClientPref),
		ActorType:   port.SubjectKind(actorType),
		ActorID:     actorID,
		OnBehalfOf:  pyStr(obo),
	}, true, nil
}

// pyStr is str() of a JSON value.
func pyStr(v any) string {
	if v == nil {
		return "None"
	}
	if s, ok := v.(string); ok {
		return s
	}
	return pyRepr(v)
}

// pyJSONString is json.dumps of a string with ensure_ascii, as PyJWT encodes claims.
func pyJSONString(s string) string {
	var b strings.Builder
	b.WriteByte('"')
	for _, r := range s {
		switch r {
		case '"':
			b.WriteString(`\"`)
		case '\\':
			b.WriteString(`\\`)
		case '\n':
			b.WriteString(`\n`)
		case '\r':
			b.WriteString(`\r`)
		case '\t':
			b.WriteString(`\t`)
		case '\b':
			b.WriteString(`\b`)
		case '\f':
			b.WriteString(`\f`)
		default:
			switch {
			case r < 0x20 || (r > 0x7f && r < 0x10000):
				fmt.Fprintf(&b, `\u%04x`, r)
			case r >= 0x10000:
				r -= 0x10000
				fmt.Fprintf(&b, `\u%04x\u%04x`, 0xd800+(r>>10), 0xdc00+(r&0x3ff))
			default:
				b.WriteRune(r)
			}
		}
	}
	b.WriteByte('"')
	return b.String()
}
