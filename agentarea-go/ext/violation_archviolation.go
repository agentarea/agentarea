//go:build archviolation

package ext

import _ "github.com/agentarea/agentarea/agentarea-go/internal/modules/projects" // want depguard
