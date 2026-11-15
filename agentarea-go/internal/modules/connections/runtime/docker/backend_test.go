package docker

import (
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/runtime/workload"
)

func spec(id string) workload.Spec {
	return workload.Spec{Name: id, ServiceName: id, InstanceID: id, WorkspaceID: "ws-1", Image: "vendor/mcp:1.0", Port: 8080}
}

// freshHost answers like a host with no container under the name, room to
// spare, and a run that succeeds.
func freshHost(t *testing.T, extra func(args []string) (reply, bool)) *fakeRunner {
	t.Helper()
	return &fakeRunner{handle: func(args []string) reply {
		if extra != nil {
			if r, ok := extra(args); ok {
				return r
			}
		}
		switch args[0] {
		case "container":
			return absent()
		case "ps":
			return reply{}
		case "run":
			return reply{stdout: "Unable to find image\nabc123\n"}
		case "info":
			return reply{stdout: `{"runc":{},"runsc":{}}`}
		}
		return reply{err: errors.New("unexpected " + strings.Join(args, " "))}
	}}
}

func TestCreateAcknowledgesAStartingWorkload(t *testing.T) {
	r := freshHost(t, nil)
	b, _ := newTestBackend(t, testConfig(), r)
	st, err := b.Create(context.Background(), spec("i-1"))
	if err != nil {
		t.Fatal(err)
	}
	if st.Status != workload.StatusStarting || st.ID != "abc123" || st.Name != "mcp-i-1" {
		t.Fatalf("status = %+v", st)
	}
	if !r.called("run -d --name mcp-i-1") {
		t.Fatalf("no run issued:\n%s", r.joined())
	}
}

func TestCreateRefusesAFlagShapedImageBeforeTheRuntime(t *testing.T) {
	r := freshHost(t, nil)
	b, _ := newTestBackend(t, testConfig(), r)
	s := spec("i-1")
	s.Image = "--privileged"
	if _, err := b.Create(context.Background(), s); err == nil {
		t.Fatal("a flag-shaped image was accepted")
	}
	if len(r.calls) != 0 {
		t.Fatalf("the runtime was invoked:\n%s", r.joined())
	}
}

func TestCreateRefusesACeilingAboveTheHostMaximum(t *testing.T) {
	r := freshHost(t, nil)
	b, _ := newTestBackend(t, testConfig(), r)
	for name, lim := range map[string]workload.ResourceList{
		"memory": {Memory: "100g"},
		"cpu":    {CPU: "64"},
		"junk":   {CPU: "all-of-it"},
	} {
		s := spec("greedy-" + name)
		s.Resources.Limits = lim
		if _, err := b.Create(context.Background(), s); err == nil {
			t.Fatalf("%s: the request was admitted", name)
		}
	}
	if r.called("run") {
		t.Fatalf("a refused request reached the runtime:\n%s", r.joined())
	}
	s := spec("modest")
	s.Resources.Limits = workload.ResourceList{Memory: "256m", CPU: "0.5"}
	if _, err := b.Create(context.Background(), s); err != nil {
		t.Fatalf("a smaller ceiling was refused: %v", err)
	}
	if !strings.Contains(r.joined(), "--memory 256m --cpus 0.5") {
		t.Fatalf("run did not carry the requested ceiling:\n%s", r.joined())
	}
}

func TestCreateRefusesAtTheContainerLimitCountingOnlyLiveWorkloads(t *testing.T) {
	cfg := testConfig()
	cfg.MaxContainers = 2
	states := "running\nexited\ndead\ncreated\n"
	r := freshHost(t, func(args []string) (reply, bool) {
		if args[0] == "ps" {
			return reply{stdout: states}, true
		}
		return reply{}, false
	})
	b, _ := newTestBackend(t, cfg, r)
	if _, err := b.Create(context.Background(), spec("i-1")); err == nil || !strings.Contains(err.Error(), "maximum container limit") {
		t.Fatalf("Create() error = %v, want the limit", err)
	}
	states = "running\nexited\nexited\nstopped\n"
	if _, err := b.Create(context.Background(), spec("i-1")); err != nil {
		t.Fatalf("dead containers held slots: %v", err)
	}
}

