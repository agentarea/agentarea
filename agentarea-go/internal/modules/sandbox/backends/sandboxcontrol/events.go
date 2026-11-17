package sandboxcontrol

import (
	"encoding/json"
	"fmt"
	"time"
)

func marshalExecutionCloudEvent(record *ExecutionRecord, eventType, source string) (string, error) {
	if record == nil || record.ID == "" || eventType == "" || source == "" {
		return "", fmt.Errorf("execution record, event type, and source are required")
	}
	data := map[string]any{
		"execution_id": record.ID,
		"status":       record.Status,
	}
	if record.TaskID != "" {
		data["task_id"] = record.TaskID
	}
	if record.WorkspaceID != "" {
		data["workspace_id"] = record.WorkspaceID
	}
	if record.WorkspaceManifestRef != nil {
		data["workspace_manifest_ref"] = record.WorkspaceManifestRef
	}
	if len(record.OutputRefs) > 0 {
		data["output_refs"] = record.OutputRefs
		data["output_ref_count"] = len(record.OutputRefs)
	}
	event := CloudEvent{
		SpecVersion:     "1.0",
		Type:            eventType,
		Source:          source,
		ID:              newID("evt"),
		Time:            time.Now().UTC(),
		DataContentType: "application/json",
		CorrelationID:   record.ID,
		Data:            data,
	}
	payload, err := json.Marshal(event)
	if err != nil {
		return "", fmt.Errorf("encode sandbox event %s: %w", eventType, err)
	}
	return string(payload), nil
}
