package app

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	corev1 "k8s.io/api/core/v1"

	"github.com/agentarea/agentarea/agentarea-go/ext"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/backends/artifactstore"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/backends/sandboxruntime"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/backends/warmpool"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/plane"
)

// resolveWorkloadHooks builds only the workload hooks, for a process that holds
// no database and runs nothing the other extension points serve.
func (b *Build) resolveWorkloadHooks(ctx context.Context, deps ext.Deps) (_ *extensions, err error) {
	e := &extensions{}
	for _, f := range b.ext.WorkloadHooks {
		h, err := build(ctx, e, deps, "workload hooks", f)
		if err != nil {
			return nil, errors.Join(err, e.Close())
		}
		e.WorkloadHooks = append(e.WorkloadHooks, h)
	}
	return e, nil
}

// attachWorkloads hands every overlay what the process runs, once, before it serves.
func attachWorkloads(ctx context.Context, hooks []ext.WorkloadHooks, w ext.Workloads) error {
	for i, h := range hooks {
		if h.Attach == nil {
			continue
		}
		if err := h.Attach(ctx, w); err != nil {
			return fmt.Errorf("workload hooks %d: %w", i+1, err)
		}
	}
	return nil
}

// sandboxHooks attaches the overlays' sandbox observers to the provider runtime.
// A sandbox-only process (strict) refuses a runtime it cannot observe.
func sandboxHooks(hooks []ext.WorkloadHooks, strict bool) []plane.Hook {
	var sessions sessionObservers
	var pods taskPodObservers
	for _, h := range hooks {
		if h.Sandboxes != nil {
			sessions = append(sessions, h.Sandboxes)
		}
		if h.TaskPods != nil {
			pods = append(pods, h.TaskPods)
		}
	}
	if len(sessions) == 0 && len(pods) == 0 {
		return nil
	}
	return []plane.Hook{func(rt sandboxruntime.ManagedRuntime, provider string) error {
		attached := false
		if o, ok := rt.(interface {
			SetLifecycleObserver(sandboxruntime.LifecycleObserver)
		}); ok && len(sessions) > 0 {
			o.SetLifecycleObserver(sessions)
			attached = true
		}
		if o, ok := rt.(interface {
			SetTaskLifecycleObserver(warmpool.LifecycleObserver)
		}); ok && len(pods) > 0 {
			o.SetTaskLifecycleObserver(pods)
			attached = true
		}
		if strict && !attached {
			return fmt.Errorf("sandbox provider %s (%T) exposes no lifecycle observation", provider, rt)
		}
		return nil
	}}
}

// artifactHooks attaches the overlays' publication observers to the artifact
// store and reports the store through into.
func artifactHooks(hooks []ext.WorkloadHooks, into *ext.ArtifactStorage) []func(*artifactstore.Repository) error {
	var observers []ext.ArtifactObserver
	for _, h := range hooks {
		if h.Artifacts != nil {
			observers = append(observers, h.Artifacts)
		}
	}
	return []func(*artifactstore.Repository) error{func(repo *artifactstore.Repository) error {
		*into = repo
		if len(observers) > 0 {
			repo.SetPublicationObserver(publications{repo: repo, observers: observers})
		}
		return nil
	}}
}

// publications reads each published object back from the store, so an observer
// sees its size and time as the store has them, never as the request said.
type publications struct {
	repo      *artifactstore.Repository
	observers []ext.ArtifactObserver
}

func (p publications) Published(ctx context.Context, pub artifactstore.Publication) error {
	cfg, client := p.repo.ObjectStore()
	head, err := client.HeadObject(ctx, &s3.HeadObjectInput{Bucket: aws.String(cfg.Bucket), Key: aws.String(pub.ObjectKey)})
	if err != nil {
		return fmt.Errorf("read published artifact: %w", err)
	}
	a := ext.StoredArtifact{
		WorkspaceID: pub.WorkspaceID, TaskID: pub.TaskID, Bucket: cfg.Bucket, Prefix: cfg.Prefix,
		ObjectKey: pub.ObjectKey, SizeBytes: pub.SizeBytes, HeadSize: aws.ToInt64(head.ContentLength),
		VersionID: aws.ToString(head.VersionId), ETag: aws.ToString(head.ETag), LastModified: head.LastModified,
	}
	errs := make([]error, 0, len(p.observers))
	for _, o := range p.observers {
		errs = append(errs, o.Published(ctx, a))
	}
	return errors.Join(errs...)
}

type sessionObservers []ext.SandboxObserver

func sandboxSession(s sandboxruntime.SessionSnapshot) ext.SandboxSession {
	return ext.SandboxSession{Provider: s.Provider, ID: s.ID, WorkspaceID: s.WorkspaceID, TaskID: s.TaskID,
		CreatedAt: s.CreatedAt, ExpiresAt: s.ExpiresAt, CreatedAtSource: s.CreatedAtSource, Resources: s.Resources}
}

func sandboxDelete(a sandboxruntime.DeleteAttempt) ext.SandboxDelete {
	return ext.SandboxDelete{Session: sandboxSession(a.Session), OperationID: a.OperationID, Reason: a.Reason, RequestedAt: a.RequestedAt}
}

