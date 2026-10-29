package mcpgateway

import (
	"context"
	"errors"
	"fmt"
	"testing"
)

func TestClassifyColdStart(t *testing.T) {
	stopped := &StartupFailureError{reason: "stopped", cause: &workloadStoppedDuringStartupError{status: "exited"}}
	cases := []struct {
		name    string
		step    activationStep
		err     error
		outcome ColdStartOutcome
		reason  string
	}{
		{name: "ready", outcome: ColdStartReady},
		{name: "create failed", step: stepCreate, err: errors.New("quota"), outcome: ColdStartFailed, reason: "create_failed"},
		{name: "deadline while waiting to run", step: stepRunning, err: &StartupFailureError{cause: errStartupDeadline}, outcome: ColdStartTimeout, reason: "not_running"},
		{name: "context expired while waiting to run", step: stepRunning, err: fmt.Errorf("wait: %w", context.DeadlineExceeded), outcome: ColdStartTimeout, reason: "not_running"},
		{name: "inspection failed", step: stepRunning, err: errors.New("api down"), outcome: ColdStartFailed, reason: "inspect_failed"},
		{name: "stopped while running", step: stepRunning, err: stopped, outcome: ColdStartFailed, reason: "stopped"},
		{name: "stopped while listening", step: stepListening, err: errors.Join(stopped, errors.New("cleanup")), outcome: ColdStartFailed, reason: "stopped"},
		{name: "never listened", step: stepListening, err: errors.New("never accepted a connection"), outcome: ColdStartTimeout, reason: "not_listening"},
		{name: "observer refused", step: stepObserver, err: errors.New("ledger"), outcome: ColdStartFailed, reason: "observer_refused"},
		{name: "lease failed", step: stepAdmission, err: errors.New("ownership lost"), outcome: ColdStartFailed, reason: "admission_failed"},
		{name: "unattributed", err: errors.New("?"), outcome: ColdStartFailed, reason: "other"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			outcome, reason := classifyColdStart(tc.step, tc.err)
			if outcome != tc.outcome || reason != tc.reason {
				t.Fatalf("classifyColdStart = %s/%s, want %s/%s", outcome, reason, tc.outcome, tc.reason)
			}
		})
	}
}

func TestGatewayStatus(t *testing.T) {
	cases := []struct {
		status   int
		answer   GatewayAnswer
		canceled bool
		want     string
	}{
		{status: 200, want: "2xx"},
		{status: 400, want: "4xx"},
		{status: 503, want: "5xx"},
		{status: 503, answer: AnswerStarting, want: "503_starting"},
		{status: 503, answer: AnswerStartFailed, want: "503_start_failed"},
		{status: 502, answer: AnswerStartFailed, want: "502_start_failed"},
		{status: 0, canceled: true, want: "canceled"},
		{status: 0, want: "none"},
		{status: 999, want: "other"},
	}
	for _, tc := range cases {
		if got := gatewayStatus(tc.status, tc.answer, tc.canceled); got != tc.want {
			t.Fatalf("gatewayStatus(%d, %q, %v) = %q, want %q", tc.status, tc.answer, tc.canceled, got, tc.want)
		}
	}
}

func TestMCPMethodName(t *testing.T) {
	value := func(s string) *string { return &s }
	cases := []struct {
		header *string
		want   string
	}{
		{header: nil, want: "none"},
		{header: value("tools/call"), want: "tools/call"},
		{header: value("server/discover"), want: "server/discover"},
		{header: value("tools/call?x=1"), want: "other"},
		{header: value(""), want: "other"},
	}
	for _, tc := range cases {
		if got := mcpMethodName(tc.header); got != tc.want {
			t.Fatalf("mcpMethodName = %q, want %q", got, tc.want)
		}
	}
}
