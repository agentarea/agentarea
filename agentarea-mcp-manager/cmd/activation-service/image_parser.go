// Docker image config parser for activation service
package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

// ImageConfig represents docker image configuration
type ImageConfig struct {
	Entrypoint []string
	Cmd        []string
	Env        []string
	WorkingDir string
	User       string
}

// DockerImageManifest represents the manifest.json in docker archives
type DockerImageManifest []struct {
	Config string `json:"Config"`
}

// DockerConfig represents the config.json structure
type DockerConfig struct {
	Config struct {
		Entrypoint []string `json:"Entrypoint"`
		Cmd        []string `json:"Cmd"`
		Env        []string `json:"Env"`
		WorkingDir string   `json:"WorkingDir"`
		User       string   `json:"User"`
	} `json:"config"`
}

// ParseImageConfig extracts configuration from extracted docker image
// Returns error if config.json not found or invalid
func ParseImageConfig(extractDir string) (*ImageConfig, error) {
	// First, look for manifest.json to find config file path
	manifestPath := filepath.Join(extractDir, "manifest.json")
	manifestData, err := os.ReadFile(manifestPath)
	if err != nil {
		// Try direct config.json if no manifest
		return parseDirectConfig(extractDir)
	}

	var manifest DockerImageManifest
	if err := json.Unmarshal(manifestData, &manifest); err != nil {
		return nil, fmt.Errorf("failed to parse manifest.json: %w", err)
	}

	if len(manifest) == 0 {
		return nil, fmt.Errorf("empty manifest.json")
	}

	// Config file is specified in manifest
	configPath := filepath.Join(extractDir, manifest[0].Config)
	return parseConfigFile(configPath)
}

// parseDirectConfig looks for config.json directly in extractDir
func parseDirectConfig(extractDir string) (*ImageConfig, error) {
	configPath := filepath.Join(extractDir, "config.json")
	return parseConfigFile(configPath)
}

// parseConfigFile parses a docker config.json file
func parseConfigFile(configPath string) (*ImageConfig, error) {
	data, err := os.ReadFile(configPath)
	if err != nil {
		return nil, fmt.Errorf("config.json not found: %w", err)
	}

	var dockerConfig DockerConfig
	if err := json.Unmarshal(data, &dockerConfig); err != nil {
		return nil, fmt.Errorf("failed to parse config.json: %w", err)
	}

	return &ImageConfig{
		Entrypoint: dockerConfig.Config.Entrypoint,
		Cmd:        dockerConfig.Config.Cmd,
		Env:        dockerConfig.Config.Env,
		WorkingDir: dockerConfig.Config.WorkingDir,
		User:       dockerConfig.Config.User,
	}, nil
}

// GetEffectiveCommand returns the effective entrypoint and command.
//
// The entrypoint (executable and any fixed args) always comes from the verified image
// config — it is never taken from user input. This ensures only hash-verified image
// content determines what binary is executed.
//
// The command (CMD args) may be overridden by the caller; these are arguments passed
// to the entrypoint binary, not a new executable.
//
// Returns an error if imageConfig is nil or defines neither ENTRYPOINT nor CMD.
func GetEffectiveCommand(imageConfig *ImageConfig, userCommand []string) (entrypoint, command []string, err error) {
	if imageConfig == nil {
		return nil, nil, fmt.Errorf("image config unavailable: image must define ENTRYPOINT or CMD")
	}

	entrypoint = imageConfig.Entrypoint // always from image — not user-controlled

	if len(userCommand) > 0 {
		command = userCommand // caller may override CMD arguments
	} else {
		command = imageConfig.Cmd
	}

	if len(entrypoint) == 0 && len(command) == 0 {
		return nil, nil, fmt.Errorf("image defines neither ENTRYPOINT nor CMD")
	}

	return entrypoint, command, nil
}

// ParseEnv parses KEY=value strings into a map
func ParseEnv(env []string) map[string]string {
	result := make(map[string]string)
	for _, e := range env {
		if idx := indexOf(e, '='); idx > 0 {
			key := e[:idx]
			value := e[idx+1:]
			result[key] = value
		}
	}
	return result
}

func indexOf(s string, c byte) int {
	for i := 0; i < len(s); i++ {
		if s[i] == c {
			return i
		}
	}
	return -1
}
