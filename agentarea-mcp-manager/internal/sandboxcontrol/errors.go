package sandboxcontrol

import "errors"

var (
	ErrExecutionNotFound = errors.New("sandbox execution not found")
	ErrExecutionConflict = errors.New("sandbox execution revision conflict")
	ErrInvalidExecution  = errors.New("invalid sandbox execution request")
)
