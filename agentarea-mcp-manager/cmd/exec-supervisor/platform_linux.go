//go:build linux

package main

import (
	"errors"
	"fmt"
	"os"
	"strconv"
	"strings"

	"golang.org/x/sys/unix"
)

func openSelfExecutable() (*os.File, error) {
	return os.Open("/proc/self/exe")
}

func enableChildSubreaper() error {
	if err := unix.Prctl(unix.PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0); err != nil {
		return fmt.Errorf("enable child subreaper: %w", err)
	}
	return nil
}

func descendantPIDs(rootPID int) ([]int, error) {
	entries, err := os.ReadDir("/proc")
	if err != nil {
		return nil, err
	}
	parents := make(map[int]int, len(entries))
	for _, entry := range entries {
		pid, err := strconv.Atoi(entry.Name())
		if err != nil || pid <= 0 {
			continue
		}
		data, err := os.ReadFile("/proc/" + entry.Name() + "/stat")
		if err != nil {
			if errors.Is(err, os.ErrNotExist) {
				continue
			}
			return nil, err
		}
		closing := strings.LastIndexByte(string(data), ')')
		if closing < 0 {
			return nil, fmt.Errorf("malformed /proc/%d/stat", pid)
		}
		fields := strings.Fields(string(data[closing+1:]))
		if len(fields) < 2 {
			return nil, fmt.Errorf("malformed /proc/%d/stat fields", pid)
		}
		parent, err := strconv.Atoi(fields[1])
		if err != nil {
			return nil, fmt.Errorf("parse /proc/%d parent: %w", pid, err)
		}
		parents[pid] = parent
	}

	descendant := map[int]bool{rootPID: true}
	changed := true
	for changed {
		changed = false
		for pid, parent := range parents {
			if !descendant[pid] && descendant[parent] {
				descendant[pid] = true
				changed = true
			}
		}
	}
	result := make([]int, 0, len(descendant)-1)
	for pid := range descendant {
		if pid != rootPID {
			result = append(result, pid)
		}
	}
	return result, nil
}