func TestCreateFailsClosedWithoutTheIsolationRuntime(t *testing.T) {
	cfg := testConfig()
	cfg.IsolationTier = workload.IsolationUntrusted
	r := freshHost(t, func(args []string) (reply, bool) {
		if args[0] == "info" {
			return reply{stdout: `{"runc":{}}`}, true
		}
		return reply{}, false
	})
	b, _ := newTestBackend(t, cfg, r)
	_, err := b.Create(context.Background(), spec("i-1"))
	var unavailable *RuntimeUnavailableError
	if !errors.As(err, &unavailable) || unavailable.Runtime != "runsc" {
		t.Fatalf("Create() error = %v, want the missing runtime named", err)
	}
	if r.called("run") {
		t.Fatal("the workload started without its isolation")
	}
}

func TestCreateClassifiesARuntimeRefusalWithoutEchoingIt(t *testing.T) {
	r := freshHost(t, func(args []string) (reply, bool) {
		if args[0] == "run" {
			return reply{stderr: "pull access denied for reg.example.com/team/app", err: exitErr()}, true
		}
		return reply{}, false
	})
	b, logged := newTestBackend(t, testConfig(), r)
	_, err := b.Create(context.Background(), spec("i-1"))
	if err == nil || !strings.Contains(err.Error(), "no credentials") || strings.Contains(err.Error(), "reg.example.com") {
		t.Fatalf("Create() error = %v", err)
	}
	if !strings.Contains(logged.String(), "reg.example.com") {
		t.Fatal("the runtime's own text did not reach the log")
	}
}

func inspecting(t *testing.T, st containerState) func(args []string) reply {
	return func(args []string) reply {
		switch args[0] {
		case "container":
			return reply{stdout: st.json(t)}
		case "rm":
			return reply{}
		case "logs":
			return reply{stdout: "\x1b[31mstarting with token=sk-live-6f2b91c4aa77 on port 8123\x1b[0m"}
		}
		return reply{err: errors.New("unexpected " + strings.Join(args, " "))}
	}
}

func owned(id string) map[string]string {
	return map[string]string{ownerLabel: id, instanceLabel: id}
}

func TestStaleNamesakeIsRemoved(t *testing.T) {
	r := &fakeRunner{handle: inspecting(t, containerState{status: "exited", labels: owned("i-1")})}
	b, _ := newTestBackend(t, testConfig(), r)
	if err := b.clearContainerName(context.Background(), "mcp-i-1", "i-1"); err != nil {
		t.Fatal(err)
	}
	if !r.called("rm -f mcp-i-1") {
		t.Fatalf("the corpse stayed:\n%s", r.joined())
	}
}

func TestRunningNamesakeIsReportedNotKilled(t *testing.T) {
	r := &fakeRunner{handle: inspecting(t, containerState{status: "running", labels: owned("i-1")})}
	b, _ := newTestBackend(t, testConfig(), r)
	if err := b.clearContainerName(context.Background(), "mcp-i-1", "i-1"); err == nil {
		t.Fatal("a running namesake was accepted")
	}
	if r.called("rm") {
		t.Fatal("a running container was removed")
	}
}

func TestACorpseOwnedBySomethingElseIsNotRemoved(t *testing.T) {
	for name, labels := range map[string]map[string]string{
		"foreign":    {ownerLabel: "someone-else"},
		"unlabelled": nil,
	} {
		r := &fakeRunner{handle: inspecting(t, containerState{status: "exited", labels: labels})}
		b, _ := newTestBackend(t, testConfig(), r)
		if err := b.clearContainerName(context.Background(), "mcp-i-1", "i-1"); err == nil {
			t.Fatalf("%s: the container was claimed", name)
		}
		if r.called("rm") {
			t.Fatalf("%s: the container was removed", name)
		}
	}
}

func TestAbsentNameNeedsNoWork(t *testing.T) {
	r := &fakeRunner{handle: func([]string) reply { return absent() }}
	b, _ := newTestBackend(t, testConfig(), r)
	if err := b.clearContainerName(context.Background(), "mcp-i-1", "i-1"); err != nil {
		t.Fatal(err)
	}
	if r.called("rm") {
		t.Fatal("removal ran for a free name")
	}
}

