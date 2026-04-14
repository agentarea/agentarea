package trigger

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"time"
)

// LoadActivePollingTriggers returns all active triggers that have a data_extractor
// configured and are of type "polling" or "cron" (to support existing cron-based
// telegram_polling triggers during migration).
func LoadActivePollingTriggers(ctx context.Context, db *sql.DB) ([]Trigger, error) {
	query := `
		SELECT id, name, agent_id, workspace_id, created_by,
		       data_extractor, data_extractor_config, data_extractor_state
		FROM triggers
		WHERE is_active = true
		  AND data_extractor IS NOT NULL
		  AND trigger_type IN ('polling', 'cron')
	`

	rows, err := db.QueryContext(ctx, query)
	if err != nil {
		return nil, fmt.Errorf("query active polling triggers: %w", err)
	}
	defer rows.Close()

	var triggers []Trigger
	for rows.Next() {
		var t Trigger
		var configJSON, stateJSON sql.NullString

		if err := rows.Scan(
			&t.ID,
			&t.Name,
			&t.AgentID,
			&t.WorkspaceID,
			&t.CreatedBy,
			&t.DataExtractor,
			&configJSON,
			&stateJSON,
		); err != nil {
			return nil, fmt.Errorf("scan trigger row: %w", err)
		}

		if configJSON.Valid && configJSON.String != "" {
			if err := json.Unmarshal([]byte(configJSON.String), &t.DataExtractorConfig); err != nil {
				// Log and skip malformed config rather than aborting
				continue
			}
		}

		if stateJSON.Valid && stateJSON.String != "" {
			if err := json.Unmarshal([]byte(stateJSON.String), &t.DataExtractorState); err != nil {
				t.DataExtractorState = nil
			}
		}

		triggers = append(triggers, t)
	}

	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate trigger rows: %w", err)
	}

	return triggers, nil
}

// UpdateExtractorState persists updated state (e.g. last seen offset) for a trigger.
func UpdateExtractorState(ctx context.Context, db *sql.DB, triggerID string, state map[string]any) error {
	b, err := json.Marshal(state)
	if err != nil {
		return fmt.Errorf("marshal extractor state: %w", err)
	}

	_, err = db.ExecContext(ctx,
		`UPDATE triggers SET data_extractor_state = $1, updated_at = $2 WHERE id = $3`,
		string(b), time.Now().UTC(), triggerID,
	)
	if err != nil {
		return fmt.Errorf("update extractor state: %w", err)
	}
	return nil
}
