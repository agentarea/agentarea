package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/agentarea/mcp-manager/internal/execsupervisor"
	"golang.org/x/sys/unix"
)

func main() {
	if err := run(os.Args[1:]); err != nil {
		_, _ = fmt.Fprintln(os.Stderr, "agentarea execution supervisor:", err)
		os.Exit(1)
	}
}

func run(args []string) error {
	if len(args) == 1 && args[0] == "version" {
		_, err := fmt.Fprintf(os.Stdout, "agentarea-exec-supervisor protocol=%d\n", execsupervisor.ProtocolVersion)
		return err
	}
	if len(args) > 0 && args[0] == "child" {
		return runChild(args[1:])
	}
	if len(args) == 0 || args[0] != "run" {
		return fmt.Errorf("expected version, run, or child")
	}
	flags := flag.NewFlagSet("run", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	protocol := flags.Int("protocol", 0, "protocol version")
	statusPath := flags.String("status", "", "root-owned completion status path")
	uid := flags.Uint("uid", 0, "child uid")
	gid := flags.Uint("gid", 0, "child gid")
	timeoutSeconds := flags.Int("timeout-seconds", 0, "execution timeout")
	maxFileBytes := flags.Int64("max-file-bytes", 0, "inherited RLIMIT_FSIZE")
	if err := flags.Parse(args[1:]); err != nil {
		return fmt.Errorf("parse arguments: %w", err)
	}
	command := flags.Args()
	if *protocol != execsupervisor.ProtocolVersion {
		return fmt.Errorf("unsupported protocol %d", *protocol)
	}
	if err := validateStatusPath(*statusPath); err != nil {
		return err
	}
	if *uid == 0 || *gid == 0 || uint64(*uid) > uint64(^uint32(0)) || uint64(*gid) > uint64(^uint32(0)) {
		return fmt.Errorf("child uid and gid must be non-root uint32 values")
	}
	if *timeoutSeconds <= 0 || *maxFileBytes <= 0 || len(command) == 0 {
		return fmt.Errorf("command, timeout, and max-file-bytes are required")
	}
	if os.Geteuid() != 0 {
		return fmt.Errorf("supervisor must run as root")
	}
	if err := enableChildSubreaper(); err != nil {
		return err
	}
	digest, err := selfDigest()
	if err != nil {
		return err
	}
	result, err := supervise(command, uint32(*uid), uint32(*gid), time.Duration(*timeoutSeconds)*time.Second, uint64(*maxFileBytes))
	if err != nil {
		return err
	}
	status := execsupervisor.Status{
		ProtocolVersion:  execsupervisor.ProtocolVersion,
		SupervisorSHA256: digest,
		Quiescent:        true,
		ChildExitCode:    result.exitCode,
		TimedOut:         result.timedOut,
	}
	return writeStatus(*statusPath, status)
}

type executionResult struct {
	exitCode int
	timedOut bool
}

func supervise(command []string, uid, gid uint32, timeout time.Duration, maxFileBytes uint64) (executionResult, error) {
	childArgs := []string{"child", "--max-file-bytes", strconv.FormatUint(maxFileBytes, 10), "--"}
	childArgs = append(childArgs, command...)
	// The non-root child stage applies RLIMIT_FSIZE to itself and then execs the
	// requested command. The privileged supervisor never inherits that limit, so
	// it can always publish the authenticated status even for very small quotas.
	cmd := exec.Command("/proc/self/exe", childArgs...) // #nosec G204 -- argv is the explicitly requested sandbox command
	cmd.Stdin = os.Stdin
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.Env = os.Environ()
	cmd.SysProcAttr = &syscall.SysProcAttr{
		Setpgid: true,
		Credential: &syscall.Credential{
			Uid: uid, Gid: gid, NoSetGroups: true,
		},
	}
	if err := cmd.Start(); err != nil {
		return executionResult{}, fmt.Errorf("start child: %w", err)
	}

	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	signals := make(chan os.Signal, 4)
	signal.Notify(signals, syscall.SIGTERM, syscall.SIGINT, syscall.SIGHUP)
	defer signal.Stop(signals)
	timer := time.NewTimer(timeout)
	defer timer.Stop()

	result := executionResult{}
	var waitErr error
	select {
	case waitErr = <-done:
	case <-timer.C:
		result.timedOut = true
		killProcessGroup(cmd.Process.Pid)
		waitErr = <-done
	case received := <-signals:
		killProcessGroup(cmd.Process.Pid)
		waitErr = <-done
		if signalValue, ok := received.(syscall.Signal); ok {
			result.exitCode = 128 + int(signalValue)
		} else {
			result.exitCode = 1
		}
	}

	if result.timedOut {
		result.exitCode = 124
	} else if result.exitCode == 0 {
		result.exitCode = exitCode(waitErr)
	}
	if err := drainDescendants(cmd.Process.Pid, execsupervisor.DescendantDrainTimeout); err != nil {
		return executionResult{}, err
	}
	return result, nil
}

func runChild(args []string) error {
	flags := flag.NewFlagSet("child", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	maxFileBytes := flags.Uint64("max-file-bytes", 0, "inherited RLIMIT_FSIZE")
	if err := flags.Parse(args); err != nil {
		return fmt.Errorf("parse child arguments: %w", err)
	}
	command := flags.Args()
	if *maxFileBytes == 0 || len(command) == 0 || command[0] == "" {
		return fmt.Errorf("child command and max-file-bytes are required")
	}
	if os.Geteuid() == 0 || os.Getegid() == 0 {
		return fmt.Errorf("child launcher must already be non-root")
	}
	if err := unix.Setrlimit(unix.RLIMIT_FSIZE, &unix.Rlimit{Cur: *maxFileBytes, Max: *maxFileBytes}); err != nil {
		return fmt.Errorf("set child file-size limit: %w", err)
	}
	if err := unix.Exec(command[0], command, os.Environ()); err != nil { // #nosec G204 -- sandbox command is the explicit child argv
		return fmt.Errorf("exec child command: %w", err)
	}
	return nil
}

func exitCode(err error) int {
	if err == nil {
		return 0
	}
	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) {
		code := exitErr.ExitCode()
		if code >= 0 && code <= 255 {
			return code
		}
	}
	return 1
}

func killProcessGroup(pid int) {
	if pid <= 0 {
		return
	}
	if err := syscall.Kill(-pid, syscall.SIGKILL); err != nil && !errors.Is(err, syscall.ESRCH) {
		_ = syscall.Kill(pid, syscall.SIGKILL)
	}
}

func drainDescendants(groupLeader int, timeout time.Duration) error {
	deadline := time.Now().Add(timeout)
	for {
		killProcessGroup(groupLeader)
		descendants, err := descendantPIDs(os.Getpid())
		if err != nil {
			return fmt.Errorf("enumerate descendants: %w", err)
		}
		for _, pid := range descendants {
			_ = syscall.Kill(pid, syscall.SIGKILL)
		}
		for {
			var status syscall.WaitStatus
			pid, waitErr := syscall.Wait4(-1, &status, syscall.WNOHANG, nil)
			switch {
			case pid > 0:
				continue
			case errors.Is(waitErr, syscall.ECHILD):
				return nil
			case waitErr != nil && !errors.Is(waitErr, syscall.EINTR):
				return fmt.Errorf("reap descendants: %w", waitErr)
			default:
			}
			break
		}
		if time.Now().After(deadline) {
			return fmt.Errorf("descendant drain did not reach ECHILD within %s", timeout)
		}
		time.Sleep(10 * time.Millisecond)
	}
}

func validateStatusPath(statusPath string) error {
	clean := filepath.Clean(statusPath)
	if clean != statusPath || filepath.Dir(clean) != execsupervisor.StatusRoot || !strings.HasSuffix(filepath.Base(clean), ".json") {
		return fmt.Errorf("status path must be one JSON file directly below %s", execsupervisor.StatusRoot)
	}
	return nil
}

func selfDigest() (string, error) {
	file, err := openSelfExecutable()
	if err != nil {
		return "", fmt.Errorf("open supervisor executable: %w", err)
	}
	defer file.Close()
	hasher := sha256.New()
	if _, err := io.Copy(hasher, file); err != nil {
		return "", fmt.Errorf("hash supervisor executable: %w", err)
	}
	return hex.EncodeToString(hasher.Sum(nil)), nil
}

func writeStatus(statusPath string, status execsupervisor.Status) error {
	if err := os.MkdirAll(execsupervisor.StatusRoot, 0o700); err != nil {
		return fmt.Errorf("create status directory: %w", err)
	}
	info, err := os.Lstat(execsupervisor.StatusRoot)
	if err != nil || !info.IsDir() || info.Mode().Perm()&0o077 != 0 {
		return fmt.Errorf("status directory is not a private real directory")
	}
	if stat, ok := info.Sys().(*syscall.Stat_t); !ok || stat.Uid != 0 {
		return fmt.Errorf("status directory is not root-owned")
	}
	payload, err := json.Marshal(status)
	if err != nil {
		return fmt.Errorf("encode status: %w", err)
	}
	temp, err := os.CreateTemp(execsupervisor.StatusRoot, ".status-*")
	if err != nil {
		return fmt.Errorf("create status tempfile: %w", err)
	}
	tempName := temp.Name()
	cleanup := func() { _ = os.Remove(tempName) }
	defer cleanup()
	if err := temp.Chmod(0o600); err != nil {
		temp.Close()
		return fmt.Errorf("chmod status tempfile: %w", err)
	}
	if _, err := temp.Write(payload); err != nil {
		temp.Close()
		return fmt.Errorf("write status tempfile: %w", err)
	}
	if err := temp.Sync(); err != nil {
		temp.Close()
		return fmt.Errorf("sync status tempfile: %w", err)
	}
	if err := temp.Close(); err != nil {
		return fmt.Errorf("close status tempfile: %w", err)
	}
	if err := os.Rename(tempName, statusPath); err != nil {
		return fmt.Errorf("commit status: %w", err)
	}
	directory, err := os.Open(execsupervisor.StatusRoot)
	if err != nil {
		return fmt.Errorf("open status directory: %w", err)
	}
	syncErr := directory.Sync()
	closeErr := directory.Close()
	return errors.Join(syncErr, closeErr)
}