func TestInspectFailureIsNotAbsence(t *testing.T) {
	r := &fakeRunner{handle: func([]string) reply {
		return reply{stderr: "Cannot connect to the Docker daemon", err: exitErr()}
	}}
	b, _ := newTestBackend(t, testConfig(), r)
	if _, err := b.Status(context.Background(), "i-1"); err == nil || errors.Is(err, workload.ErrNotFound) {
		t.Fatalf("Status() error = %v, want a runtime failure", err)
	}
}

func TestDeletingAnAlreadyRemovedContainerSucceeds(t *testing.T) {
	r := &fakeRunner{handle: func([]string) reply { return absent() }}
	b, _ := newTestBackend(t, testConfig(), r)
	if err := b.Delete(context.Background(), "i-1"); err != nil {
		t.Fatal(err)
	}
	gone := &fakeRunner{handle: func(args []string) reply {
		if args[0] == "rm" {
			return absent()
		}
		return inspecting(t, containerState{status: "running", labels: owned("i-1")})(args)
	}}
	b, _ = newTestBackend(t, testConfig(), gone)
	if err := b.Delete(context.Background(), "i-1"); err != nil {
		t.Fatalf("a container reaped between inspect and rm failed retirement: %v", err)
	}
}

func TestDeleteRefusesANamesakeOfAnotherInstance(t *testing.T) {
	r := &fakeRunner{handle: inspecting(t, containerState{status: "running", labels: owned("other")})}
	b, _ := newTestBackend(t, testConfig(), r)
	if err := b.Delete(context.Background(), "i-1"); err == nil {
		t.Fatal("another instance's container was deleted")
	}
	if r.called("rm") {
		t.Fatal("rm ran")
	}
}

func TestStatusOfAMissingWorkloadIsNotFound(t *testing.T) {
	r := &fakeRunner{handle: func([]string) reply { return absent() }}
	b, _ := newTestBackend(t, testConfig(), r)
	if _, err := b.Status(context.Background(), "i-1"); !errors.Is(err, workload.ErrNotFound) {
		t.Fatalf("Status() error = %v, want ErrNotFound", err)
	}
}

func TestRunningStatusCarriesTheNetworkAddress(t *testing.T) {
	for name, tc := range map[string]struct {
		st   containerState
		want string
	}{
		"configured network": {containerState{networks: map[string]string{"other": "10.9.9.9", "agentarea-mcp": " 172.18.0.3 "}}, "http://172.18.0.3:8080"},
		"any network":        {containerState{networks: map[string]string{"bridge": "172.17.0.4"}}, "http://172.17.0.4:8080"},
		"flat field":         {containerState{networks: map[string]string{"bridge": ""}, flatIP: "10.0.0.5"}, "http://10.0.0.5:8080"},
	} {
		tc.st.status, tc.st.labels, tc.st.env = "running", owned("i-1"), []string{"MCP_CONTAINER_PORT=8080"}
		b, _ := newTestBackend(t, testConfig(), &fakeRunner{handle: inspecting(t, tc.st)})
		got, err := b.Status(context.Background(), "i-1")
		if err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		if got.Status != workload.StatusRunning || got.InternalURL != tc.want || got.Port != 8080 {
			t.Fatalf("%s: status = %+v, want %s", name, got, tc.want)
		}
	}
}

func TestRunningStatusWithoutAnAddressIsAnError(t *testing.T) {
	st := containerState{status: "running", labels: owned("i-1"), env: []string{"MCP_CONTAINER_PORT=8080"}}
	b, _ := newTestBackend(t, testConfig(), &fakeRunner{handle: inspecting(t, st)})
	if _, err := b.Status(context.Background(), "i-1"); err == nil {
		t.Fatal("an addressless running container was reported reachable")
	}
}

func TestCreatedContainerIsStarting(t *testing.T) {
	st := containerState{status: "created", labels: owned("i-1"), env: []string{"MCP_CONTAINER_PORT=8080"}}
	b, _ := newTestBackend(t, testConfig(), &fakeRunner{handle: inspecting(t, st)})
	got, err := b.Status(context.Background(), "i-1")
	if err != nil || got.Status != workload.StatusStarting {
		t.Fatalf("Status() = %+v, %v", got, err)
	}
}

