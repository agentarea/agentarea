package usage

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"path"
	"strings"
)

// StorageScope separates retained content from internal workspace metadata.
type StorageScope struct {
	WorkspaceID  string `json:"workspace_id"`
	TaskID       string `json:"task_id"`
	ResourceKind string `json:"resource_kind"`
}

func StorageNamespaceID(bucket, prefix string) string {
	normalizedPrefix := strings.Trim(path.Clean("/"+prefix), "/")
	hash := sha256.Sum256([]byte(bucket + "\x00" + normalizedPrefix))
	return hex.EncodeToString(hash[:])
}

// KnownStorageScopes retains scopes until a complete all-zero inventory sample.
// Each version is the latest durable sequence observed before inventory starts.
func (s *Store) KnownStorageScopes(ctx context.Context, namespaceID string) (map[StorageScope]int64, error) {
	rows, err := s.db.QueryContext(ctx, `SELECT latest.workspace_id,latest.task_id,latest.resource_kind,latest.sequence
		FROM (
			SELECT DISTINCT ON (workspace_id,task_id,resource_kind)
				workspace_id,task_id,resource_kind,sequence
			FROM resource_usage_events
			WHERE kind IN ('storage.sample','storage.artifact.published')
			AND source IN ('storage-inventory','artifact-store')
			AND data->>'storage_namespace'=$1
			ORDER BY workspace_id,task_id,resource_kind,sequence DESC
		) AS latest
		JOIN resource_usage_events AS event ON event.sequence=latest.sequence
		WHERE event.kind <> 'storage.sample' OR NOT event.data @>
			'{"current_bytes":0,"retained_bytes":0,"current_objects":0,"retained_versions":0,"delete_markers":0,"delete_marker_key_bytes":0}'::jsonb`, namespaceID)
	if err != nil {
		return nil, fmt.Errorf("read durable storage scopes: %w", err)
	}
	defer rows.Close()
	scopes := make(map[StorageScope]int64)
	for rows.Next() {
		var scope StorageScope
		var sequence int64
		if err := rows.Scan(&scope.WorkspaceID, &scope.TaskID, &scope.ResourceKind, &sequence); err != nil {
			return nil, err
		}
		scopes[scope] = sequence
	}
	return scopes, rows.Err()
}

func isStorageEvent(event Event) bool {
	return (event.Source == "storage-inventory" || event.Source == "artifact-store") &&
		(event.Kind == "storage.sample" || event.Kind == "storage.artifact.published")
}

// All storage writers hold this lock through commit. The version comparison
// and zero insertion must share it with publications, not just other scans.
func lockStorageScope(ctx context.Context, tx *sql.Tx, event Event) (string, error) {
	var data struct {
		Namespace string `json:"storage_namespace"`
	}
	if err := json.Unmarshal(event.Data, &data); err != nil {
		return "", fmt.Errorf("decode storage namespace: %w", err)
	}
	if data.Namespace == "" {
		return "", errors.New("storage event requires storage_namespace")
	}
	_, err := tx.ExecContext(ctx, `SELECT pg_advisory_xact_lock(hashtextextended(
		jsonb_build_array('agentarea:usage:storage'::text,$1::text,$2::text,$3::text,$4::text)::text,0))`,
		data.Namespace, event.WorkspaceID, event.TaskID, event.ResourceKind)
	if err != nil {
		return "", fmt.Errorf("lock storage scope: %w", err)
	}
	return data.Namespace, nil
}

// RecordStorageZero discards a synthesized zero if the scope changed after the
// pre-scan snapshot. Skipping a stale observation is successful, not a retry.
func (s *Store) RecordStorageZero(ctx context.Context, event Event, expectedSequence int64) error {
	if err := event.Validate(); err != nil {
		return err
	}
	if event.Source != "storage-inventory" || event.Kind != "storage.sample" {
		return errors.New("storage zero requires an inventory sample")
	}
	tx, err := s.db.BeginTx(ctx, &sql.TxOptions{Isolation: sql.LevelReadCommitted})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback() }()
	namespace, err := lockStorageScope(ctx, tx, event)
	if err != nil {
		return err
	}
	var latestSequence int64
	err = tx.QueryRowContext(ctx, `SELECT sequence FROM resource_usage_events
		WHERE kind IN ('storage.sample','storage.artifact.published')
		AND source IN ('storage-inventory','artifact-store')
		AND data->>'storage_namespace'=$1 AND workspace_id=$2 AND task_id=$3 AND resource_kind=$4
		ORDER BY sequence DESC LIMIT 1`, namespace, event.WorkspaceID, event.TaskID, event.ResourceKind).Scan(&latestSequence)
	if errors.Is(err, sql.ErrNoRows) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("compare storage scope version: %w", err)
	}
	if latestSequence != expectedSequence {
		return nil
	}
	if err := recordSQL(ctx, tx, event); err != nil {
		return err
	}
	return tx.Commit()
}
