package packageimage

import (
	"encoding/json"
	"fmt"

	"github.com/google/go-containerregistry/pkg/v1"
	"github.com/google/go-containerregistry/pkg/v1/mutate"
	"github.com/google/go-containerregistry/pkg/v1/tarball"
)

// Package identifies the immutable package release in the image metadata.
type Package struct {
	Ecosystem Ecosystem `json:"ecosystem"`
	Name      string    `json:"name"`
	Version   string    `json:"version"`
}

// AssembleImage appends the pack workload's layer while retaining the base
// image's entrypoint, command, environment, and other config fields.
func AssembleImage(base v1.Image, layerPath string, packageInfo Package, entrypoint []string) (v1.Image, error) {
	if base == nil {
		return nil, fmt.Errorf("base image is required")
	}
	layer, err := tarball.LayerFromFile(layerPath)
	if err != nil {
		return nil, fmt.Errorf("read package layer: %w", err)
	}
	assembled, err := mutate.Append(base, mutate.Addendum{
		Layer: layer,
		History: v1.History{
			CreatedBy: "agentarea package import " + string(packageInfo.Ecosystem) + ":" + packageInfo.Name + "@" + packageInfo.Version,
		},
	})
	if err != nil {
		return nil, fmt.Errorf("append package layer: %w", err)
	}
	config, err := assembled.ConfigFile()
	if err != nil {
		return nil, fmt.Errorf("read assembled image config: %w", err)
	}
	if config.Config.Labels == nil {
		config.Config.Labels = make(map[string]string)
	}
	config.Config.Labels["io.agentarea.mcp.package"] = string(packageInfo.Ecosystem) + ":" + packageInfo.Name + "@" + packageInfo.Version
	encodedEntrypoint, err := json.Marshal(entrypoint)
	if err != nil {
		return nil, fmt.Errorf("encode package entrypoint: %w", err)
	}
	config.Config.Labels["io.agentarea.mcp.entrypoint"] = string(encodedEntrypoint)
	assembled, err = mutate.Config(assembled, config.Config)
	if err != nil {
		return nil, fmt.Errorf("set package image labels: %w", err)
	}
	return assembled, nil
}
