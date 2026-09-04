package sandboxruntime

import (
	"errors"
	"fmt"
	"io"
	"time"

	"github.com/agentarea/mcp-manager/internal/execsupervisor"
)

const supervisorCleanupGraceSeconds = int(execsupervisor.CompletionGrace / time.Second)

func (execution QuiescentExecution) validate() (int, error) {
	if execution.Request.CommandBody == "" {
		return 0, fmt.Errorf("quiescent execution command is required")
	}
	if execution.MaxFileBytes <= 0 {
		return 0, fmt.Errorf("quiescent execution file-size limit must be positive")
	}
	if err := execution.Supervisor.Validate(); err != nil {
		return 0, fmt.Errorf("quiescent execution supervisor: %w", err)
	}
	for _, artifactPath := range execution.Request.ArtifactPaths {
		if _, err := sandboxPath(artifactPath); err != nil {
			return 0, fmt.Errorf("invalid artifact path %q: %w", artifactPath, err)
		}
	}
	timeout := execution.Request.TimeoutSeconds
	if timeout <= 0 {
		return 0, fmt.Errorf("quiescent execution timeout must be positive")
	}
	return timeout, nil
}

func verifySupervisorDownload(download *FileDownload, expected execsupervisor.Attestation) error {
	if download == nil || download.Content == nil {
		return fmt.Errorf("execution supervisor download is unavailable")
	}
	verifyErr := execsupervisor.VerifyBinary(download.Content, download.Size, expected)
	closeErr := download.Content.Close()
	return errors.Join(verifyErr, closeErr)
}

func decodeSupervisorStatusDownload(download *FileDownload, expected execsupervisor.Attestation) (execsupervisor.Status, error) {
	if download == nil || download.Content == nil || download.Size <= 0 || download.Size > execsupervisor.MaxStatusBytes {
		return execsupervisor.Status{}, fmt.Errorf("execution supervisor status has an invalid size")
	}
	payload, readErr := io.ReadAll(io.LimitReader(download.Content, execsupervisor.MaxStatusBytes+1))
	closeErr := download.Content.Close()
	if readErr != nil || closeErr != nil {
		return execsupervisor.Status{}, errors.Join(readErr, closeErr)
	}
	if int64(len(payload)) != download.Size {
		return execsupervisor.Status{}, fmt.Errorf("execution supervisor status size changed while reading")
	}
	return execsupervisor.DecodeStatus(payload, expected)
}
