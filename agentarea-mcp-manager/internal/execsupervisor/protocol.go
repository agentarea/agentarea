package execsupervisor

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"path"
	"strconv"
	"strings"
	"time"
)

const (
	ProtocolVersion = 1
	StatusRoot      = "/run/agentarea-executions"
	MaxBinaryBytes  = 64 * 1024 * 1024
	MaxStatusBytes  = 4 * 1024

	// DescendantDrainTimeout bounds the supervisor's kill/reap phase after the
	// requested command has exited or timed out. CompletionGrace also reserves
	// time for the durable status commit; TransportGrace is the minimum margin a
	// caller must add so it never kills the supervisor before that proof exists.
	DescendantDrainTimeout = 5 * time.Second
	CompletionGrace        = DescendantDrainTimeout + 5*time.Second
	PostExecutionBudget    = 30 * time.Second
	NetworkGrace           = 5 * time.Second
	TransportGrace         = CompletionGrace + PostExecutionBudget + NetworkGrace
)

// Attestation is the immutable runtime contract for the privileged execution
// supervisor. The control plane supplies it from the digest-pinned runtime
// manifest and providers verify the binary before admitting task code.
type Attestation struct {
	Path            string `json:"path"`
	SHA256          string `json:"sha256"`
	ProtocolVersion int    `json:"protocol_version"`
	CommandUID      uint32 `json:"command_uid"`
	CommandGID      uint32 `json:"command_gid"`
}

func (a Attestation) Validate() error {
	if a.ProtocolVersion != ProtocolVersion {
		return fmt.Errorf("execution supervisor protocol_version must be %d", ProtocolVersion)
	}
	if !strings.HasPrefix(a.Path, "/") || path.Clean(a.Path) != a.Path || a.Path == "/" {
		return fmt.Errorf("execution supervisor path must be an absolute clean file path")
	}
	if len(a.SHA256) != 64 || strings.ToLower(a.SHA256) != a.SHA256 {
		return fmt.Errorf("execution supervisor sha256 must be a lowercase SHA-256 digest")
	}
	if _, err := hex.DecodeString(a.SHA256); err != nil {
		return fmt.Errorf("execution supervisor sha256 is invalid: %w", err)
	}
	if a.CommandUID == 0 || a.CommandGID == 0 {
		return fmt.Errorf("execution supervisor command uid and gid must be non-root")
	}
	return nil
}

// Status is written atomically by the root-owned supervisor only after every
// descendant has been killed and reaped. The outer process exits zero only
// after this document is durable; child exit status remains separate.
type Status struct {
	ProtocolVersion  int    `json:"protocol_version"`
	SupervisorSHA256 string `json:"supervisor_sha256"`
	Quiescent        bool   `json:"quiescent"`
	ChildExitCode    int    `json:"child_exit_code"`
	TimedOut         bool   `json:"timed_out"`
}

func DecodeStatus(data []byte, expected Attestation) (Status, error) {
	if err := expected.Validate(); err != nil {
		return Status{}, err
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	var status Status
	if err := decoder.Decode(&status); err != nil {
		return Status{}, fmt.Errorf("decode execution supervisor status: %w", err)
	}
	if err := decoder.Decode(&struct{}{}); err != io.EOF {
		return Status{}, fmt.Errorf("decode execution supervisor status: trailing data")
	}
	if status.ProtocolVersion != expected.ProtocolVersion {
		return Status{}, fmt.Errorf("execution supervisor status used protocol %d, expected %d", status.ProtocolVersion, expected.ProtocolVersion)
	}
	if status.SupervisorSHA256 != expected.SHA256 {
		return Status{}, fmt.Errorf("execution supervisor status digest did not match the runtime manifest")
	}
	if !status.Quiescent {
		return Status{}, fmt.Errorf("execution supervisor did not prove process quiescence")
	}
	if status.ChildExitCode < 0 || status.ChildExitCode > 255 {
		return Status{}, fmt.Errorf("execution supervisor returned invalid child exit code %d", status.ChildExitCode)
	}
	if status.TimedOut && status.ChildExitCode != 124 {
		return Status{}, fmt.Errorf("timed-out execution supervisor status must use child exit code 124")
	}
	return status, nil
}

func StatusPath(executionID string) (string, error) {
	if executionID == "" || len(executionID) > 128 {
		return "", fmt.Errorf("execution id is invalid")
	}
	for _, character := range executionID {
		if (character < 'a' || character > 'z') &&
			(character < 'A' || character > 'Z') &&
			(character < '0' || character > '9') && character != '-' && character != '_' {
			return "", fmt.Errorf("execution id is invalid")
		}
	}
	return path.Join(StatusRoot, executionID+".json"), nil
}

// VerifyBinary authenticates a supervisor body obtained through a provider's
// control API. The declared size is part of the check: a matching prefix with
// trailing bytes is never accepted as the attested executable.
func VerifyBinary(content io.Reader, declaredSize int64, expected Attestation) error {
	if err := expected.Validate(); err != nil {
		return err
	}
	if content == nil || declaredSize <= 0 || declaredSize > MaxBinaryBytes {
		return fmt.Errorf("execution supervisor binary size must be between 1 and %d bytes", MaxBinaryBytes)
	}
	hasher := sha256.New()
	written, err := io.Copy(hasher, io.LimitReader(content, declaredSize+1))
	if err != nil {
		return fmt.Errorf("hash execution supervisor binary: %w", err)
	}
	if written != declaredSize {
		return fmt.Errorf("execution supervisor binary size was %d, expected %d", written, declaredSize)
	}
	if actual := hex.EncodeToString(hasher.Sum(nil)); actual != expected.SHA256 {
		return fmt.Errorf("execution supervisor binary digest did not match the runtime manifest")
	}
	return nil
}

func RunArgs(
	attestation Attestation,
	statusPath string,
	timeoutSeconds int,
	maxFileBytes int64,
	command ...string,
) ([]string, error) {
	if err := attestation.Validate(); err != nil {
		return nil, err
	}
	if !strings.HasPrefix(statusPath, StatusRoot+"/") || path.Clean(statusPath) != statusPath || path.Dir(statusPath) != StatusRoot {
		return nil, fmt.Errorf("execution supervisor status path is invalid")
	}
	if timeoutSeconds <= 0 || maxFileBytes <= 0 || len(command) == 0 || command[0] == "" {
		return nil, fmt.Errorf("execution supervisor requires a command, timeout, and file-size limit")
	}
	args := []string{
		"run",
		"--protocol", strconv.Itoa(attestation.ProtocolVersion),
		"--status", statusPath,
		"--uid", strconv.FormatUint(uint64(attestation.CommandUID), 10),
		"--gid", strconv.FormatUint(uint64(attestation.CommandGID), 10),
		"--timeout-seconds", strconv.Itoa(timeoutSeconds),
		"--max-file-bytes", strconv.FormatInt(maxFileBytes, 10),
		"--",
	}
	return append(args, command...), nil
}

func Invocation(
	attestation Attestation,
	statusPath string,
	timeoutSeconds int,
	maxFileBytes int64,
	commandBody string,
) (string, error) {
	args, err := RunArgs(attestation, statusPath, timeoutSeconds, maxFileBytes, "/bin/sh", "-c", commandBody)
	if err != nil {
		return "", err
	}
	args = append([]string{attestation.Path}, args...)
	quoted := make([]string, len(args))
	for index, arg := range args {
		quoted[index] = shellQuote(arg)
	}
	return strings.Join(quoted, " "), nil
}

func shellQuote(value string) string {
	return "'" + strings.ReplaceAll(value, "'", "'\"'\"'") + "'"
}
