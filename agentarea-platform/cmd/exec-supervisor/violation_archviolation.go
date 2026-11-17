//go:build archviolation

package main

import (
	_ "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope" // want depguard
	_ "os/exec"                                                           // allowed
)
