package service

import (
	"context"
	"errors"
	"strconv"
)

// RunnerDelivery is a message or approval answer for the runner holding a
// turn: Kind steer (MessageID, Text), decision (RequestID, Approved) or pause.
type RunnerDelivery struct {
	ClientID, TaskID, TurnKey, Kind string
	MessageID, Text, RequestID      string
	Approved                        *bool
}

// DeliverToRunner broadcasts to the client's runner sockets; the one holding
// the turn passes it on (runner.py). Booleans travel as lowercase strings.
func (s *Service) DeliverToRunner(ctx context.Context, d RunnerDelivery) error {
	if s.d.Events == nil {
		return errors.New("delivering to a runner needs a broker")
	}
	if d.ClientID == "" {
		return nonRetryable("ValueError", "a runner delivery names no client", nil)
	}
	fields := map[string]string{}
	for k, v := range map[string]string{
		"task_id": d.TaskID, "turn_key": d.TurnKey, "kind": d.Kind,
		"message_id": d.MessageID, "text": d.Text, "request_id": d.RequestID,
	} {
		if v != "" {
			fields[k] = v
		}
	}
	if d.Approved != nil {
		fields["approved"] = strconv.FormatBool(*d.Approved)
	}
	return s.d.Events.NotifyRunner(ctx, d.ClientID, fields)
}

// RunRunnerTurn runs one turn on the client's runner; onUpdate receives each
// runner_turn_update frame while it runs.
func (s *Service) RunRunnerTurn(ctx context.Context, turn RunnerTurn, onUpdate func([]byte) error) (RunnerOutcome, error) {
	if s.d.Runner == nil {
		return RunnerOutcome{}, errors.New("running a runner turn needs the runner socket")
	}
	return s.d.Runner.RunTurn(ctx, turn, onUpdate)
}
