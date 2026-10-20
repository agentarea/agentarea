package secrets

import (
	"context"
	"errors"
	"testing"
)

// Made by Python's cryptography.fernet with the key below.
const (
	pythonKey   = "cw_0x689RpI-jtRR7oE8h_eQsKImvJapLeSbXpwF4e4="
	pythonToken = "gAAAAABq0TZfKpB71-g18B2GIwCwU5r4bq_VV74mHyYZImjpRPHE5IaZhwSTSUHRfwc-9tLksyMbOhY_yiNEVYJAGL-X5PDVk-uZmJxoaeBS-w7CXoY8yCQ="
)

func TestDecryptReadsATokenPythonMade(t *testing.T) {
	f, err := NewFernet(pythonKey)
	if err != nil {
		t.Fatalf("NewFernet: %v", err)
	}
	plaintext, err := f.Decrypt(pythonToken)
	if err != nil {
		t.Fatalf("Decrypt: %v", err)
	}
	if string(plaintext) != `{"bot_token": "1:abc"}` {
		t.Fatalf("plaintext = %q", plaintext)
	}
}

func TestDecryptRefusesATokenOfAnotherKey(t *testing.T) {
	f, err := NewFernet("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
	if err != nil {
		t.Fatalf("NewFernet: %v", err)
	}
	if _, err := f.Decrypt(pythonToken); err == nil {
		t.Fatal("decrypted a token signed with another key")
	}
}

func TestNewFernetRefusesAShortKey(t *testing.T) {
	if _, err := NewFernet("a2V5"); err == nil {
		t.Fatal("accepted a 3-byte key")
	}
}

type fakeReader map[string]string

func (f fakeReader) Get(_ context.Context, workspaceID, name string) (string, error) {
	value, ok := f[workspaceID+"/"+name]
	if !ok {
		return "", ErrNotFound
	}
	return value, nil
}

func TestCredentialsResolveValuesAndSecretReferences(t *testing.T) {
	r := fakeReader{
		"ws/channel_cred:feedy:k1": `{"token": "plain", "password": {"secret_name": "mailbox"}, "port": 993}`,
		"ws/mailbox":               "hunter2",
	}
	creds, err := Credentials(context.Background(), r, "ws", "feedy", "k1")
	if err != nil {
		t.Fatalf("Credentials: %v", err)
	}
	if creds["token"] != "plain" || creds["password"] != "hunter2" || creds["port"] != "993" {
		t.Fatalf("creds = %v", creds)
	}
}

func TestCredentialsOfASourceWithoutAny(t *testing.T) {
	creds, err := Credentials(context.Background(), fakeReader{}, "ws", "feedy", "k1")
	if err != nil || len(creds) != 0 {
		t.Fatalf("creds = %v, err = %v", creds, err)
	}
	creds, err = Credentials(context.Background(), fakeReader{}, "ws", "feedy", "")
	if err != nil || len(creds) != 0 {
		t.Fatalf("creds = %v, err = %v", creds, err)
	}
}

func TestCredentialsFailOnAMissingReferencedSecret(t *testing.T) {
	r := fakeReader{"ws/channel_cred:feedy:k1": `{"password": {"secret_name": "gone"}}`}
	if _, err := Credentials(context.Background(), r, "ws", "feedy", "k1"); !errors.Is(err, ErrNotFound) {
		t.Fatalf("err = %v, want ErrNotFound", err)
	}
}
