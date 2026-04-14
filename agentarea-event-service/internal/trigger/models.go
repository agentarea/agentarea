package trigger

// Trigger represents an active polling trigger loaded from the database.
type Trigger struct {
	ID                  string
	Name                string
	AgentID             string
	WorkspaceID         string
	CreatedBy           string
	DataExtractor       string
	DataExtractorConfig map[string]any
	DataExtractorState  map[string]any
}
