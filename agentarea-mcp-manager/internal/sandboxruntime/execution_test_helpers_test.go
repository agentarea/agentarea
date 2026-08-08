package sandboxruntime

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"strings"

	"github.com/agentarea/mcp-manager/internal/execsupervisor"
	"github.com/agentarea/mcp-manager/internal/sandboxcontract"
)

var testSupervisorBinary = []byte("static-test-execution-supervisor")

func testSupervisorAttestation() execsupervisor.Attestation {
	digest := sha256.Sum256(testSupervisorBinary)
	return execsupervisor.Attestation{
		Path:            "/usr/local/bin/agentarea-exec-supervisor",
		SHA256:          hex.EncodeToString(digest[:]),
		ProtocolVersion: execsupervisor.ProtocolVersion,
		CommandUID:      10001,
		CommandGID:      10001,
	}
}

func supervisorStatusPathFromShell(command string) string {
	marker := execsupervisor.StatusRoot + "/"
	start := strings.Index(command, marker)
	if start < 0 {
		return ""
	}
	end := strings.IndexByte(command[start:], '\'')
	if end < 0 {
		return ""
	}
	return command[start : start+end]
}

func testQuiescentExecution(request sandboxcontract.ExecuteRequest) QuiescentExecution {
	return QuiescentExecution{
		Request: request, Supervisor: testSupervisorAttestation(), MaxFileBytes: 1024 * 1024,
	}
}

func testSupervisorStatus(exitCode int) []byte {
	payload, err := json.Marshal(execsupervisor.Status{
		ProtocolVersion:  execsupervisor.ProtocolVersion,
		SupervisorSHA256: testSupervisorAttestation().SHA256,
		Quiescent:        true,
		ChildExitCode:    exitCode,
	})
	if err != nil {
		panic(err)
	}
	return payload
}
