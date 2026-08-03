//go:build !linux

package main

import (
	"fmt"
	"os"
)

func openSelfExecutable() (*os.File, error) {
	executable, err := os.Executable()
	if err != nil {
		return nil, err
	}
	return os.Open(executable)
}

func enableChildSubreaper() error {
	if os.Getenv("AGENTAREA_EXEC_SUPERVISOR_ALLOW_NON_LINUX_TEST") == "true" {
		return nil
	}
	return fmt.Errorf("execution supervisor requires Linux")
}

func descendantPIDs(_ int) ([]int, error) {
	if os.Getenv("AGENTAREA_EXEC_SUPERVISOR_ALLOW_NON_LINUX_TEST") == "true" {
		return nil, nil
	}
	return nil, fmt.Errorf("execution supervisor requires Linux")
}
