package service

import (
	"context"
	"errors"
	"net/http"
	"sync"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/store"
)

// The container monitor (container_monitor.py).
const (
	monitorTick = 30 * time.Second
	// orphanThreshold exceeds the longest a healthy verification runs, so
	// only rows a dead process left in_progress are reaped.
	orphanThreshold       = 12 * time.Minute
	maxConcurrentVerifies = 5
	neverAttemptedBatch   = 500
	packageImportsPerTick = 3
	// packageCandidateScan bounds the rows read to find the npx/uvx ones:
	// the effective command needs the spec, which is catalog's table.
	packageCandidateScan = 200
	packageRetryAfter    = time.Hour
	packageImportTimeout = 20 * time.Minute
)

// RunMonitor ticks every 30 s until ctx ends: reap orphaned in_progress
// verifications, verify never_attempted container and platform-managed
// instances (5 at a time), import verified npx/uvx command instances into
// package images (3 per tick, one after another).
func (s *Service) RunMonitor(ctx context.Context) error {
	var wg sync.WaitGroup
	sem := make(chan struct{}, maxConcurrentVerifies)
	defer wg.Wait()
	t := time.NewTicker(monitorTick)
	defer t.Stop()
	for {
		if err := s.MonitorTick(ctx, &wg, sem); err != nil && ctx.Err() == nil {
			s.d.Log.Error("MCP container monitor tick failed", "error", err)
		}
		select {
		case <-ctx.Done():
			return nil
		case <-t.C:
		}
	}
}

// MonitorTick is one sweep; verifications run in wg, bounded by sem.
func (s *Service) MonitorTick(ctx context.Context, wg *sync.WaitGroup, sem chan struct{}) error {
	interrupted := s.payload(domain.VerifyFailed, failure(CodeInterrupted, "Verification timed out — click Verify to retry.", nil))
	var pending []store.Pending
	var candidates []store.ImportRow
	err := s.d.DB.Global().Write(ctx, func(ctx context.Context, q db.Querier) error {
		reaped, err := s.d.Instances.InterruptStale(ctx, q, interrupted, s.d.Now().Add(-orphanThreshold))
		if err != nil {
			return err
		}
		if reaped > 0 {
			s.d.Log.Info("orphan gc: rows reaped", "reaped", reaped)
		}
		if pending, err = s.d.Instances.NeverAttempted(ctx, q, neverAttemptedBatch); err != nil {
			return err
		}
		candidates, err = s.d.Instances.PackageImportCandidates(ctx, q, s.d.Now().Add(-packageRetryAfter), packageCandidateScan)
		return err
	})
	if err != nil {
		return err
	}
	for _, p := range pending {
		select {
		case sem <- struct{}{}:
		case <-ctx.Done():
			return nil
		}
		wg.Add(1)
		go func(p store.Pending) {
			defer wg.Done()
			defer func() { <-sem }()
			if err := s.sweepVerify(ctx, p); err != nil {
				s.d.Log.Error("verify raised for instance", "instance_id", p.ID, "error", err)
			}
		}(p)
	}
	s.d.Log.Info("verify sweep: rows enqueued", "enqueued", len(pending))
	attempted := 0
	for _, c := range candidates {
		if attempted == packageImportsPerTick || ctx.Err() != nil {
			break
		}
		ok, err := s.importCandidate(ctx, c)
		if err != nil {
			s.d.Log.Error("package import raised for instance", "instance_id", c.ID, "error", err)
		}
		if ok || err != nil {
			attempted++
		}
	}
	s.d.Log.Info("package import sweep: rows attempted", "attempted", attempted)
	return nil
}

// sweepVerify verifies one never_attempted row in its workspace; a
// platform-managed url row sends the platform's credential headers.
func (s *Service) sweepVerify(ctx context.Context, p store.Pending) error {
	ws, err := scope.NewWorkspace(p.WorkspaceID, "")
	if err != nil {
		return err
	}
	var extra http.Header
	if p.ManagedBy != nil && *p.ManagedBy == domain.ManagedByPlatform {
		inst, err := s.instanceIn(ctx, ws, p.ID)
		if err != nil {
			return err
		}
		if inst.Transport == domain.TransportURL {
			creds, err := s.instanceSecrets(ctx, inst, inst.EnvVars())
			if err != nil {
				return err
			}
			if len(creds) > 0 {
				extra = http.Header{}
				for k, v := range creds {
					extra.Set(k, v)
				}
			}
		}
	}
	_, err = s.verifyRow(ctx, ws, p.ID, extra, false)
	return err
}

// effectiveCommand is the command a command instance runs: its own, its
// spec's json_spec command, the spec's cmd[0].
func effectiveCommand(inst map[string]any, specJSON map[string]any, cmd []any) string {
	if v, ok := inst["command"].(string); ok && v != "" {
		return v
	}
	if v, ok := specJSON["command"].(string); ok && v != "" {
		return v
	}
	if len(cmd) > 0 {
		if v, ok := cmd[0].(string); ok {
			return v
		}
	}
	return ""
}

