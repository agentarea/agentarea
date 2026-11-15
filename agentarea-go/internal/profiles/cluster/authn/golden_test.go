package authn

import (
	"context"
	"testing"
	"time"

	port "github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
)

// Every Kratos and Hydra token below was minted by PyJWT and run through
// Python's _verify_token; Go must reach the same verdict with the same detail.
func TestVerifyMatchesPythonForKratosAndHydraTokens(t *testing.T) {
	g := loadGolden(t)
	hydraSrv, _ := jwksServer(t, func() []byte { return g.HydraJWKS })
	for _, sc := range g.Scenarios {
		t.Run(sc.Name, func(t *testing.T) {
			gate := newTestGate(t, Config{
				JWKSB64:       sc.JWKSB64,
				Issuer:        g.Issuer,
				Audience:      g.Audience,
				HydraURL:      hydraSrv.URL,
				HydraAudience: sc.HydraAudience,
			}, Deps{})
			for _, name := range sc.Tokens {
				want := g.Results[sc.Name][name]
				t.Run(name, func(t *testing.T) {
					p, err := gate.Verify(context.Background(), g.Tokens[name])
					switch want.Status {
					case 200:
						if err != nil {
							t.Fatalf("Python accepted, Go refused: %v", err)
						}
						if p.UserID != want.UserID || p.Email != want.Email || string(p.Credential.Kind) != want.Kind {
							t.Fatalf("principal %+v %+v, Python %+v", p, *p.Credential, want)
						}
					case 0:
						if err == nil {
							t.Fatalf("Python raised %s, Go accepted", want.Raised)
						}
						if r, ok := asRefusal(err); ok {
							t.Fatalf("Python raised %s (500), Go refused %d %q", want.Raised, r.Status, r.Detail)
						}
					default:
						r, ok := asRefusal(err)
						if !ok {
							t.Fatalf("Python refused %d %q, Go: %v", want.Status, want.Detail, err)
						}
						if r.Status != want.Status || r.Detail != want.Detail || r.WWWAuthenticate != want.WWWAuthenticate {
							t.Fatalf("Go %d %q %q\nPy %d %q %q", r.Status, r.Detail, r.WWWAuthenticate, want.Status, want.Detail, want.WWWAuthenticate)
						}
					}
				})
			}
		})
	}
}

func TestTurnTokenIssueIsPythonsByteForByte(t *testing.T) {
	g := loadGolden(t)
	at := time.Unix(g.Turn.IssuedAt, 0)
	tokens, err := NewTurnTokens(g.Turn.Secret, func() time.Time { return at })
	if err != nil {
		t.Fatal(err)
	}
	for _, c := range g.Turn.Issue {
		got, err := tokens.Issue(c.Claims.port(), time.Duration(c.TTL)*time.Second)
		if err != nil {
			t.Fatal(err)
		}
		if got != c.Token {
			t.Fatalf("Go minted\n%s\nPython minted\n%s", got, c.Token)
		}
	}
}

func TestTurnTokenDecodeMatchesPython(t *testing.T) {
	g := loadGolden(t)
	key := turnSigningKey(g.Turn.Secret)
	now := unixSeconds(time.Now())
	for name, token := range g.Turn.Cases {
		t.Run(name, func(t *testing.T) {
			if isTurnToken(token) != g.Turn.IsTurn[name] {
				t.Fatalf("isTurnToken = %v, Python %v", !g.Turn.IsTurn[name], g.Turn.IsTurn[name])
			}
			want := g.Turn.Decoded[name]
			got, ok, err := decodeTurn(token, key, now)
			switch {
			case want == nil:
				if ok || err != nil {
					t.Fatalf("Python refused, Go: ok=%v err=%v", ok, err)
				}
			case want.Raised != "":
				if err == nil {
					t.Fatalf("Python raised %s, Go ok=%v", want.Raised, ok)
				}
			default:
				if !ok || err != nil {
					t.Fatalf("Python accepted, Go: ok=%v err=%v", ok, err)
				}
				if got != want.port() {
					t.Fatalf("Go %+v\nPy %+v", got, want.port())
				}
			}
		})
	}
}

func TestPythonMintedAPIKeysHashAndShapeAsGoExpects(t *testing.T) {
	g := loadGolden(t)
	for _, k := range g.APIKeys {
		if port.HashAPIKey(k.Token) != k.Hash {
			t.Fatalf("hash of %s differs", k.Prefix)
		}
		if k.Token[:port.APIKeyPrefixLength] != k.Prefix || len(k.Token) != 47 {
			t.Fatalf("shape %q", k.Token)
		}
	}
	token, prefix, hash, err := port.NewAPIKey()
	if err != nil {
		t.Fatal(err)
	}
	if len(token) != 47 || token[:4] != port.APIKeyPrefix || prefix != token[:12] || hash != port.HashAPIKey(token) || len(hash) != 64 {
		t.Fatalf("Go key %q %q %q", token, prefix, hash)
	}
}