func (o sessionObservers) each(f func(ext.SandboxObserver) error) error {
	errs := make([]error, 0, len(o))
	for _, x := range o {
		errs = append(errs, f(x))
	}
	return errors.Join(errs...)
}

func (o sessionObservers) Allocation(ctx context.Context, s sandboxruntime.SessionSnapshot) error {
	return o.each(func(x ext.SandboxObserver) error { return x.Allocation(ctx, sandboxSession(s)) })
}

func (o sessionObservers) LeaseRenewed(ctx context.Context, s sandboxruntime.SessionSnapshot, state string, at time.Time) error {
	return o.each(func(x ext.SandboxObserver) error { return x.LeaseRenewed(ctx, sandboxSession(s), state, at) })
}

func (o sessionObservers) Missing(ctx context.Context, s sandboxruntime.SessionSnapshot) error {
	return o.each(func(x ext.SandboxObserver) error { return x.Missing(ctx, sandboxSession(s)) })
}

func (o sessionObservers) Provisioning(ctx context.Context, p sandboxruntime.ProvisioningObservation) error {
	e := ext.SandboxProvisioning{Provider: p.Intent.Provider, ProvisioningID: p.Intent.ProvisioningID,
		WorkspaceID: p.Intent.WorkspaceID, TaskID: p.Intent.TaskID, Phase: string(p.Phase),
		RequestedAt: p.RequestedAt, RespondedAt: p.RespondedAt}
	return o.each(func(x ext.SandboxObserver) error { return x.Provisioning(ctx, e) })
}

func (o sessionObservers) BeforeDelete(ctx context.Context, a sandboxruntime.DeleteAttempt) error {
	return o.each(func(x ext.SandboxObserver) error { return x.BeforeDelete(ctx, sandboxDelete(a)) })
}

func (o sessionObservers) AfterDelete(ctx context.Context, r sandboxruntime.DeleteResult) error {
	e := ext.SandboxDeleteResult{Attempt: sandboxDelete(r.Attempt), Outcome: string(r.Outcome), RespondedAt: r.RespondedAt}
	return o.each(func(x ext.SandboxObserver) error { return x.AfterDelete(ctx, e) })
}

type taskPodObservers []ext.TaskPodObserver

func quantities(l corev1.ResourceList) map[string]string {
	if l == nil {
		return nil
	}
	out := make(map[string]string, len(l))
	for name, q := range l {
		out[string(name)] = q.String()
	}
	return out
}

func containerResources(cs []warmpool.ContainerAllocation) []ext.ContainerResources {
	out := make([]ext.ContainerResources, 0, len(cs))
	for _, c := range cs {
		out = append(out, ext.ContainerResources{Name: c.Name, Resources: ext.ResourceRequirements{
			Limits: quantities(c.Resources.Limits), Requests: quantities(c.Resources.Requests)}})
	}
	return out
}

func taskPod(p warmpool.TaskPodSnapshot) ext.TaskPod {
	return ext.TaskPod{Namespace: p.Namespace, Name: p.Name, UID: p.UID, WorkspaceID: p.WorkspaceID, TaskID: p.TaskID,
		State: p.State, AssignedAt: p.AssignedAt, LeaseUntil: p.LeaseUntil, CleanupAt: p.CleanupAt,
		Containers: containerResources(p.Containers), InitContainers: containerResources(p.InitContainers),
		Overhead: quantities(p.Overhead)}
}

func taskPodDelete(a warmpool.DeleteAttempt) ext.TaskPodDelete {
	return ext.TaskPodDelete{Pod: taskPod(a.Pod), OperationID: a.OperationID, Reason: a.Reason, RequestedAt: a.RequestedAt}
}

func (o taskPodObservers) each(f func(ext.TaskPodObserver) error) error {
	errs := make([]error, 0, len(o))
	for _, x := range o {
		errs = append(errs, f(x))
	}
	return errors.Join(errs...)
}

func (o taskPodObservers) Allocation(ctx context.Context, p warmpool.TaskPodSnapshot) error {
	return o.each(func(x ext.TaskPodObserver) error { return x.Allocation(ctx, taskPod(p)) })
}

func (o taskPodObservers) Lease(ctx context.Context, p warmpool.TaskPodSnapshot) error {
	return o.each(func(x ext.TaskPodObserver) error { return x.Lease(ctx, taskPod(p)) })
}

func (o taskPodObservers) BeforeDelete(ctx context.Context, a warmpool.DeleteAttempt) error {
	return o.each(func(x ext.TaskPodObserver) error { return x.BeforeDelete(ctx, taskPodDelete(a)) })
}

func (o taskPodObservers) AfterDelete(ctx context.Context, r warmpool.DeleteResult) error {
	e := ext.TaskPodDeleteResult{Attempt: taskPodDelete(r.Attempt), Outcome: string(r.Outcome), RespondedAt: r.RespondedAt}
	return o.each(func(x ext.TaskPodObserver) error { return x.AfterDelete(ctx, e) })
}
