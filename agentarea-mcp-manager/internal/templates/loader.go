package templates

import (
	"fmt"
	"os"
	"sync"

	"github.com/agentarea/mcp-manager/internal/models"
	yaml "gopkg.in/yaml.v3"
)

// Loader loads MCP templates from a YAML file
type Loader struct {
	path      string
	templates map[string]models.MCPProviderTemplate
	mutex     sync.RWMutex
}

// NewLoader creates a new template loader
func NewLoader(path string) *Loader {
	return &Loader{
		path:      path,
		templates: make(map[string]models.MCPProviderTemplate),
	}
}

// Load loads the templates from the YAML file
func (l *Loader) Load() error {
	l.mutex.Lock()
	defer l.mutex.Unlock()

	data, err := os.ReadFile(l.path)
	if err != nil {
		return fmt.Errorf("failed to read templates file: %w", err)
	}

	var providerList models.MCPProviderList
	if err := yaml.Unmarshal(data, &providerList); err != nil {
		return fmt.Errorf("failed to unmarshal templates: %w", err)
	}

	l.templates = providerList.Providers
	return nil
}

// List returns a list of all templates
func (l *Loader) List() []models.MCPProviderTemplate {
	l.mutex.RLock()
	defer l.mutex.RUnlock()

	templates := make([]models.MCPProviderTemplate, 0, len(l.templates))
	for _, template := range l.templates {
		templates = append(templates, template)
	}
	return templates
}

// Get returns a specific template by key (provider name)
func (l *Loader) Get(key string) (models.MCPProviderTemplate, bool) {
	l.mutex.RLock()
	defer l.mutex.RUnlock()

	template, exists := l.templates[key]
	return template, exists
}
