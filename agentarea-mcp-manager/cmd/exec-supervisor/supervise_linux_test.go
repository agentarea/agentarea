//go:build linux

package main

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/execsupervisor"
)

type superviseHelperResult struct {
	ExitCode int    `json:"exit_code"`
	TimedOut bool   `json:"timed_out"`
	Error    string `json:"error,omitempty"`
}

func TestMain(m *testing.M) {
	if len(os.Args) > 1 && os.Args[1] == "child" {
		if err := runChild(os.Args[2:]); err != nil {
			_, _ = fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		os.Exit(0)
	}
	os.Exit(m.Run())
}

func TestSuperviseHelperProcess(t *testing.T) {
	if os.Getenv("AGENTAREA_SUPERVISE_HELPER") != "true" {
		return
	}
	payload, err := base64.StdEncoding.DecodeString(os.Getenv("AGENTAREA_SUPERVISE_COMMAND"))
	if err != nil {
		panic(err)
	}
	var command []string
	if err := json.Unmarshal(payload, &command); err != nil {
		panic(err)
	}
	timeout, err := time.ParseDuration(os.Getenv("AGENTAREA_SUPERVISE_TIMEOUT"))
	if err != nil {
		panic(err)
	}
	maxFileBytes, err := strconv.ParseUint(os.Getenv("AGENTAREA_SUPERVISE_MAX_FILE_BYTES"), 10, 64)
	if err != nil {
		panic(err)
	}
	if err := enableChildSubreaper(); err != nil {
		panic(err)
	}
	uid, gid := uint32(os.Getuid()), uint32(os.Getgid())
	if uid == 0 || gid == 0 {
		uid, gid = 65534, 65534
	}
	result, err := supervise(command, uid, gid, timeout, maxFileBytes)
	output := superviseHelperResult{ExitCode: result.exitCode, TimedOut: result.timedOut}
	if err != nil {
		output.Error = err.Error()
	}
	file, err := os.Create(os.Getenv("AGENTAREA_SUPERVISE_RESULT"))
	if err != nil {
		panic(err)
	}
	if err := json.NewEncoder(file).Encode(output); err != nil {
		panic(err)
	}
	if err := file.Close(); err != nil {
		panic(err)
	}
	os.Exit(0)
}

func runSuperviseHelper(t *testing.T, command []string, timeout time.Duration, maxFileBytes uint64) executionResult {
	t.Helper()
	payload, err := json.Marshal(command)
	if err != nil {
		t.Fatal(err)
	}
	resultPath := filepath.Join(t.TempDir(), "result.json")
	helper := exec.Command(os.Args[0], "-test.run=^TestSuperviseHelperProcess$")
	helper.Env = append(os.Environ(),
		"AGENTAREA_SUPERVISE_HELPER=true",
		"AGENTAREA_SUPERVISE_COMMAND="+base64.StdEncoding.EncodeToString(payload),
		"AGENTAREA_SUPERVISE_TIMEOUT="+timeout.String(),
		"AGENTAREA_SUPERVISE_MAX_FILE_BYTES="+strconv.FormatUint(maxFileBytes, 10),
		"AGENTAREA_SUPERVISE_RESULT="+resultPath,
	)
	if output, err := helper.CombinedOutput(); err != nil {
		t.Fatalf("supervisor helper: %v: %s", err, output)
	}
	file, err := os.Open(resultPath)
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	var output superviseHelperResult
	if err := json.NewDecoder(file).Decode(&output); err != nil {
		t.Fatal(err)
	}
	if output.Error != "" {
		t.Fatal(output.Error)
	}
	return executionResult{exitCode: output.ExitCode, timedOut: output.TimedOut}
}

func sandboxTempPath(t *testing.T, pattern string) string {
	t.Helper()
	file, err := os.CreateTemp("/tmp", pattern)
	if err != nil {
		t.Fatal(err)
	}
	path := file.Name()
	if err := file.Close(); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Remove(path) })
	return path
}

