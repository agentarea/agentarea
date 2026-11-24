package api

import (
	"context"
	"errors"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
)

// Decision question types (DecisionQuestionType).
const (
	QuestionChoice = "choice"
	QuestionScore  = "score"
)

// Decision is one System One request to a resolved decision model.
type Decision struct {
	Model ResolvedModel
	// Funded: billing holds the call, so a platform credential may be used.
	Funded    bool
	State     any
	Questions map[string]any
}

// DecisionReply is DecisionResult: one answer per question; CostUSD nil when neither the
// provider nor the spec says what the call cost.
type DecisionReply struct {
	Answers                   map[string]map[string]any
	CostUSD                   *money.Decimal
	InputTokens, OutputTokens int64
}

// ModelCallError is what a non-chat model call answered when it failed: its text never repeats
// what the endpoint said.
type ModelCallError struct{ Msg string }

func (e *ModelCallError) Error() string { return e.Msg }

// Decider asks decision models (DecisionModel.evaluate, POST /systemone).
type Decider interface {
	Decide(ctx context.Context, p Principal, d Decision) (DecisionReply, error)
}

// Model kinds (ModelKind).
const (
	KindChat     = "chat"
	KindDecision = "decision"
	KindImage    = "image"
	KindVideo    = "video"
)

// ErrKindMismatch: the instance's model is of another kind than the call needs (ModelKindMismatchError).
var ErrKindMismatch = errors.New("model kind mismatch")

// Describer resolves an instance for one call of a kind outside a run (ModelService.describe):
// no context window is required, the kind is.
type Describer interface {
	Describe(ctx context.Context, p Principal, modelID, kind string) (ResolvedModel, error)
}

// HTTPStatusError is a failed call the provider answered with an error status.
type HTTPStatusError interface{ HTTPStatus() int }
