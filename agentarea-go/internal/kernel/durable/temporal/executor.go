package temporal

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	commonpb "go.temporal.io/api/common/v1"
	enumspb "go.temporal.io/api/enums/v1"
	"go.temporal.io/api/serviceerror"
	taskqueuepb "go.temporal.io/api/taskqueue/v1"
	"go.temporal.io/api/workflowservice/v1"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/converter"
	"go.temporal.io/sdk/temporal"
	"google.golang.org/protobuf/types/known/durationpb"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/durable"
)

// Workflow retry defaults (workflow/executor.py:46-48).
const (
	defaultRetryAttempts = 3
	defaultRetryInitial  = 30 * time.Second
	defaultRetryMax      = 10 * time.Minute
)

func retryPolicy(o durable.StartOptions) *temporal.RetryPolicy {
	p := &temporal.RetryPolicy{
		MaximumAttempts: int32(o.RetryAttempts),
		InitialInterval: o.RetryInitial,
		MaximumInterval: o.RetryMax,
	}
	if p.MaximumAttempts == 0 {
		p.MaximumAttempts = defaultRetryAttempts
	}
	if p.InitialInterval == 0 {
		p.InitialInterval = defaultRetryInitial
	}
	if p.MaximumInterval == 0 {
		p.MaximumInterval = defaultRetryMax
	}
	return p
}

func reusePolicy(o durable.StartOptions) enumspb.WorkflowIdReusePolicy {
	if o.StartOnce {
		return enumspb.WORKFLOW_ID_REUSE_POLICY_REJECT_DUPLICATE
	}
	return enumspb.WORKFLOW_ID_REUSE_POLICY_ALLOW_DUPLICATE
}

// Start starts workflow (temporal_executor.py:172). With StartSignal it is a
// signal-with-start whose signal carries every StartSignalArgs value as its
// own argument.
func (c *Client) Start(ctx context.Context, workflow, workflowID string, args []any, o durable.StartOptions) (string, error) {
	if o.TaskQueue == "" {
		return "", errors.New("start workflow: task queue is required")
	}
	var err error
	if o.StartSignal != "" {
		err = c.signalWithStart(ctx, workflow, workflowID, args, o)
	} else {
		_, err = c.sdk.ExecuteWorkflow(ctx, client.StartWorkflowOptions{
			ID:                                       workflowID,
			TaskQueue:                                o.TaskQueue,
			WorkflowExecutionTimeout:                 o.Timeout,
			RetryPolicy:                              retryPolicy(o),
			StartDelay:                               o.StartDelay,
			WorkflowIDReusePolicy:                    reusePolicy(o),
			WorkflowExecutionErrorWhenAlreadyStarted: true,
		}, workflow, args...)
	}
	if err != nil {
		if _, ok := errors.AsType[*serviceerror.WorkflowExecutionAlreadyStarted](err); ok {
			return "", fmt.Errorf("start %s %s: %w", workflow, workflowID, durable.ErrAlreadyStarted)
		}
		return "", fmt.Errorf("start %s %s: %w", workflow, workflowID, err)
	}
	return workflowID, nil
}

func (c *Client) signalWithStart(ctx context.Context, workflow, workflowID string, args []any, o durable.StartOptions) error {
	dc := converter.GetDefaultDataConverter()
	input, err := dc.ToPayloads(args...)
	if err != nil {
		return err
	}
	signalInput, err := dc.ToPayloads(o.StartSignalArgs...)
	if err != nil {
		return err
	}
	rp := retryPolicy(o)
	req := &workflowservice.SignalWithStartWorkflowExecutionRequest{
		Namespace:             c.namespace,
		WorkflowId:            workflowID,
		WorkflowType:          &commonpb.WorkflowType{Name: workflow},
		TaskQueue:             &taskqueuepb.TaskQueue{Name: o.TaskQueue, Kind: enumspb.TASK_QUEUE_KIND_NORMAL},
		Input:                 input,
		SignalName:            o.StartSignal,
		SignalInput:           signalInput,
		Identity:              c.identity,
		RequestId:             uuid.NewString(),
		WorkflowIdReusePolicy: reusePolicy(o),
		RetryPolicy: &commonpb.RetryPolicy{
			MaximumAttempts:    rp.MaximumAttempts,
			InitialInterval:    durationpb.New(rp.InitialInterval),
			MaximumInterval:    durationpb.New(rp.MaximumInterval),
			BackoffCoefficient: 2,
		},
	}
	if o.Timeout > 0 {
		req.WorkflowExecutionTimeout = durationpb.New(o.Timeout)
	}
	if o.StartDelay > 0 {
		req.WorkflowStartDelay = durationpb.New(o.StartDelay)
	}
	_, err = c.sdk.WorkflowService().SignalWithStartWorkflowExecution(ctx, req)
	return err
}

func statusOf(s enumspb.WorkflowExecutionStatus) durable.Status {
	switch s {
	case enumspb.WORKFLOW_EXECUTION_STATUS_RUNNING:
		return durable.StatusRunning
	case enumspb.WORKFLOW_EXECUTION_STATUS_COMPLETED:
		return durable.StatusCompleted
	case enumspb.WORKFLOW_EXECUTION_STATUS_FAILED:
		return durable.StatusFailed
	case enumspb.WORKFLOW_EXECUTION_STATUS_CANCELED:
		return durable.StatusCancelled
	case enumspb.WORKFLOW_EXECUTION_STATUS_TERMINATED:
		return durable.StatusTerminated
	case enumspb.WORKFLOW_EXECUTION_STATUS_UNSPECIFIED, enumspb.WORKFLOW_EXECUTION_STATUS_CONTINUED_AS_NEW,
		enumspb.WORKFLOW_EXECUTION_STATUS_TIMED_OUT, enumspb.WORKFLOW_EXECUTION_STATUS_PAUSED:
		return durable.StatusUnknown
	}
	return durable.StatusUnknown
}

