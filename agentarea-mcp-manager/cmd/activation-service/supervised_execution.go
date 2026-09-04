package main

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"syscall"
	"time"

	"github.com/agentarea/mcp-manager/internal/execsupervisor"
	"github.com/google/uuid"
)

type supervisedCommandRequest struct {
	Attestation    execsupervisor.Attestation
	CommandPath    string
	WorkspaceDir   string
	Environment    []string
	TimeoutSeconds int
	MaxFileBytes   int64
	Stdout         io.Writer
	Stderr         io.Writer
}

type supervisedCommandRunner func(context.Context, supervisedCommandRequest) (execsupervisor.Status, error)

var (
	runSandboxCommand   = runAttestedSandboxCommand
	executorInvalidator = func() {
		_ = syscall.Kill(os.Getpid(), syscall.SIGTERM)
	}
)

func runAttestedSandboxCommand(ctx context.Context, request supervisedCommandRequest) (execsupervisor.Status, error) {
	if request.TimeoutSeconds <= 0 || request.MaxFileBytes <= 0 || request.CommandPath == "" || request.WorkspaceDir == "" {
		return execsupervisor.Status{}, fmt.Errorf("supervised command request is incomplete")
	}
	if os.Geteuid() != 0 {
		return execsupervisor.Status{}, fmt.Errorf("execution supervisor requires a root activation service")
	}
	if err := verifyLocalExecutionSupervisor(request.Attestation); err != nil {
		return execsupervisor.Status{}, err
	}
	statusPath, err := execsupervisor.StatusPath(uuid.NewString())
	if err != nil {
		return execsupervisor.Status{}, err
	}
	args, err := execsupervisor.RunArgs(
		request.Attestation,
		statusPath,
		request.TimeoutSeconds,
		request.MaxFileBytes,
		"/bin/sh", request.CommandPath,
	)
	if err != nil {
		return execsupervisor.Status{}, err
	}
	outerCtx, cancel := context.WithTimeout(
		ctx,
		time.Duration(request.TimeoutSeconds)*time.Second+execsupervisor.CompletionGrace,
	)
	defer cancel()
	command := exec.CommandContext(outerCtx, request.Attestation.Path, args...) // #nosec G204 -- path and digest come from the validated runtime manifest
	command.Dir = request.WorkspaceDir
	command.Env = request.Environment
	command.Stdout = request.Stdout
	command.Stderr = request.Stderr
	if err := command.Run(); err != nil {
		return execsupervisor.Status{}, fmt.Errorf("execution supervisor did not complete cleanly: %w", err)
	}
	status, statusErr := readLocalExecutionStatus(statusPath, request.Attestation)
	removeErr := os.Remove(statusPath)
	if removeErr != nil && !errors.Is(removeErr, os.ErrNotExist) {
		removeErr = fmt.Errorf("remove execution supervisor status: %w", removeErr)
	} else {
		removeErr = nil
	}
	return status, errors.Join(statusErr, removeErr)
}

func verifyLocalExecutionSupervisor(expected execsupervisor.Attestation) error {
	if err := expected.Validate(); err != nil {
		return err
	}
	info, err := os.Lstat(expected.Path)
	if err != nil {
		return fmt.Errorf("inspect execution supervisor: %w", err)
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || !info.Mode().IsRegular() || stat.Uid != 0 || info.Mode().Perm()&0o022 != 0 || info.Mode().Perm()&0o100 == 0 {
		return fmt.Errorf("execution supervisor must be a root-owned regular executable that is not group/other writable")
	}
	file, err := os.Open(expected.Path)
	if err != nil {
		return fmt.Errorf("open execution supervisor: %w", err)
	}
	verifyErr := execsupervisor.VerifyBinary(file, info.Size(), expected)
	closeErr := file.Close()
	return errors.Join(verifyErr, closeErr)
}

func readLocalExecutionStatus(statusPath string, expected execsupervisor.Attestation) (execsupervisor.Status, error) {
	info, err := os.Lstat(statusPath)
	if err != nil {
		return execsupervisor.Status{}, fmt.Errorf("inspect execution supervisor status: %w", err)
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || !info.Mode().IsRegular() || stat.Uid != 0 || info.Mode().Perm() != 0o600 || info.Size() <= 0 || info.Size() > execsupervisor.MaxStatusBytes {
		return execsupervisor.Status{}, fmt.Errorf("execution supervisor status is not a bounded root-owned 0600 regular file")
	}
	payload, err := os.ReadFile(statusPath)
	if err != nil {
		return execsupervisor.Status{}, fmt.Errorf("read execution supervisor status: %w", err)
	}
	return execsupervisor.DecodeStatus(payload, expected)
}
