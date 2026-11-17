package domain

import "testing"

func TestMaskInlineSecretsMatchesPython(t *testing.T) {
	for in, want := range map[string]string{
		"curl -H 'Authorization: Bearer abcdefgh123'": "curl -H 'Authorization: Bearer [redacted]'",
		"export API_KEY=sk-abcdefghijklmnopqrst":      "export API_KEY=[redacted]",
		`{"password": "hunter2", "user": "bob"}`:      `{"password": "[redacted]", "user": "bob"}`,
		"tool --token xyz --name a":                   "tool --token [redacted] --name a",
		"pre-token=keep":                              "pre-token=[redacted]",
		"git clone https://bob:s3cret@host/repo":      "git clone https://bob:[redacted]@host/repo",
		"curl -u bob:pw http://x":                     "curl -u bob:[redacted] http://x",
		"mysql -h db -psecret":                        "mysql -h db -p[redacted]",
		"sshpass -p hunter2 ssh x":                    "sshpass -p [redacted] ssh x",
		"key ghp_abcdefghijklmnopqrstuvwxyz":          "key [redacted]",
		"nothing to see here":                         "nothing to see here",
	} {
		if got := MaskInlineSecrets(in); got != want {
			t.Errorf("MaskInlineSecrets(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestToolResultKeepsStructuredContentWhole(t *testing.T) {
	vector := []any{map[string]any{"metric": map[string]any{"__name__": "ALERTS"}, "value": []any{float64(1793647243), "1"}}}
	got := SanitizeToolResultData(map[string]any{
		"tool_call_id": "tc-1", "result": "PRIVATE_STDOUT_CANARY",
		"structured_content": map[string]any{"data": vector, "exploreUrl": "https://grafana/explore"},
	})
	sc, _ := got["structured_content"].(map[string]any)
	if d, _ := sc["data"].([]any); len(d) != 1 || sc["exploreUrl"] != "https://grafana/explore" {
		t.Fatalf("structured_content = %#v", got["structured_content"])
	}
	if got["result"] == "PRIVATE_STDOUT_CANARY" {
		t.Fatal("the result outside structured_content must stay bounded")
	}
}

func TestToolResultStructuredContentMasksSecretKeys(t *testing.T) {
	got := SanitizeToolResultData(map[string]any{"tool_call_id": "tc-1",
		"structured_content": map[string]any{"api_key": "sk-live", "rows": float64(3)}})
	sc, _ := got["structured_content"].(map[string]any)
	if sc["api_key"] != "[redacted]" || sc["rows"] != float64(3) {
		t.Fatalf("structured_content = %#v", sc)
	}
}