func isNotFound(err error) bool {
	_, ok := errors.AsType[*serviceerror.NotFound](err)
	return ok
}

// Status describes the workflow and, once completed, reads its result
// (temporal_executor.py:274).
func (c *Client) Status(ctx context.Context, workflowID string) (durable.Result, error) {
	r := durable.Result{WorkflowID: workflowID}
	desc, err := c.sdk.DescribeWorkflow(ctx, workflowID, "")
	if isNotFound(err) {
		r.Status, r.Error = durable.StatusUnknown, "Workflow not found"
		return r, nil
	}
	if err != nil {
		return r, fmt.Errorf("describe workflow %s: %w", workflowID, err)
	}
	r.Status = statusOf(desc.Status)
	if !desc.WorkflowStartTime.IsZero() {
		r.StartTime = &desc.WorkflowStartTime
	}
	r.EndTime = desc.WorkflowCloseTime
	if r.Status == durable.StatusCompleted {
		var raw json.RawMessage
		if err := c.sdk.GetWorkflow(ctx, workflowID, "").Get(ctx, &raw); err != nil {
			return r, fmt.Errorf("read result of workflow %s: %w", workflowID, err)
		}
		r.Result = raw
	}
	return r, nil
}

// Cancel requests cancellation; ErrNotFound for an unknown workflow.
func (c *Client) Cancel(ctx context.Context, workflowID string) error {
	err := c.sdk.CancelWorkflow(ctx, workflowID, "")
	if isNotFound(err) {
		return fmt.Errorf("cancel workflow %s: %w", workflowID, durable.ErrNotFound)
	}
	return err
}

// Wait blocks until the workflow closes; a failed, cancelled or terminated
// workflow is a Result with Error, not an error (temporal_executor.py:363).
func (c *Client) Wait(ctx context.Context, workflowID string, timeout time.Duration) (durable.Result, error) {
	if timeout > 0 {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, timeout)
		defer cancel()
	}
	var raw json.RawMessage
	runErr := c.sdk.GetWorkflow(ctx, workflowID, "").Get(ctx, &raw)
	if runErr != nil && ctx.Err() != nil {
		return durable.Result{WorkflowID: workflowID}, fmt.Errorf("wait for workflow %s: %w", workflowID, durable.ErrWaitTimeout)
	}
	if isNotFound(runErr) {
		return durable.Result{WorkflowID: workflowID}, fmt.Errorf("wait for workflow %s: %w", workflowID, durable.ErrNotFound)
	}
	r, err := c.Status(context.WithoutCancel(ctx), workflowID)
	if err != nil {
		return r, err
	}
	if runErr != nil {
		r.Error = runErr.Error()
		return r, nil
	}
	r.Result = raw
	return r, nil
}

// Signal sends a signal with each of args as its own argument.
func (c *Client) Signal(ctx context.Context, workflowID, signal string, args ...any) error {
	var err error
	if len(args) == 1 {
		err = c.sdk.SignalWorkflow(ctx, workflowID, "", signal, args[0])
	} else {
		var input *commonpb.Payloads
		if input, err = converter.GetDefaultDataConverter().ToPayloads(args...); err != nil {
			return err
		}
		_, err = c.sdk.WorkflowService().SignalWorkflowExecution(ctx, &workflowservice.SignalWorkflowExecutionRequest{
			Namespace:         c.namespace,
			WorkflowExecution: &commonpb.WorkflowExecution{WorkflowId: workflowID},
			SignalName:        signal,
			Input:             input,
			Identity:          c.identity,
			RequestId:         uuid.NewString(),
		})
	}
	if isNotFound(err) {
		return fmt.Errorf("signal %s to %s: %w", signal, workflowID, durable.ErrNotFound)
	}
	return err
}

// Query runs a query and decodes its result into out.
func (c *Client) Query(ctx context.Context, workflowID, query string, out any, args ...any) error {
	v, err := c.sdk.QueryWorkflow(ctx, workflowID, "", query, args...)
	if isNotFound(err) {
		return fmt.Errorf("query %s on %s: %w", query, workflowID, durable.ErrNotFound)
	}
	if err != nil {
		return err
	}
	if out == nil {
		return nil
	}
	return v.Get(out)
}

// Update runs an update to completion and decodes its result into out.
func (c *Client) Update(ctx context.Context, workflowID, update string, out any, args ...any) error {
	h, err := c.sdk.UpdateWorkflow(ctx, client.UpdateWorkflowOptions{
		WorkflowID:   workflowID,
		UpdateName:   update,
		Args:         args,
		WaitForStage: client.WorkflowUpdateStageCompleted,
	})
	if isNotFound(err) {
		return fmt.Errorf("update %s on %s: %w", update, workflowID, durable.ErrNotFound)
	}
	if err != nil {
		return err
	}
	return h.Get(ctx, out)
}
