package repository

import (
	"context"
	"database/sql"
	"fmt"
	"time"

	"github.com/agentarea/mcp-manager/internal/models"
)

// MCPInstanceRepository implements the reconciler.MCPInstanceRepository interface
type MCPInstanceRepository struct {
	db *sql.DB
}

// NewMCPInstanceRepository creates a new repository
func NewMCPInstanceRepository(db *sql.DB) *MCPInstanceRepository {
	return &MCPInstanceRepository{db: db}
}

// GetAll retrieves all MCP instances from the database
func (r *MCPInstanceRepository) GetAll(ctx context.Context) ([]*models.MCPServerInstance, error) {
	query := `
		SELECT id, name, service_name, status, url, internal_url, 
		       image, port, environment, labels, created_at, updated_at
		FROM mcp_server_instances
		WHERE deleted_at IS NULL
	`
	
	rows, err := r.db.QueryContext(ctx, query)
	if err != nil {
		return nil, fmt.Errorf("failed to query MCP instances: %w", err)
	}
	defer rows.Close()
	
	var instances []*models.MCPServerInstance
	for rows.Next() {
		instance := &models.MCPServerInstance{}
		var envJSON, labelsJSON []byte
		
		err := rows.Scan(
			&instance.ID,
			&instance.Name,
			&instance.ServiceName,
			&instance.Status,
			&instance.URL,
			&instance.InternalURL,
			&instance.Image,
			&instance.Port,
			&envJSON,
			&labelsJSON,
			&instance.CreatedAt,
			&instance.UpdatedAt,
		)
		if err != nil {
			return nil, fmt.Errorf("failed to scan MCP instance: %w", err)
		}
		
		// Parse JSON fields
		if len(envJSON) > 0 {
			instance.Environment = envJSON
		}
		if len(labelsJSON) > 0 {
			instance.Labels = labelsJSON
		}
		
		instances = append(instances, instance)
	}
	
	return instances, rows.Err()
}

// GetByID retrieves a single MCP instance by ID
func (r *MCPInstanceRepository) GetByID(ctx context.Context, id string) (*models.MCPServerInstance, error) {
	query := `
		SELECT id, name, service_name, status, url, internal_url, 
		       image, port, environment, labels, created_at, updated_at
		FROM mcp_server_instances
		WHERE id = $1 AND deleted_at IS NULL
	`
	
	instance := &models.MCPServerInstance{}
	var envJSON, labelsJSON []byte
	
	err := r.db.QueryRowContext(ctx, query, id).Scan(
		&instance.ID,
		&instance.Name,
		&instance.ServiceName,
		&instance.Status,
		&instance.URL,
		&instance.InternalURL,
		&instance.Image,
		&instance.Port,
		&envJSON,
		&labelsJSON,
		&instance.CreatedAt,
		&instance.UpdatedAt,
	)
	if err == sql.ErrNoRows {
		return nil, fmt.Errorf("MCP instance not found: %s", id)
	}
	if err != nil {
		return nil, fmt.Errorf("failed to query MCP instance: %w", err)
	}
	
	if len(envJSON) > 0 {
		instance.Environment = envJSON
	}
	if len(labelsJSON) > 0 {
		instance.Labels = labelsJSON
	}
	
	return instance, nil
}

// UpdateStatus updates the status of an MCP instance
func (r *MCPInstanceRepository) UpdateStatus(ctx context.Context, id string, status string) error {
	query := `
		UPDATE mcp_server_instances
		SET status = $1, updated_at = $2
		WHERE id = $3 AND deleted_at IS NULL
	`
	
	result, err := r.db.ExecContext(ctx, query, status, time.Now().UTC(), id)
	if err != nil {
		return fmt.Errorf("failed to update MCP instance status: %w", err)
	}
	
	rowsAffected, err := result.RowsAffected()
	if err != nil {
		return fmt.Errorf("failed to get rows affected: %w", err)
	}
	
	if rowsAffected == 0 {
		return fmt.Errorf("MCP instance not found: %s", id)
	}
	
	return nil
}

// GetByStatus retrieves MCP instances by status
func (r *MCPInstanceRepository) GetByStatus(ctx context.Context, status string) ([]*models.MCPServerInstance, error) {
	query := `
		SELECT id, name, service_name, status, url, internal_url, 
		       image, port, environment, labels, created_at, updated_at
		FROM mcp_server_instances
		WHERE status = $1 AND deleted_at IS NULL
	`
	
	rows, err := r.db.QueryContext(ctx, query, status)
	if err != nil {
		return nil, fmt.Errorf("failed to query MCP instances: %w", err)
	}
	defer rows.Close()
	
	var instances []*models.MCPServerInstance
	for rows.Next() {
		instance := &models.MCPServerInstance{}
		var envJSON, labelsJSON []byte
		
		err := rows.Scan(
			&instance.ID,
			&instance.Name,
			&instance.ServiceName,
			&instance.Status,
			&instance.URL,
			&instance.InternalURL,
			&instance.Image,
			&instance.Port,
			&envJSON,
			&labelsJSON,
			&instance.CreatedAt,
			&instance.UpdatedAt,
		)
		if err != nil {
			return nil, fmt.Errorf("failed to scan MCP instance: %w", err)
		}
		
		if len(envJSON) > 0 {
			instance.Environment = envJSON
		}
		if len(labelsJSON) > 0 {
			instance.Labels = labelsJSON
		}
		
		instances = append(instances, instance)
	}
	
	return instances, rows.Err()
}
