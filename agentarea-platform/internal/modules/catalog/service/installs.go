package service

import (
	"context"
	"errors"
	"fmt"
	"strings"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/store"
)

// The limits of a skill package fetched from GitHub (skill_storage_service.py).
const (
	maxFolderFiles = 1000
	maxFolderBytes = 50 * 1024 * 1024
)

// Installs implements api.Installs.
type Installs struct {
	DB    db.Database
	Fetch Fetcher
}

var _ api.Installs = Installs{}

func (x Installs) read(ctx context.Context, ws scope.Workspace, fn func(db.Session) error) error {
	s, done, err := x.DB.Read(ctx, ws)
	if err != nil {
		return err
	}
	defer done()
	return fn(s)
}

func (x Installs) AgentPresets(ctx context.Context, ws scope.Workspace) (out []api.CatalogItem, err error) {
	err = x.read(ctx, ws, func(s db.Session) error {
		out, err = store.Installs{}.AgentPresets(ctx, s)
		return err
	})
	return out, err
}

func (x Installs) AgentItems(ctx context.Context, ws scope.Workspace) (out []api.CatalogItem, err error) {
	err = x.read(ctx, ws, func(s db.Session) error {
		out, err = store.Installs{}.AgentItems(ctx, s)
		return err
	})
	return out, err
}

func (x Installs) item(ctx context.Context, ws scope.Workspace, typ, id string) (it api.CatalogItem, ok bool, err error) {
	err = x.read(ctx, ws, func(s db.Session) error {
		it, ok, err = store.Installs{}.Item(ctx, s, typ, id)
		return err
	})
	return it, ok, err
}

func (x Installs) AgentItem(ctx context.Context, ws scope.Workspace, id string) (api.CatalogItem, bool, error) {
	return x.item(ctx, ws, "agents", id)
}

func (x Installs) SkillItem(ctx context.Context, ws scope.Workspace, id string) (api.CatalogItem, bool, error) {
	return x.item(ctx, ws, "skills", id)
}

func (x Installs) SkillByKey(ctx context.Context, ws scope.Workspace, key string) (it api.CatalogItem, ok bool, err error) {
	err = x.read(ctx, ws, func(s db.Session) error {
		it, ok, err = store.Installs{}.SkillByKey(ctx, s, key)
		return err
	})
	return it, ok, err
}

func (x Installs) MarkInstalled(ctx context.Context, s db.Session, itemID, entityID string, version *string) error {
	item, err := uuid.Parse(itemID)
	if err != nil {
		return fmt.Errorf("catalog item id %q: %w", itemID, err)
	}
	entity, err := uuid.Parse(entityID)
	if err != nil {
		return fmt.Errorf("installed entity id %q: %w", entityID, err)
	}
	return store.Installs{}.MarkInstalled(ctx, s, item, entity, version)
}

func itemUUIDs(itemIDs []string) []uuid.UUID {
	ids := make([]uuid.UUID, 0, len(itemIDs))
	for _, id := range itemIDs {
		if u, err := uuid.Parse(id); err == nil {
			ids = append(ids, u)
		}
	}
	return ids
}

func (x Installs) SkillVersions(ctx context.Context, ws scope.Workspace, itemIDs []string) (out map[string]api.ItemVersions, err error) {
	ids := itemUUIDs(itemIDs)
	if len(ids) == 0 {
		return map[string]api.ItemVersions{}, nil
	}
	err = x.read(ctx, ws, func(s db.Session) error {
		out, err = store.Installs{}.SkillVersions(ctx, s, ids)
		return err
	})
	return out, err
}

func (x Installs) SkillProvenance(ctx context.Context, ws scope.Workspace, itemIDs []string) (out map[string]api.ItemSource, err error) {
	ids := itemUUIDs(itemIDs)
	if len(ids) == 0 {
		return map[string]api.ItemSource{}, nil
	}
	err = x.read(ctx, ws, func(s db.Session) error {
		out, err = store.Installs{}.SkillProvenance(ctx, s, ids)
		return err
	})
	return out, err
}

// ErrNoOutbound is a GitHub read in a process given no outbound clients.
var ErrNoOutbound = errors.New("catalog: reading GitHub needs the outbound clients, which this process was not given")

// Folder is GitHubSkillImporter.download_folder: the commit archive without a token, the REST API with one.
func (x Installs) Folder(ctx context.Context, token, repo, folder string, ref, treeSHA *string) (api.GitHubFolder, error) {
	var f api.GitHubFolder
	var err error
	if token == "" {
		f, err = x.folder(ctx, repo, folder, ref, treeSHA)
	} else {
		f, err = x.tokenFolder(ctx, token, repo, folder, ref, treeSHA)
	}
	var gh *GitHubError
	if errors.As(err, &gh) {
		return f, &api.FolderError{Msg: gh.Msg, NotFound: gh.Status == 404, RateLimited: gh.RateLimit}
	}
	return f, err
}

func (x Installs) folder(ctx context.Context, repo, folder string, ref, treeSHA *string) (api.GitHubFolder, error) {
	if x.Fetch.Net == nil {
		return api.GitHubFolder{}, ErrNoOutbound
	}
	folder = strings.Trim(folder, "/")
	where := repo
	if folder != "" {
		where += "/" + folder
	}
	commit, err := x.Fetch.ResolveCommit(ctx, repo, ref)
	if err != nil {
		return api.GitHubFolder{}, err
	}
	prefix := ""
	if folder != "" {
		prefix = folder + "/"
	}
	packaged := func(p, mode string) bool {
		rel, ok := strings.CutPrefix(p, prefix)
		if !ok || mode == "120000" {
			return false
		}
		for _, part := range strings.Split(rel, "/") {
			if strings.HasPrefix(part, ".") {
				return false
			}
		}
		return true
	}
	all, err := x.Fetch.readArchive(ctx, repo, commit, packaged, maxFolderBytes)
	if err != nil {
		return api.GitHubFolder{}, err
	}
	tree, ok := gitTreeSHAs(all)[folder]
	if !ok {
		return api.GitHubFolder{}, &GitHubError{Msg: fmt.Sprintf("The skill was removed upstream: %s is not in %s at %s", where, repo, commit), Status: 404}
	}
	if treeSHA != nil && *treeSHA != "" && *treeSHA != tree {
		return api.GitHubFolder{}, &GitHubError{Msg: fmt.Sprintf("%s at %s is tree %s, not %s as the catalog pins it", where, commit, tree, *treeSHA)}
	}
	files := map[string][]byte{}
	for p, f := range all {
		if f.data != nil && packaged(p, f.mode) {
			files[strings.TrimPrefix(p, prefix)] = f.data
		}
	}
	if len(files) > maxFolderFiles {
		return api.GitHubFolder{}, &GitHubError{Msg: fmt.Sprintf("GitHub skill package exceeds its limits (%d files, %d MB)", maxFolderFiles, maxFolderBytes/(1024*1024))}
	}
	return api.GitHubFolder{Commit: commit, TreeSHA: tree, Files: files}, nil
}
