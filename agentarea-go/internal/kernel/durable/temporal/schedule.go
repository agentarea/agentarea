package temporal

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"

	commonpb "go.temporal.io/api/common/v1"
	enumspb "go.temporal.io/api/enums/v1"
	"go.temporal.io/api/serviceerror"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/converter"
	"go.temporal.io/sdk/temporal"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/durable"
)

func overlapPolicy(o durable.Overlap) (enumspb.ScheduleOverlapPolicy, bool) {
	switch o {
	case "":
		return enumspb.SCHEDULE_OVERLAP_POLICY_UNSPECIFIED, true
	case durable.OverlapSkip:
		return enumspb.SCHEDULE_OVERLAP_POLICY_SKIP, true
	case durable.OverlapBufferOne:
		return enumspb.SCHEDULE_OVERLAP_POLICY_BUFFER_ONE, true
	case durable.OverlapBufferAll:
		return enumspb.SCHEDULE_OVERLAP_POLICY_BUFFER_ALL, true
	case durable.OverlapCancel:
		return enumspb.SCHEDULE_OVERLAP_POLICY_CANCEL_OTHER, true
	case durable.OverlapTerminate:
		return enumspb.SCHEDULE_OVERLAP_POLICY_TERMINATE_OTHER, true
	case durable.OverlapAllowAll:
		return enumspb.SCHEDULE_OVERLAP_POLICY_ALLOW_ALL, true
	}
	return 0, false
}

func scheduleParts(s durable.Schedule) (client.ScheduleSpec, *client.ScheduleWorkflowAction, enumspb.ScheduleOverlapPolicy, error) {
	overlap, ok := overlapPolicy(s.Overlap)
	if !ok {
		return client.ScheduleSpec{}, nil, 0, fmt.Errorf("schedule %s: unknown overlap policy %q", s.ID, s.Overlap)
	}
	if s.TaskQueue == "" || s.Workflow == "" || s.WorkflowID == "" {
		return client.ScheduleSpec{}, nil, 0, fmt.Errorf("schedule %s: workflow, workflow id and task queue are required", s.ID)
	}
	spec := client.ScheduleSpec{CronExpressions: s.Cron, TimeZoneName: s.TimeZone}
	for _, every := range s.Every {
		spec.Intervals = append(spec.Intervals, client.ScheduleIntervalSpec{Every: every})
	}
	action := &client.ScheduleWorkflowAction{ID: s.WorkflowID, Workflow: s.Workflow, Args: s.Args, TaskQueue: s.TaskQueue}
	return spec, action, overlap, nil
}

// Ensure creates the schedule, or replaces an existing one with s
// (ensure_undispatched_task_schedule, ensure_cron_schedule_sync_schedule).
func (c *Client) Ensure(ctx context.Context, s durable.Schedule) error {
	spec, action, overlap, err := scheduleParts(s)
	if err != nil {
		return err
	}
	_, err = c.sdk.ScheduleClient().Create(ctx, client.ScheduleOptions{
		ID:            s.ID,
		Spec:          spec,
		Action:        action,
		Overlap:       overlap,
		CatchupWindow: s.CatchupWindow,
		Paused:        s.Paused,
		Note:          s.Note,
	})
	if !errors.Is(err, temporal.ErrScheduleAlreadyRunning) {
		if err != nil {
			return fmt.Errorf("create schedule %s: %w", s.ID, err)
		}
		return nil
	}
	err = c.sdk.ScheduleClient().GetHandle(ctx, s.ID).Update(ctx, client.ScheduleUpdateOptions{
		DoUpdate: func(client.ScheduleUpdateInput) (*client.ScheduleUpdate, error) {
			return &client.ScheduleUpdate{Schedule: &client.Schedule{
				Action: action,
				Spec:   &spec,
				Policy: &client.SchedulePolicies{Overlap: overlap, CatchupWindow: s.CatchupWindow},
				State:  &client.ScheduleState{Note: s.Note, Paused: s.Paused},
			}}, nil
		},
	})
	if err != nil {
		return fmt.Errorf("update schedule %s: %w", s.ID, err)
	}
	return nil
}

// Describe reads a schedule; ErrNotFound when it does not exist.
func (c *Client) Describe(ctx context.Context, id string) (durable.ScheduleInfo, error) {
	d, err := c.sdk.ScheduleClient().GetHandle(ctx, id).Describe(ctx)
	if _, ok := errors.AsType[*serviceerror.NotFound](err); ok {
		return durable.ScheduleInfo{}, fmt.Errorf("schedule %s: %w", id, durable.ErrNotFound)
	}
	if err != nil {
		return durable.ScheduleInfo{}, fmt.Errorf("describe schedule %s: %w", id, err)
	}
	info := durable.ScheduleInfo{ID: id, NextActions: d.Info.NextActionTimes}
	if a, ok := d.Schedule.Action.(*client.ScheduleWorkflowAction); ok {
		info.WorkflowID, info.TaskQueue = a.ID, a.TaskQueue
		if name, ok := a.Workflow.(string); ok {
			info.Workflow = name
		}
		for _, arg := range a.Args {
			raw, err := rawArg(arg)
			if err != nil {
				return durable.ScheduleInfo{}, fmt.Errorf("schedule %s argument: %w", id, err)
			}
			info.Args = append(info.Args, raw)
		}
	}
	if spec := d.Schedule.Spec; spec != nil {
		info.Cron, info.TimeZone = spec.CronExpressions, spec.TimeZoneName
		for _, iv := range spec.Intervals {
			info.Every = append(info.Every, iv.Every)
		}
	}
	if p := d.Schedule.Policy; p != nil {
		info.CatchupWindow = p.CatchupWindow
	}
	if st := d.Schedule.State; st != nil {
		info.Paused, info.Note = st.Paused, st.Note
	}
	for _, ra := range d.Info.RecentActions {
		action := durable.ScheduleAction{ScheduledTime: ra.ScheduleTime, ActualTime: ra.ActualTime}
		if r := ra.StartWorkflowResult; r != nil {
			action.WorkflowID, action.RunID = r.WorkflowID, r.FirstExecutionRunID
		}
		info.RecentActions = append(info.RecentActions, action)
	}
	return info, nil
}

// rawArg is a described action argument as JSON.
func rawArg(arg any) (json.RawMessage, error) {
	p, ok := arg.(*commonpb.Payload)
	if !ok {
		return nil, fmt.Errorf("unexpected %T", arg)
	}
	switch enc := string(p.GetMetadata()[converter.MetadataEncoding]); enc {
	case converter.MetadataEncodingJSON:
		return json.RawMessage(p.GetData()), nil
	case converter.MetadataEncodingNil:
		return json.RawMessage("null"), nil
	default:
		return nil, fmt.Errorf("payload encoding %q is not JSON", enc)
	}
}

// Delete removes a schedule; ErrNotFound when it does not exist.
func (c *Client) Delete(ctx context.Context, id string) error {
	err := c.sdk.ScheduleClient().GetHandle(ctx, id).Delete(ctx)
	if _, ok := errors.AsType[*serviceerror.NotFound](err); ok {
		return fmt.Errorf("schedule %s: %w", id, durable.ErrNotFound)
	}
	return err
}