func TestSuperviseReapsSetsidAndDoubleForkDescendants(t *testing.T) {
	marker := sandboxTempPath(t, "agentarea-supervisor-escaped-*")
	command := fmt.Sprintf(`( setsid /bin/sh -c '( sleep 0.25; printf escaped > %q ) &' >/dev/null 2>&1 & ); exit 0`, marker)
	result := runSuperviseHelper(t, []string{"/bin/sh", "-c", command}, 5*time.Second, 1024*1024)
	if result.exitCode != 0 || result.timedOut {
		t.Fatalf("supervise() = %+v", result)
	}
	time.Sleep(400 * time.Millisecond)
	if _, err := os.Stat(marker); !os.IsNotExist(err) {
		t.Fatalf("setsid/double-fork descendant survived supervisor return: %v", err)
	}
}

func TestSuperviseTimeoutStillReachesQuiescence(t *testing.T) {
	marker := sandboxTempPath(t, "agentarea-supervisor-late-*")
	command := fmt.Sprintf(`setsid /bin/sh -c 'sleep 0.4; printf late > %q' >/dev/null 2>&1 & sleep 5`, marker)
	result := runSuperviseHelper(t, []string{"/bin/sh", "-c", command}, 100*time.Millisecond, 1024*1024)
	if !result.timedOut || result.exitCode != 124 {
		t.Fatalf("supervise() = %+v", result)
	}
	time.Sleep(500 * time.Millisecond)
	if _, err := os.Stat(marker); !os.IsNotExist(err) {
		t.Fatalf("timed-out descendant survived supervisor return: %v", err)
	}
}

func TestSuperviseAppliesPerFileHardLimit(t *testing.T) {
	target := sandboxTempPath(t, "agentarea-supervisor-large-*")
	result := runSuperviseHelper(t,
		[]string{"/bin/sh", "-c", fmt.Sprintf("dd if=/dev/zero of=%q bs=4096 count=32 2>/dev/null", target)},
		5*time.Second, 8192,
	)
	if result.exitCode == 0 {
		t.Fatal("command that crossed RLIMIT_FSIZE unexpectedly succeeded")
	}
	info, err := os.Stat(target)
	if err != nil {
		t.Fatal(err)
	}
	if info.Size() > 8192 {
		t.Fatalf("file size = %d, want <= 8192", info.Size())
	}
}

func TestRunPublishesStatusWhenChildFileLimitIsOneByte(t *testing.T) {
	if os.Geteuid() != 0 {
		t.Skip("root is required to exercise the real privilege boundary")
	}
	target := sandboxTempPath(t, "agentarea-supervisor-tiny-*")
	statusPath := filepath.Join(execsupervisor.StatusRoot, fmt.Sprintf("tiny-limit-%d.json", os.Getpid()))
	_ = os.Remove(statusPath)
	t.Cleanup(func() { _ = os.Remove(statusPath) })

	err := run([]string{
		"run", "--protocol", strconv.Itoa(execsupervisor.ProtocolVersion),
		"--status", statusPath, "--uid", "65534", "--gid", "65534",
		"--timeout-seconds", "5", "--max-file-bytes", "1", "--",
		"/bin/sh", "-c", fmt.Sprintf("printf xx > %q", target),
	})
	if err != nil {
		t.Fatalf("supervisor failed to publish status under child RLIMIT_FSIZE: %v", err)
	}
	payload, err := os.ReadFile(statusPath)
	if err != nil {
		t.Fatalf("read supervisor status: %v", err)
	}
	digest, err := selfDigest()
	if err != nil {
		t.Fatal(err)
	}
	status, err := execsupervisor.DecodeStatus(payload, execsupervisor.Attestation{
		Path: "/proc/self/exe", SHA256: digest, ProtocolVersion: execsupervisor.ProtocolVersion,
		CommandUID: 65534, CommandGID: 65534,
	})
	if err != nil {
		t.Fatalf("decode authenticated supervisor status: %v", err)
	}
	if status.ChildExitCode == 0 || !status.Quiescent {
		t.Fatalf("status = %+v, want bounded child failure and proven quiescence", status)
	}
}

func TestSuperviseDrainsManyDetachedChildren(t *testing.T) {
	started := time.Now()
	result := runSuperviseHelper(t,
		[]string{"/bin/sh", "-c", `i=0; while [ "$i" -lt 64 ]; do setsid /bin/sh -c 'sleep 10' >/dev/null 2>&1 & i=$((i+1)); done`},
		5*time.Second, 1024*1024,
	)
	if result.exitCode != 0 || time.Since(started) > 3*time.Second {
		t.Fatalf("supervise() = %+v in %s", result, time.Since(started))
	}
}
