package service

import (
	"context"
	"errors"
	"fmt"
	"testing"
	"time"

	"go.opentelemetry.io/otel/attribute"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/metric/metricdata"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/durable"
	kobs "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/obs"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
)

func newToolMetrics(t *testing.T) (*ToolTelemetry, *sdkmetric.ManualReader, *time.Time) {
	t.Helper()
	reader := sdkmetric.NewManualReader()
	provider := sdkmetric.NewMeterProvider(sdkmetric.WithReader(reader))
	t.Cleanup(func() { _ = provider.Shutdown(context.Background()) })
	tel, err := NewToolTelemetry(provider.Meter("test"))
	if err != nil {
		t.Fatal(err)
	}
	clock := fixedNow()
	tel.now = func() time.Time { return clock }
	return tel, reader, &clock
}

// toolPoints is every point of the tool instruments as "name kind/path[/outcome]" -> value.
func toolPoints(t *testing.T, reader *sdkmetric.ManualReader) map[string]float64 {
	t.Helper()
	var data metricdata.ResourceMetrics
	if err := reader.Collect(context.Background(), &data); err != nil {
		t.Fatal(err)
	}
	key := func(name string, a attribute.Set) string {
		kind, _ := a.Value(kobs.AttrToolKind)
		path, _ := a.Value(kobs.AttrPath)
		k := fmt.Sprintf("%s %s/%s", name, kind.AsString(), path.AsString())
		if outcome, ok := a.Value(kobs.AttrOutcome); ok {
			k += "/" + outcome.AsString()
		}
		return k
	}
	out := map[string]float64{}
	for _, scope := range data.ScopeMetrics {
		for _, m := range scope.Metrics {
			switch d := m.Data.(type) {
			case metricdata.Sum[int64]:
				for _, p := range d.DataPoints {
					out[key(m.Name, p.Attributes)] = float64(p.Value)
				}
			case metricdata.Gauge[float64]:
				for _, p := range d.DataPoints {
					out[key(m.Name, p.Attributes)] = p.Value
				}
			case metricdata.Histogram[float64]:
				for _, p := range d.DataPoints {
					out[key(m.Name, p.Attributes)] = p.Sum
				}
			}
		}
	}
	return out
}

func TestToolCallsAreCountedInFlightAndOnCompletion(t *testing.T) {
	tel, reader, clock := newToolMetrics(t)
	ctx := context.Background()
	first := tel.begin(ctx, toolKindMCP, toolPathWorker)
	*clock = clock.Add(30 * time.Second)
	second := tel.begin(ctx, toolKindMCP, toolPathWorker)
	skill := tel.begin(ctx, toolKindSkill, toolPathWorker)
	*clock = clock.Add(15 * time.Second)

	got := toolPoints(t, reader)
	if got[kobs.ToolInFlight+" mcp/worker"] != 2 || got[kobs.ToolInFlight+" skill/worker"] != 1 {
		t.Fatalf("in flight %v", got)
	}
	if got[kobs.ToolOldestInFlight+" mcp/worker"] != 45 || got[kobs.ToolOldestInFlight+" skill/worker"] != 15 {
		t.Fatalf("oldest %v", got)
	}
	if _, ok := got[kobs.ToolOldestInFlight+" openapi/worker"]; ok {
		t.Fatalf("a kind never called reports an age: %v", got)
	}

	first.answered(true)
	first.end(ctx, nil)
	second.answered(false)
	second.end(ctx, nil)
	skill.end(ctx, context.Canceled)

	got = toolPoints(t, reader)
	if got[kobs.ToolInFlight+" mcp/worker"] != 0 || got[kobs.ToolOldestInFlight+" mcp/worker"] != 0 {
		t.Fatalf("after the calls ended %v", got)
	}
	want := map[string]float64{
		kobs.ToolCalls + " mcp/worker/ok":                 1,
		kobs.ToolCalls + " mcp/worker/tool_error":         1,
		kobs.ToolCalls + " skill/worker/cancelled":        1,
		kobs.ToolCallDuration + " mcp/worker/ok":          45,
		kobs.ToolCallDuration + " mcp/worker/tool_error":  15,
		kobs.ToolCallDuration + " skill/worker/cancelled": 15,
		kobs.ToolOldestInFlight + " skill/worker":         0,
		kobs.ToolInFlight + " skill/worker":               0,
	}
	for k, v := range want {
		if got[k] != v {
			t.Errorf("%s = %v, want %v", k, got[k], v)
		}
	}
}

func TestAnOutcomeSetFirstIsKept(t *testing.T) {
	tel, reader, _ := newToolMetrics(t)
	ctx := context.Background()
	held := tel.begin(ctx, toolKindOpenAPI, toolPathWorker)
	held.set(toolOutcomeHeld)
	held.answered(true)
	held.end(ctx, nil)
	failed := tel.begin(ctx, toolKindOpenAPI, toolPathWorker)
	failed.failed(context.DeadlineExceeded)
	failed.answered(false)
	failed.end(ctx, errors.New("ledger"))
	var none *ToolTelemetry
	none.begin(ctx, toolKindMCP, toolPathWorker).end(ctx, nil)

	got := toolPoints(t, reader)
	if got[kobs.ToolCalls+" openapi/worker/held"] != 1 || got[kobs.ToolCalls+" openapi/worker/timeout"] != 1 || len(got) != 6 {
		t.Fatalf("points %v", got)
	}
}

type timeoutErr struct{}

func (timeoutErr) Error() string { return "i/o timeout" }
func (timeoutErr) Timeout() bool { return true }

