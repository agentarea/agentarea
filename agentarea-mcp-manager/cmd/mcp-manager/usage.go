package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log/slog"
	"time"

	"github.com/agentarea/mcp-manager/internal/artifactstore"
	"github.com/agentarea/mcp-manager/internal/usage"
	"github.com/google/uuid"
)

func runRuntimeUsage(ctx context.Context, sampler usage.Sampler, recorder usage.Recorder, interval time.Duration, logger *slog.Logger) {
	runUsageCollection(ctx, interval, logger, "runtime", func(sampleCtx context.Context) error {
		samples, err := sampler.SampleUsage(sampleCtx)
		if err != nil {
			return err
		}
		for _, sample := range samples {
			data, err := json.Marshal(sample)
			if err != nil {
				return err
			}
			event := usage.Event{
				SchemaVersion: usage.SchemaVersion,
				ID:            uuid.NewString(), Source: "runtime-sampler", Kind: "runtime.sample",
				WorkspaceID: sample.WorkspaceID, ResourceKind: sample.ResourceKind,
				ResourceID: sample.ResourceID, IncarnationID: sample.IncarnationID, TaskID: sample.TaskID,
				OccurredAt: sample.ObservedAt, Data: data,
			}
			if err := recordUsageWithRetry(sampleCtx, recorder.Record, event); err != nil {
				return err
			}
		}
		return nil
	})
}

func runStorageUsage(ctx context.Context, repository *artifactstore.Repository, store *usage.Store, interval time.Duration, logger *slog.Logger) {
	runUsageCollection(ctx, interval, logger, "storage", func(sampleCtx context.Context) error {
		return collectStorageUsage(sampleCtx, repository, store)
	})
}

func collectStorageUsage(ctx context.Context, repository *artifactstore.Repository, store *usage.Store) error {
	// Snapshot remembered scopes before inventory so a scope first published
	// during the scan cannot be closed by observations that preceded it.
	// Incomplete inventories never produce zero samples.
	namespace := repository.StorageNamespaceID()
	known, err := store.KnownStorageScopes(ctx, namespace)
	if err != nil {
		return err
	}
	inventory, err := repository.InventoryStorage(ctx)
	if err != nil {
		return err
	}
	observations := make(map[usage.StorageScope]artifactstore.StorageObservation, len(known)+len(inventory.Observations))
	for scope := range known {
		observations[scope] = artifactstore.StorageObservation{StorageScope: scope}
	}
	for _, observation := range inventory.Observations {
		observations[observation.StorageScope] = observation
	}
	scanID := uuid.NewString()
	for scope, observation := range observations {
		scopeJSON, err := json.Marshal(scope)
		if err != nil {
			return err
		}
		identity := sha256.Sum256(append([]byte(namespace+"\x00"), scopeJSON...))
		resourceID := hex.EncodeToString(identity[:])
		data, err := json.Marshal(struct {
			artifactstore.StorageObservation
			ScanID            string    `json:"scan_id"`
			ScanStartedAt     time.Time `json:"scan_started_at"`
			ScanCompletedAt   time.Time `json:"scan_completed_at"`
			Coverage          string    `json:"coverage"`
			MeasurementStatus string    `json:"measurement_status"`
			StorageNamespace  string    `json:"storage_namespace"`
		}{observation, scanID, inventory.StartedAt, inventory.CompletedAt, "retained_object_versions", "observed", namespace})
		if err != nil {
			return err
		}
		record := store.Record
		if observation == (artifactstore.StorageObservation{StorageScope: scope}) {
			record = func(recordCtx context.Context, event usage.Event) error {
				return store.RecordStorageZero(recordCtx, event, known[scope])
			}
		}
		if err := recordUsageWithRetry(ctx, record, usage.Event{
			SchemaVersion: usage.SchemaVersion,
			ID:            scanID + ":" + resourceID, Source: "storage-inventory", Kind: "storage.sample",
			WorkspaceID: scope.WorkspaceID, TaskID: scope.TaskID, ResourceKind: scope.ResourceKind,
			ResourceID: resourceID, OccurredAt: inventory.CompletedAt, Data: data,
		}); err != nil {
			return err
		}
	}
	return nil
}

func recordUsageWithRetry(ctx context.Context, record func(context.Context, usage.Event) error, event usage.Event) error {
	var err error
	for attempt := range 3 {
		if err = record(ctx, event); err == nil {
			return nil
		}
		if attempt < 2 {
			timer := time.NewTimer(time.Duration(attempt+1) * 200 * time.Millisecond)
			select {
			case <-ctx.Done():
				timer.Stop()
				return ctx.Err()
			case <-timer.C:
			}
		}
	}
	return fmt.Errorf("record usage %s/%s: %w", event.Source, event.ID, err)
}

func runUsageCollection(ctx context.Context, interval time.Duration, logger *slog.Logger, source string, collect func(context.Context) error) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		// A slow metrics API or object store must not leave overlapping scans.
		collectCtx, cancel := context.WithTimeout(ctx, interval)
		err := collect(collectCtx)
		cancel()
		if err != nil && ctx.Err() == nil {
			logger.Error("Usage collection incomplete", slog.String("source", source), slog.String("error", err.Error()))
		}
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}
