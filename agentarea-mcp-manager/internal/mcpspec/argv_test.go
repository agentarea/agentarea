package mcpspec

import "testing"

func TestDockerArgvAcceptsStringCommandList(t *testing.T) {
	got := DockerArgv(map[string]any{
		"image":   "repo@sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
		"command": []string{"serve", "--port", "8080"},
	})
	want := []string{"serve", "--port", "8080"}
	if len(got) != len(want) {
		t.Fatalf("DockerArgv() = %v, want %v", got, want)
	}
	for index := range want {
		if got[index] != want[index] {
			t.Fatalf("DockerArgv()[%d] = %q, want %q", index, got[index], want[index])
		}
	}
}
