package docker

import (
	"context"
	"fmt"
	"strings"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/runtime/workload"
)

// DryRunResult is what ValidateDryRun found, in the shape the manager's
// POST /containers/validate answered.
type DryRunResult struct {
	Valid         bool     `json:"valid"`
	Errors        []string `json:"errors"`
	Warnings      []string `json:"warnings"`
	ImageExists   bool     `json:"image_exists"`
	CanPull       bool     `json:"can_pull"`
	EstimatedSize string   `json:"estimated_size,omitempty"`
}

func (r *DryRunResult) fail(format string, args ...any) {
	r.Valid = false
	r.Errors = append(r.Errors, fmt.Sprintf(format, args...))
}

// ValidateDryRun checks an instance's json_spec without starting it: the spec's
// shape, that a docker image is present or can be pulled, and that the host has
// room for one more workload. A command spec runs on mcp-base and needs no image
// check. A runtime that cannot answer is an error, not an invalid spec.
func (b *Backend) ValidateDryRun(ctx context.Context, spec map[string]any) (DryRunResult, error) {
	r := DryRunResult{Valid: true, Errors: []string{}, Warnings: []string{}}
	if err := validateJSONSpec(spec); err != nil {
		r.fail("Invalid JSON spec: %v", err)
	}
	if t, _ := spec["type"].(string); t == "command" {
		r.ImageExists, r.CanPull = true, true
	} else {
		image, ok := spec["image"].(string)
		if !ok || image == "" {
			r.fail("Missing or invalid image in json_spec")
			return r, nil
		}
		if err := b.checkImage(ctx, image, &r); err != nil {
			return DryRunResult{}, err
		}
	}
	occupied, err := b.occupied(ctx)
	if err != nil {
		return DryRunResult{}, err
	}
	switch {
	case occupied >= b.cfg.MaxContainers:
		r.fail("Container limit reached: %d/%d", occupied, b.cfg.MaxContainers)
	case occupied >= b.cfg.MaxContainers-1:
		r.Warnings = append(r.Warnings, fmt.Sprintf("Close to container limit: %d/%d", occupied, b.cfg.MaxContainers))
	}
	if err := validateResources(spec); err != nil {
		r.Warnings = append(r.Warnings, fmt.Sprintf("Resource validation: %v", err))
	}
	return r, nil
}

// checkImage reports whether the image is on this host, and otherwise whether
// a pull succeeds: a real pull is the one check every registry answers.
func (b *Backend) checkImage(ctx context.Context, image string, r *DryRunResult) error {
	if err := workload.ValidateImageReference(image); err != nil {
		r.fail("%v", err)
		return nil
	}
	_, stderr, err := b.run.Run(ctx, "image", "inspect", "--format", "{{.Id}}", image)
	if err != nil && !imageAbsent(stderr) {
		return fmt.Errorf("inspecting image %s: %w: %s", image, err, strings.TrimSpace(string(stderr)))
	}
	if err == nil {
		r.ImageExists = true
		size, stderr, err := b.run.Run(ctx, "image", "inspect", "--format", "{{.Size}}", image)
		if err != nil {
			return fmt.Errorf("reading the size of image %s: %w: %s", image, err, strings.TrimSpace(string(stderr)))
		}
		r.EstimatedSize = strings.TrimSpace(string(size)) + " bytes"
		return nil
	}
	if _, stderr, err := b.run.Run(ctx, "pull", "--quiet", image); err != nil {
		b.log.InfoContext(ctx, "dry run could not pull the MCP image", "image", image, "error", err,
			"output", strings.TrimSpace(string(stderr)))
		r.fail("Image %s does not exist locally and cannot be pulled", image)
		return nil
	}
	r.CanPull = true
	r.Warnings = append(r.Warnings, fmt.Sprintf("Image %s will be pulled during container creation", image))
	return nil
}

func imageAbsent(stderr []byte) bool {
	lowered := strings.ToLower(string(stderr))
	return strings.Contains(lowered, "no such image") || strings.Contains(lowered, "no such object") ||
		strings.Contains(lowered, "image not known")
}

func validateJSONSpec(spec map[string]any) error {
	if t, _ := spec["type"].(string); t == "command" {
		if c, ok := spec["command"].(string); !ok || c == "" {
			return fmt.Errorf("command field must be a non-empty string for type 'command'")
		}
	} else {
		image, ok := spec["image"].(string)
		if !ok || image == "" {
			return fmt.Errorf("image field must be a non-empty string")
		}
		if err := workload.ValidateImageReference(image); err != nil {
			return err
		}
		switch port := spec["port"].(type) {
		case int:
			if port < 1 || port > 65535 {
				return fmt.Errorf("port must be between 1 and 65535")
			}
		case float64:
			if port < 1 || port > 65535 {
				return fmt.Errorf("port must be between 1 and 65535")
			}
		default:
			return fmt.Errorf("port field must be a number")
		}
		if cmd, ok := spec["cmd"]; ok {
			if _, isList := cmd.([]any); !isList {
				return fmt.Errorf("cmd field must be an array")
			}
		}
	}
	if env, ok := spec["environment"]; ok {
		if _, isMap := env.(map[string]any); !isMap {
			return fmt.Errorf("environment field must be an object")
		}
	}
	return nil
}

func validateResources(spec map[string]any) error {
	raw, ok := spec["resources"]
	if !ok {
		return nil
	}
	resources, ok := raw.(map[string]any)
	if !ok {
		return fmt.Errorf("resources must be an object")
	}
	for _, key := range []string{"memory_limit", "cpu_limit"} {
		if v, ok := resources[key]; ok {
			if _, isString := v.(string); !isString {
				return fmt.Errorf("%s must be a string", key)
			}
		}
	}
	return nil
}
