package secrets

import (
	"bytes"
	"encoding/hex"
	"encoding/json"
	"os"
	"strings"
	"testing"
	"time"
)

type pythonFernet struct {
	Key    string `json:"key"`
	Tokens []struct {
		Plaintext string `json:"plaintext"`
		Token     string `json:"token"`
	} `json:"tokens"`
}

// loadPythonTokens reads ciphertexts DatabaseSecretManager._encrypt wrote,
// recorded once in testdata.
func loadPythonTokens(t *testing.T) pythonFernet {
	t.Helper()
	raw, err := os.ReadFile("testdata/python_fernet.json")
	if err != nil {
		t.Fatal(err)
	}
	var out pythonFernet
	if err := json.Unmarshal(raw, &out); err != nil {
		t.Fatal(err)
	}
	return out
}

const pyKey = "uRJt6kJ2k7R0nQmY1m0y9y8YJX4m0p7lq3hE5G2bq1c="

func TestDecryptReadsTokensPythonMade(t *testing.T) {
	py := loadPythonTokens(t)
	f, err := NewFernet(py.Key)
	if err != nil {
		t.Fatal(err)
	}
	for _, c := range py.Tokens {
		got, err := f.Decrypt(c.Token)
		if err != nil {
			t.Fatalf("Decrypt(%q): %v", c.Plaintext, err)
		}
		if string(got) != c.Plaintext {
			t.Errorf("got %q want %q", got, c.Plaintext)
		}
	}
}

// TestNewFernetAcceptsWhatPythonAccepts replays the verdicts
// cryptography.fernet.Fernet(key) gave on CPython 3.14, recorded once: a key
// the deployment runs with today must keep opening its rows.
func TestNewFernetAcceptsWhatPythonAccepts(t *testing.T) {
	raw, err := os.ReadFile("testdata/python_fernet_keys.json")
	if err != nil {
		t.Fatal(err)
	}
	var fixture struct {
		Cases []struct {
			Name   string  `json:"name"`
			Key    string  `json:"key"`
			RawHex *string `json:"raw_hex"`
		} `json:"cases"`
	}
	if err := json.Unmarshal(raw, &fixture); err != nil {
		t.Fatal(err)
	}
	for _, c := range fixture.Cases {
		f, err := NewFernet(c.Key)
		switch {
		case c.RawHex == nil && err == nil:
			t.Errorf("%s: Python refuses %q, Go accepted it", c.Name, c.Key)
		case c.RawHex != nil && err != nil:
			t.Errorf("%s: Python accepts %q, Go: %v", c.Name, c.Key, err)
		case c.RawHex != nil:
			if got := hex.EncodeToString(append(append([]byte{}, f.signing...), f.encryption...)); got != *c.RawHex {
				t.Errorf("%s: key %q read as %s, Python %s", c.Name, c.Key, got, *c.RawHex)
			}
		}
	}
}

func TestEncryptRoundTripsAndHasFernetShape(t *testing.T) {
	f, _ := NewFernet(pyKey)
	for _, n := range []int{0, 1, 15, 16, 17, 100} {
		plain := bytes.Repeat([]byte("a"), n)
		token, err := f.Encrypt(plain)
		if err != nil {
			t.Fatal(err)
		}
		if !strings.HasPrefix(token, "gAAAAA") {
			t.Errorf("token %q lacks the Fernet version/timestamp prefix", token)
		}
		got, err := f.Decrypt(token)
		if err != nil || !bytes.Equal(got, plain) {
			t.Errorf("n=%d round trip: %q %v", n, got, err)
		}
	}
}

func TestEncryptIsDeterministicGivenIVAndTime(t *testing.T) {
	f, _ := NewFernet(pyKey)
	iv := bytes.Repeat([]byte{7}, 16)
	at := time.Unix(1700000000, 0)
	a, _ := f.encryptWithIV([]byte("v"), iv, at)
	b, _ := f.encryptWithIV([]byte("v"), iv, at)
	if a != b {
		t.Error("same inputs gave different tokens")
	}
	c, _ := f.Encrypt([]byte("v"))
	d, _ := f.Encrypt([]byte("v"))
	if c == d {
		t.Error("two encryptions share an IV")
	}
}

func TestDecryptRefusesTampering(t *testing.T) {
	f, _ := NewFernet(pyKey)
	token := loadPythonTokens(t).Tokens[0].Token
	other, _ := NewFernet("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
	bad := []string{
		token[:len(token)-4] + "AAAA",
		"",
		"not base64 !!",
		token[:20],
		"Z" + token[1:],
	}
	for _, b := range bad {
		if _, err := f.Decrypt(b); err == nil {
			t.Errorf("accepted %q", b)
		}
	}
	if _, err := other.Decrypt(token); err == nil {
		t.Error("another key opened the token")
	}
}

func TestDecryptRefusesBadPaddingAfterValidMAC(t *testing.T) {
	f, _ := NewFernet(pyKey)
	// A token with a valid signature over a ciphertext that does not unpad:
	// sign garbage blocks with the real key.
	iv := make([]byte, 16)
	token, _ := f.encryptWithIV([]byte("x"), iv, time.Unix(0, 0))
	raw, _ := decodeToken(token)
	raw[len(raw)-fernetMAC-1] ^= 0xff
	resigned := resign(f, raw)
	if _, err := f.Decrypt(resigned); err == nil {
		t.Error("accepted a corrupted padding")
	}
}

func TestNewFernetKeyChecks(t *testing.T) {
	for _, k := range []string{"", "short", "!!!!", "AAAA"} {
		_, err := NewFernet(k)
		if err == nil {
			t.Errorf("accepted key %q", k)
		}
		if err != nil && k != "" && strings.Contains(err.Error(), k) {
			t.Errorf("error repeats the key: %v", err)
		}
	}
}
