//go:build archviolation

package ext

import _ "github.com/agentarea/agentarea/agentarea-platform/internal/modules/projects" // want depguard
