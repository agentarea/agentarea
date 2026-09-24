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

// descendantProcesses lists every live or zombie descendant of rootPID,
// breadth first, so a parent always precedes its children.
func descendantProcesses(rootPID int) ([]descendant, error) {
	entries, err := os.ReadDir("/proc")
	if err != nil {
		return nil, err
	}
	children := make(map[int][]descendant, len(entries))
	for _, entry := range entries {
		pid, err := strconv.Atoi(entry.Name())
		if err != nil || pid <= 0 {
			continue
		}
		data, err := os.ReadFile("/proc/" + entry.Name() + "/stat")
		if err != nil {
			if errors.Is(err, os.ErrNotExist) || errors.Is(err, unix.ESRCH) {
				continue
			}
			return nil, err
		}
		closing := strings.LastIndexByte(string(data), ')')
		if closing < 0 {
			return nil, fmt.Errorf("malformed /proc/%d/stat", pid)
		}
		fields := strings.Fields(string(data[closing+1:]))
		if len(fields) < 2 || len(fields[0]) != 1 {
			return nil, fmt.Errorf("malformed /proc/%d/stat fields", pid)
		}
		parent, err := strconv.Atoi(fields[1])
		if err != nil {
			return nil, fmt.Errorf("parse /proc/%d parent: %w", pid, err)
		}
		children[parent] = append(children[parent], descendant{pid: pid, state: fields[0][0]})
	}

	result := make([]descendant, 0)
	seen := map[int]bool{rootPID: true}
	queue := []int{rootPID}
	for len(queue) > 0 {
		parent := queue[0]
		queue = queue[1:]
		for _, child := range children[parent] {
			if seen[child.pid] {
				continue
			}
			seen[child.pid] = true
			result = append(result, child)
			queue = append(queue, child.pid)
		}
	}
	return result, nil
}
