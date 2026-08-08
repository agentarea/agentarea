package execsupervisor

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"strings"
	"testing"
)

func testAttestation(content []byte) Attestation {
	digest := sha256.Sum256(content)
	return Attestation{
		Path: "/usr/local/bin/agentarea-exec-supervisor", SHA256: hex.EncodeToString(digest[:]),
		ProtocolVersion: ProtocolVersion, CommandUID: 10001, CommandGID: 10001,
	}
}

func TestInvocationQuotesTheCompleteUntrustedCommand(t *testing.T) {
	attestation := testAttestation([]byte("supervisor"))
	statusPath, err := StatusPath("execution-1")
	if err != nil {
		t.Fatal(err)
	}
	invocation, err := Invocation(attestation, statusPath, 30, 4096, "printf '%s' \"$HOME\"; touch /tmp/value")
	if err != nil {
		t.Fatal(err)
	}
	for _, expected := range []string{
		"'/usr/local/bin/agentarea-exec-supervisor'", "'--status'", "'/run/agentarea-executions/execution-1.json'",
		"'/bin/sh'", "'-c'", `'printf '"'"'%s'"'"' "$HOME"; touch /tmp/value'`,
	} {
		if !strings.Contains(invocation, expected) {
			t.Fatalf("Invocation() = %q, missing %q", invocation, expected)
		}
	}
}

func TestVerifyBinaryRejectsPrefixAndDigestDrift(t *testing.T) {
	body := []byte("attested-binary")
	attestation := testAttestation(body)
	if err := VerifyBinary(bytes.NewReader(body), int64(len(body)), attestation); err != nil {
		t.Fatal(err)
	}
	if err := VerifyBinary(bytes.NewReader(append(append([]byte(nil), body...), 'x')), int64(len(body)), attestation); err == nil {
		t.Fatal("binary with an attested prefix and trailing bytes was accepted")
	}
	changed := append([]byte(nil), body...)
	changed[0] = 'x'
	if err := VerifyBinary(bytes.NewReader(changed), int64(len(changed)), attestation); err == nil {
		t.Fatal("binary with a different digest was accepted")
	}
}

func TestDecodeStatusRequiresAuthenticatedQuiescence(t *testing.T) {
	attestation := testAttestation([]byte("supervisor"))
	valid := []byte(`{"protocol_version":1,"supervisor_sha256":"` + attestation.SHA256 + `","quiescent":true,"child_exit_code":7,"timed_out":false}`)
	status, err := DecodeStatus(valid, attestation)
	if err != nil || status.ChildExitCode != 7 {
		t.Fatalf("DecodeStatus() = %+v, %v", status, err)
	}
	for name, payload := range map[string][]byte{
		"not quiescent": []byte(`{"protocol_version":1,"supervisor_sha256":"` + attestation.SHA256 + `","quiescent":false,"child_exit_code":0,"timed_out":false}`),
		"wrong digest":  []byte(`{"protocol_version":1,"supervisor_sha256":"` + strings.Repeat("b", 64) + `","quiescent":true,"child_exit_code":0,"timed_out":false}`),
		"unknown field": []byte(`{"protocol_version":1,"supervisor_sha256":"` + attestation.SHA256 + `","quiescent":true,"child_exit_code":0,"timed_out":false,"extra":true}`),
		"bad timeout":   []byte(`{"protocol_version":1,"supervisor_sha256":"` + attestation.SHA256 + `","quiescent":true,"child_exit_code":0,"timed_out":true}`),
	} {
		t.Run(name, func(t *testing.T) {
			if _, err := DecodeStatus(payload, attestation); err == nil {
				t.Fatal("invalid supervisor status was accepted")
			}
		})
	}
}

func TestStatusPathRejectsTraversalAndPunctuation(t *testing.T) {
	for _, executionID := range []string{"", "../escape", ".", "value.json", "a/b", strings.Repeat("a", 129)} {
		if _, err := StatusPath(executionID); err == nil {
			t.Fatalf("StatusPath(%q) unexpectedly succeeded", executionID)
		}
	}
}
