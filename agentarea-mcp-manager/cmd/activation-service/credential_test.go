package main

import "testing"

// The sandbox must never run untrusted commands as root: when the service is
// root it must resolve a valid non-root uid/gid or refuse. A root command could
// read PID1's environment (the activation HMAC secret) and forge tokens.
func TestResolveCommandCredential(t *testing.T) {
	// Non-root service: the command inherits the current non-root identity.
	if cred, err := resolveCommandCredential(1000, "", ""); cred != nil || err != nil {
		t.Fatalf("non-root euid should need no drop: cred=%v err=%v", cred, err)
	}

	// Root service, missing/zero uid or gid: MUST fail hard, never fall back to root.
	for _, tc := range []struct{ uid, gid string }{
		{"", ""}, {"10001", ""}, {"", "10001"},
		{"0", "0"}, {"0", "10001"}, {"10001", "0"},
		{"abc", "10001"}, {"10001", "xyz"},
	} {
		if _, err := resolveCommandCredential(0, tc.uid, tc.gid); err == nil {
			t.Fatalf("root with uid=%q gid=%q must be refused, got nil error", tc.uid, tc.gid)
		}
	}

	// Root service with a valid non-root uid/gid: drop to it.
	cred, err := resolveCommandCredential(0, "10001", "10001")
	if err != nil || cred == nil || cred.Uid != 10001 || cred.Gid != 10001 {
		t.Fatalf("root with valid uid/gid should drop: cred=%+v err=%v", cred, err)
	}
}
