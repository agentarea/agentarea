package sandboxruntime

import (
	"context"
	"fmt"
	"path"
)

// WorkspaceUsage is the live shape of one sandbox workspace. It is measured on
// the sandbox filesystem, not derived from control-plane bookkeeping, because
// shell commands write files the file API never sees.
type WorkspaceUsage struct {
	Entries      int
	LargestBytes int64
	TotalBytes   int64
}

type workspaceEntryKind uint8

const (
	workspaceEntryFile workspaceEntryKind = iota + 1
	workspaceEntryDirectory
	workspaceEntrySymlink
	// A provider response large enough to cross this guard is unauditable in a
	// bounded control-plane request and therefore fails closed. This is not a
	// customer quota; WorkspaceLimits remains the policy source of truth.
	maxWorkspaceAuditEntries = 1_000_000
)

type workspaceEntry struct {
	Path string
	Kind workspaceEntryKind
	Size int64
}

type workspaceDirectoryLister func(context.Context, string) ([]workspaceEntry, error)

// auditWorkspaceFilesystem walks one directory level at a time through the
// provider's authenticated filesystem API. Policy must never depend on a shell
// command executed inside the guest: the agent can change PATH, profiles, and
// binaries in that environment.
func auditWorkspaceFilesystem(
	ctx context.Context,
	provider string,
	root string,
	list workspaceDirectoryLister,
) (WorkspaceUsage, error) {
	root = path.Clean(root)
	if root == "." || root == "/" {
		return WorkspaceUsage{}, fmt.Errorf("%s workspace audit root is invalid", provider)
	}

	directories := []string{root}
	seen := map[string]struct{}{root: {}}
	usage := WorkspaceUsage{}
	entriesSeen := 0
	for len(directories) > 0 {
		directory := directories[0]
		directories = directories[1:]
		entries, err := list(ctx, directory)
		if err != nil {
			return WorkspaceUsage{}, fmt.Errorf("%s list workspace directory %s: %w", provider, directory, err)
		}
		for _, entry := range entries {
			entriesSeen++
			if entriesSeen > maxWorkspaceAuditEntries {
				return WorkspaceUsage{}, fmt.Errorf("%s workspace audit exceeded %d entries", provider, maxWorkspaceAuditEntries)
			}
			clean := path.Clean(entry.Path)
			if clean == root || path.Dir(clean) != directory || !pathWithinRoot(root, clean) {
				return WorkspaceUsage{}, fmt.Errorf("%s returned out-of-scope workspace entry %q", provider, entry.Path)
			}
			if _, exists := seen[clean]; exists {
				return WorkspaceUsage{}, fmt.Errorf("%s returned duplicate workspace entry %q", provider, clean)
			}
			seen[clean] = struct{}{}
			usage.Entries++

			switch entry.Kind {
			case workspaceEntryDirectory:
				directories = append(directories, clean)
			case workspaceEntryFile, workspaceEntrySymlink:
				if entry.Size < 0 {
					return WorkspaceUsage{}, fmt.Errorf("%s returned a negative size for %q", provider, clean)
				}
				if usage.TotalBytes > int64(^uint64(0)>>1)-entry.Size {
					return WorkspaceUsage{}, fmt.Errorf("%s workspace usage overflowed", provider)
				}
				usage.TotalBytes += entry.Size
				if entry.Size > usage.LargestBytes {
					usage.LargestBytes = entry.Size
				}
			default:
				return WorkspaceUsage{}, fmt.Errorf("%s returned an unknown type for workspace entry %q", provider, clean)
			}
		}
	}
	return usage, nil
}

func pathWithinRoot(root, candidate string) bool {
	return candidate != root && len(candidate) > len(root) && candidate[:len(root)] == root && candidate[len(root)] == '/'
}

// Enforce fails when live usage has crossed an admission limit. It runs after
// operations that can write outside the control-plane file API, so an oversized
// workspace is reported instead of silently accepted.
func (u WorkspaceUsage) Enforce(limits WorkspaceLimits) error {
	if u.Entries > limits.MaxFiles {
		return fmt.Errorf("sandbox workspace holds %d filesystem entries; policy allows %d", u.Entries, limits.MaxFiles)
	}
	if u.LargestBytes > limits.MaxFileBytes {
		return fmt.Errorf(
			"sandbox workspace holds a %d-byte file; policy allows %d bytes per file",
			u.LargestBytes, limits.MaxFileBytes,
		)
	}
	if u.TotalBytes > limits.MaxBytes {
		return fmt.Errorf(
			"sandbox workspace holds %d bytes; policy allows %d bytes",
			u.TotalBytes, limits.MaxBytes,
		)
	}
	return nil
}

func (l WorkspaceLimits) Validate() error {
	if l.MaxFiles <= 0 || l.MaxFileBytes <= 0 || l.MaxBytes < l.MaxFileBytes {
		return fmt.Errorf("sandbox workspace limits are invalid")
	}
	return nil
}