func TestStoppedStatusClassifiesWithoutLeakingItsOutput(t *testing.T) {
	st := containerState{status: "exited", exitCode: 17, labels: owned("i-1"),
		env: []string{"MCP_CONTAINER_PORT=8123", "API_KEY=sk-live-6f2b91c4aa77"}}
	b, logged := newTestBackend(t, testConfig(), &fakeRunner{handle: inspecting(t, st)})
	got, err := b.Status(context.Background(), "i-1")
	if err != nil {
		t.Fatal(err)
	}
	if got.Status != workload.StatusStopped || got.Message != "workload exited with code 17 during startup" {
		t.Fatalf("status = %+v", got)
	}
	if strings.Contains(logged.String(), "sk-live") || strings.Contains(logged.String(), "on port 8123") {
		t.Fatalf("workload output reached the log:\n%s", logged)
	}
	if !strings.Contains(logged.String(), "workload exited with code 17 during startup") {
		t.Fatalf("the log lacks the reason:\n%s", logged)
	}
}

func TestStoppedOutputIsRedactedWhenAHostAsksForIt(t *testing.T) {
	cfg := testConfig()
	cfg.LogWorkloadOutput = true
	st := containerState{status: "exited", exitCode: 1, labels: owned("i-1"),
		env: []string{"MCP_CONTAINER_PORT=8123", "API_KEY=sk-live-6f2b91c4aa77"}}
	b, logged := newTestBackend(t, cfg, &fakeRunner{handle: inspecting(t, st)})
	got, err := b.Status(context.Background(), "i-1")
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(got.Message, "port 8123") {
		t.Fatalf("output crossed into the status: %q", got.Message)
	}
	out := logged.String()
	if strings.Contains(out, "sk-live-6f2b91c4aa77") || !strings.Contains(out, "[redacted API_KEY]") ||
		!strings.Contains(out, "on port 8123") || strings.Contains(out, "\\x1b") {
		t.Fatalf("log = %s", out)
	}
}

func TestClassifyStartupFailureReturnsOnlySafeReasons(t *testing.T) {
	for _, tc := range []struct {
		name, output, want string
		code               int
		hasCode            bool
	}{
		{name: "npm", output: "npm error could not determine executable to run token=secret-value", want: "package has no executable"},
		{name: "python", output: "An executable named `server` is not provided by package `server` token=secret-value", want: "package has no executable"},
		{name: "import", output: "ImportError: cannot import name 'McpError'", want: "workload failed to import a dependency during startup"},
		{name: "mcp-base", output: "[mcp-base] the stdio server stopped before it initialized", want: "workload failed during MCP server initialization"},
		{name: "exit", code: 17, hasCode: true, output: "token=secret-value", want: "workload exited with code 17 during startup"},
		{name: "clean exit", hasCode: true, want: "workload failed during startup"},
	} {
		got := classifyStartupFailure(tc.code, tc.hasCode, tc.output)
		if got != tc.want || strings.Contains(got, "secret-value") {
			t.Errorf("%s: %q, want %q", tc.name, got, tc.want)
		}
	}
}

func TestRedactionDropsTheSecretsTheWorkloadWasGiven(t *testing.T) {
	got := redactEnvironment("connecting with sk-live-6f2b91c4aa77 and short=abc",
		map[string]string{"API_KEY": "sk-live-6f2b91c4aa77", "MODE": "abc"})
	if strings.Contains(got, "sk-live") || !strings.Contains(got, "[redacted API_KEY]") || !strings.Contains(got, "short=abc") {
		t.Fatalf("redacted = %q", got)
	}
	if long := redactEnvironment(strings.Repeat("x", 5000), nil); len(long) != maxLoggedOutput+len(" [truncated]") {
		t.Fatalf("long output not truncated: %d", len(long))
	}
}

func TestRuntimeRefusalNamesTheCauseWithoutEchoingTheRuntime(t *testing.T) {
	got := runtimeRefusal([]byte("docker: Error response from daemon: pull access denied for reg.example.com/team/app"))
	if !strings.Contains(got, "no credentials") || strings.Contains(got, "reg.example.com") {
		t.Fatalf("runtimeRefusal() = %q", got)
	}
	if got := runtimeRefusal([]byte(`Conflict. The container name "/mcp-x" is already in use by container "abc".`)); !strings.Contains(got, "name") {
		t.Fatalf("runtimeRefusal() = %q", got)
	}
	if got := runtimeRefusal(nil); got != "the runtime failed without output" {
		t.Fatalf("runtimeRefusal(nil) = %q", got)
	}
}