func TestFailureOutcome(t *testing.T) {
	for err, want := range map[error]string{
		context.Canceled:                         toolOutcomeCancelled,
		fmt.Errorf("call: %w", context.Canceled): toolOutcomeCancelled,
		context.DeadlineExceeded:                 toolOutcomeTimeout,
		fmt.Errorf("dial: %w", timeoutErr{}):     toolOutcomeTimeout,
		errors.New("connection refused"):         toolOutcomeTransportError,
	} {
		if got := toolFailureOutcome(err); got != want {
			t.Errorf("%v: %s, want %s", err, got, want)
		}
	}
}

func TestToolKindOfABinding(t *testing.T) {
	code := func(ns string) api.ToolBinding {
		return api.ToolBinding{Source: "code", Code: &api.CodeBinding{Namespace: ns, Method: "m"}}
	}
	for _, c := range []struct {
		b    api.ToolBinding
		want string
	}{
		{api.ToolBinding{Source: "mcp", MCP: &api.MCPBinding{InstanceID: "i"}}, toolKindMCP},
		{api.ToolBinding{Source: "openapi", OpenAPI: &api.OpenAPIBinding{ConnectionID: "c"}}, toolKindOpenAPI},
		{api.ToolBinding{Source: "remote_agent", RemoteAgent: &api.RemoteAgentBinding{AgentName: "a"}}, toolKindDelegation},
		{code(shellToolset), toolKindBuiltin},
		{code(filesToolset), toolKindBuiltin},
		{code(webToolset), toolKindBuiltin},
		{code(contextToolset), toolKindBuiltin},
		{code(mediaToolset), toolKindBuiltin},
		{code("agentarea/projects"), toolKindPlatform},
		{api.ToolBinding{Source: "code"}, toolKindBuiltin},
		{api.ToolBinding{}, toolKindBuiltin},
	} {
		if got := toolKind(c.b); got != c.want {
			t.Errorf("%+v: %s, want %s", c.b, got, c.want)
		}
	}
}

func TestSkillActivationOutcome(t *testing.T) {
	unreachable := &UnreachableError{Service: "Object storage", Err: context.DeadlineExceeded}
	for _, c := range []struct {
		err  error
		want string
	}{
		{nil, toolOutcomeOK},
		{nonRetryable("SkillActivationRefused", "no", nil), toolOutcomeDenied},
		{nonRetryable("SkillNotFound", "gone", nil), toolOutcomeToolError},
		{nonRetryable("SkillActivationFailed", "bad", errors.New("x")), toolOutcomeToolError},
		{&durable.ApplicationError{Type: "ServiceUnreachable", Cause: unreachable}, toolOutcomeTimeout},
		{&durable.ApplicationError{Type: "ServiceUnreachable", Cause: &UnreachableError{Service: "db", Err: errors.New("refused")}}, toolOutcomeTransportError},
		{context.Canceled, toolOutcomeCancelled},
		{errors.New("activating a skill needs the skill packages port"), toolOutcomeToolError},
	} {
		if got := skillOutcome(c.err); got != c.want {
			t.Errorf("%v: %s, want %s", c.err, got, c.want)
		}
	}
}

type scriptedCaller struct {
	out ToolOutput
	err error
}

func (c scriptedCaller) Call(context.Context, ToolInvocation) (ToolOutput, error) {
	return c.out, c.err
}

func TestExecuteToolRecordsTheCallsOutcome(t *testing.T) {
	yes := true
	mcp := api.ToolBinding{Source: "mcp", MCP: &api.MCPBinding{InstanceID: "i1", RawName: "search"}, PolicyNames: []string{"mcp:i1:search"}}
	cases := []struct {
		name    string
		policy  api.Policy
		granted bool
		caller  scriptedCaller
		cancel  bool
		want    string
	}{
		{name: "answered", caller: scriptedCaller{out: ToolOutput{Success: true, Result: "ok"}}, want: toolOutcomeOK},
		{name: "answered an error", caller: scriptedCaller{out: ToolOutput{Result: "no", Error: "no"}}, want: toolOutcomeToolError},
		{name: "raised", caller: scriptedCaller{err: errors.New("connection reset")}, want: toolOutcomeTransportError},
		{name: "timed out", caller: scriptedCaller{err: fmt.Errorf("post: %w", timeoutErr{})}, want: toolOutcomeTimeout},
		{name: "cancelled", caller: scriptedCaller{err: context.Canceled}, cancel: true, want: toolOutcomeCancelled},
		{name: "denied", policy: api.Policy{Tools: &api.ToolsPolicy{Denied: []string{"search"}}}, want: toolOutcomeDenied},
		{name: "held", policy: api.Policy{Approval: &api.ApprovalPolicy{RequiresHumanApproval: &yes}}, want: toolOutcomeHeld},
		{name: "approved", policy: api.Policy{Approval: &api.ApprovalPolicy{RequiresHumanApproval: &yes}}, granted: true,
			caller: scriptedCaller{out: ToolOutput{Success: true}}, want: toolOutcomeOK},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			tel, reader, _ := newToolMetrics(t)
			s := New(Deps{Pricing: eurPricing{}, Tools: map[string]ToolCaller{"mcp": c.caller}, ToolMetrics: tel, Log: quiet()})
			ctx, cancel := context.WithCancel(context.Background())
			if c.cancel {
				cancel()
			}
			defer cancel()
			_, _ = s.ExecuteTool(ctx, testPrincipal(), ToolCall{
				TaskID: "t1", ToolCallID: "c1", ToolName: "search", Binding: mcp, Policy: c.policy, PolicyApprovalGranted: c.granted,
			})
			got := toolPoints(t, reader)
			if got[kobs.ToolCalls+" mcp/worker/"+c.want] != 1 || got[kobs.ToolInFlight+" mcp/worker"] != 0 {
				t.Fatalf("points %v", got)
			}
		})
	}
}
