package docker

import (
	"context"
	"fmt"
	"regexp"
	"strings"
	"time"
)

var ansiRE = regexp.MustCompile(`\x1b\[[0-9;?]*[ -/]*[@-~]`)

// maxLoggedOutput bounds the workload output one log record carries.
const maxLoggedOutput = 4000

// stopDiagnostic classifies why a container stopped. The reason is safe to hand
// back; the workload's own output is third-party text holding whatever
// credentials it was given, so it reaches only the host log, redacted, and only
// when AGENTAREA_LOG_WORKLOAD asks for it.
func (b *Backend) stopDiagnostic(ctx context.Context, name string, info inspected, env map[string]string) string {
	evidenceCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 2*time.Second)
	defer cancel()
	stdout, stderr, err := b.run.Run(evidenceCtx, "logs", "--tail", "20", name)
	if err != nil {
		b.log.WarnContext(ctx, "could not read the output of a stopped MCP container", "container", name, "error", err)
	}
	output := strings.TrimSpace(ansiRE.ReplaceAllString(string(stdout)+string(stderr), ""))
	reason := classifyStartupFailure(info.State.ExitCode, true, output)
	if b.cfg.LogWorkloadOutput && output != "" {
		b.log.ErrorContext(ctx, "MCP container stopped", "container", name, "reason", reason,
			"workload_output", redactEnvironment(output, env))
	} else {
		b.log.ErrorContext(ctx, "MCP container stopped", "container", name, "reason", reason)
	}
	return reason
}

func classifyStartupFailure(exitCode int, hasExitCode bool, output string) string {
	lower := strings.ToLower(output)
	switch {
	case strings.Contains(lower, "could not determine executable to run"),
		strings.Contains(lower, "executable named") && strings.Contains(lower, "is not provided by package"):
		return "package has no executable"
	case strings.Contains(lower, "importerror: cannot import name"):
		return "workload failed to import a dependency during startup"
	case strings.Contains(lower, "[mcp-base] the stdio server stopped before it initialized"):
		return "workload failed during MCP server initialization"
	case hasExitCode && exitCode != 0:
		return fmt.Sprintf("workload exited with code %d during startup", exitCode)
	default:
		return "workload failed during startup"
	}
}

// redactEnvironment removes the values the container was given from text about
// to be logged. Values under four characters are not worth the message they
// would destroy, and the variables this backend sets itself hold no secret.
func redactEnvironment(text string, environment map[string]string) string {
	for key, value := range environment {
		if len(value) < 4 || key == envInstanceID || key == envServiceName || key == envPort {
			continue
		}
		text = strings.ReplaceAll(text, value, "[redacted "+key+"]")
	}
	if len(text) > maxLoggedOutput {
		text = text[:maxLoggedOutput] + " [truncated]"
	}
	return text
}