// importCandidate imports c when its effective command is npx or uvx;
// false when it is not one.
func (s *Service) importCandidate(ctx context.Context, c store.ImportRow) (bool, error) {
	ws, err := scope.NewWorkspace(c.WorkspaceID, "")
	if err != nil {
		return false, err
	}
	spec, ok, err := s.serverSpec(ctx, ws, domain.Instance{ServerSpecID: c.ServerSpecID, ManagedBy: c.ManagedBy})
	if err != nil {
		return false, err
	}
	if !ok {
		return false, nil
	}
	if cmd := effectiveCommand(c.JSONSpec, spec.JSONSpec, spec.Cmd); cmd != "npx" && cmd != "uvx" {
		return false, nil
	}
	return true, s.ImportPackage(ctx, c.ID)
}

// ImportPackage is import_package_image: one verified command instance
// becomes a docker instance on the image the runtime built for its package.
// A rejected or unavailable import is recorded in json_spec.package_import;
// an instance edited meanwhile is left for the next sweep.
func (s *Service) ImportPackage(ctx context.Context, id uuid.UUID) error {
	if s.d.Runtime == nil {
		return errNoRuntime
	}
	var source, effective map[string]any
	err := s.d.DB.Global().Write(ctx, func(ctx context.Context, q db.Querier) error {
		row, ok, err := s.d.Instances.LockForImport(ctx, q, id)
		if err != nil {
			return err
		}
		if !ok {
			return &domain.NotFound{Msg: "MCP instance " + id.String() + " not found"}
		}
		ws, err := scope.NewWorkspace(row.WorkspaceID, "")
		if err != nil {
			return err
		}
		inst := domain.Instance{ID: id.String(), ServerSpecID: row.ServerSpecID, Transport: row.Transport,
			JSONSpec: row.JSONSpec, ManagedBy: row.ManagedBy}
		spec, found, err := s.serverSpec(ctx, ws, inst)
		if err != nil {
			return err
		}
		if !found {
			return &domain.NotFound{Msg: "MCP server spec " + row.ServerSpecID + " not found"}
		}
		source, effective = row.JSONSpec, transportSpec(spec, inst)
		return nil
	})
	if err != nil {
		return err
	}
	ictx, cancel := context.WithTimeout(ctx, packageImportTimeout)
	imported, err := s.d.Runtime.ImportPackage(ictx, id.String())
	cancel()
	if err != nil {
		status := "unavailable"
		var rejected *PackageRejectedError
		if errors.As(err, &rejected) {
			status = "rejected"
		}
		return s.recordImport(ctx, id, source, status, err.Error())
	}
	if imported.Image == "" {
		return errors.New("MCP package import result has no image")
	}
	if imported.Package == nil {
		return errors.New("MCP package import result package must be an object")
	}
	args, ok := effective["args"].([]any)
	if _, has := effective["args"]; !has {
		args, ok = []any{}, true
	}
	if !ok {
		return &domain.Invalid{Msg: "Command instance args must be a list before package import"}
	}
	converted := map[string]any{}
	for k, v := range source {
		switch k {
		case "command", "args", "cmd", "type", "package_import":
		default:
			converted[k] = v
		}
	}
	command := make([]any, 0, len(imported.Command))
	for _, c := range imported.Command {
		command = append(command, c)
	}
	converted["image"] = imported.Image
	converted["port"] = imported.Port
	converted["command"] = command
	converted["package"] = imported.Package
	converted["source"] = map[string]any{"type": "command", "command": effective["command"], "args": args}
	return s.d.DB.Global().Write(ctx, func(ctx context.Context, q db.Querier) error {
		row, ok, err := s.d.Instances.LockForImport(ctx, q, id)
		if err != nil {
			return err
		}
		if !ok {
			return &domain.NotFound{Msg: "MCP instance " + id.String() + " not found"}
		}
		if !sameJSON(row.JSONSpec, source) {
			return nil
		}
		if err := s.d.Runtime.Retire(ctx, id.String()); err != nil {
			return err
		}
		return s.d.Instances.SetImportedSpec(ctx, q, id, converted, domain.TransportDocker, s.d.Now())
	})
}

// recordImport writes a rejected or unavailable attempt, unless the
// instance was edited while the image was built.
func (s *Service) recordImport(ctx context.Context, id uuid.UUID, source map[string]any, status, msg string) error {
	return s.d.DB.Global().Write(ctx, func(ctx context.Context, q db.Querier) error {
		row, ok, err := s.d.Instances.LockForImport(ctx, q, id)
		if err != nil {
			return err
		}
		if !ok {
			return &domain.NotFound{Msg: "MCP instance " + id.String() + " not found"}
		}
		if !sameJSON(row.JSONSpec, source) {
			return nil
		}
		updated := map[string]any{}
		for k, v := range source {
			updated[k] = v
		}
		updated["package_import"] = map[string]any{"status": status, "error": msg,
			"at": s.d.Now().UTC().Format("2006-01-02T15:04:05.999999-07:00")}
		return s.d.Instances.SetImportedSpec(ctx, q, id, updated, row.Transport, s.d.Now())
	})
}
