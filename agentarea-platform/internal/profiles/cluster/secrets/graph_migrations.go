package secrets

import (
	"context"
	"log/slog"

	kauthz "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
)

// platformPrincipal is PLATFORM_PRINCIPAL_ID: a creator no one owns through.
const platformPrincipal = "platform"

// SecretOwners is the graph migration 20261109_2300_secret_owners
// (agentarea_secrets/graph_migrations.py): every user secret, owner_type NULL, becomes a
// resource under its workspace's root project, and its creator, the agent that created it or
// else the person, gets the owner relations a create grants. A secret the platform principal
// created gets the project tuple only. Tuples already there are left as they are.
func SecretOwners(log *slog.Logger) kauthz.GraphMigration {
	if log == nil {
		log = slog.Default()
	}
	return kauthz.GraphMigration{
		ID:          "20261109_2300_secret_owners",
		Description: "user secrets become graph resources, owned by their creators",
		Apply: func(ctx context.Context, q db.Querier, graph kauthz.GraphProvider) error {
			return grantSecretOwners(ctx, q, graph, log)
		},
	}
}

type userSecret struct {
	id, workspaceID, createdBy string
}

func grantSecretOwners(ctx context.Context, q db.Querier, graph kauthz.GraphProvider, log *slog.Logger) error {
	rows, err := q.Query(ctx, `SELECT id::text, workspace_id, created_by FROM encrypted_secrets
		WHERE owner_type IS NULL ORDER BY workspace_id, id`)
	if err != nil {
		return err
	}
	var secrets []userSecret
	creators := map[string]struct{}{}
	for rows.Next() {
		var s userSecret
		if err := rows.Scan(&s.id, &s.workspaceID, &s.createdBy); err != nil {
			rows.Close()
			return err
		}
		secrets = append(secrets, s)
		creators[s.createdBy] = struct{}{}
	}
	rows.Close()
	if err := rows.Err(); err != nil || len(secrets) == 0 {
		return err
	}
	ids := make([]string, 0, len(creators))
	for c := range creators {
		ids = append(ids, c)
	}
	agents := map[string]bool{}
	arows, err := q.Query(ctx, `SELECT id::text FROM agents WHERE id::text = ANY($1)`, ids)
	if err != nil {
		return err
	}
	for arows.Next() {
		var id string
		if err := arows.Scan(&id); err != nil {
			arows.Close()
			return err
		}
		agents[id] = true
	}
	arows.Close()
	if err := arows.Err(); err != nil {
		return err
	}
	g, err := graph(ctx)
	if err != nil {
		return err
	}
	for _, s := range secrets {
		object := kauthz.ObjectRef(kauthz.TypeResource, s.id)
		if _, err := kauthz.WriteIdempotent(ctx, g, kauthz.Tuple{User: kauthz.RootProject(s.workspaceID), Relation: kauthz.RelProject, Object: object}); err != nil {
			return err
		}
		if s.createdBy == "" || s.createdBy == platformPrincipal {
			log.WarnContext(ctx, "User secret has no creator to own it; its project only", "secret_id", s.id, "workspace_id", s.workspaceID)
			continue
		}
		owner := kauthz.UserSubject(s.createdBy)
		if agents[s.createdBy] {
			owner = kauthz.AgentSubject(s.createdBy)
		}
		for _, rel := range kauthz.OwnerRelations() {
			if _, err := kauthz.WriteIdempotent(ctx, g, kauthz.Tuple{User: owner, Relation: rel, Object: object}); err != nil {
				return err
			}
		}
	}
	log.InfoContext(ctx, "Recorded the owners of user secrets in the graph", "count", len(secrets))
	return nil
}
