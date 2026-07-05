// Ory Keto ReBAC namespaces for AgentArea (Ory Permission Language).
//
// Authorization graph for the access explorer. Subjects that receive grants are
// users (Kratos identities), agents, or `workspace#members` (the default-viewer
// rule). The scaling mechanism is the SkillCollection: a single grant on a
// collection fans out to every skill contained in it. Agents are both subjects
// (they use skills/MCP) and objects (someone operates them).
//
// Relation tuple shapes (see config/auth/keto/README.md):
//   Workspace:<id>#members@User:<uid>
//   SkillCollection:<id>#parents@Workspace:<id>
//   SkillCollection:<id>#editors@Agent:<aid>
//   Skill:<id>#collections@SkillCollection:<cid>
//   Skill:<id>#owners@Agent:<aid>                  (direct exception)
//   MCPServer:<id>#connectors@Agent:<aid>
//   Agent:<id>#operators@User:<uid>

import { Namespace, Context, SubjectSet } from "@ory/keto-namespace-types"

class User implements Namespace {}

class Workspace implements Namespace {
  related: {
    members: (User | Agent)[]
  }
}

class SkillCollection implements Namespace {
  related: {
    parents: Workspace[]
    viewers: (User | Agent | SubjectSet<Workspace, "members">)[]
    editors: (User | Agent | SubjectSet<Workspace, "members">)[]
    owners: (User | Agent)[]
  }

  permits = {
    // viewer == "use"; higher relations inherit the lower capabilities.
    use: (ctx: Context): boolean =>
      this.related.viewers.includes(ctx.subject) ||
      this.related.editors.includes(ctx.subject) ||
      this.related.owners.includes(ctx.subject),

    configure: (ctx: Context): boolean =>
      this.related.editors.includes(ctx.subject) ||
      this.related.owners.includes(ctx.subject),

    manage: (ctx: Context): boolean =>
      this.related.owners.includes(ctx.subject),
  }
}

class Skill implements Namespace {
  related: {
    collections: SkillCollection[]
    viewers: (User | Agent)[]
    editors: (User | Agent)[]
    owners: (User | Agent)[]
  }

  permits = {
    // Direct grant OR inherited from any collection the skill belongs to.
    use: (ctx: Context): boolean =>
      this.related.viewers.includes(ctx.subject) ||
      this.related.editors.includes(ctx.subject) ||
      this.related.owners.includes(ctx.subject) ||
      this.related.collections.traverse((c) => c.permits.use(ctx)),

    configure: (ctx: Context): boolean =>
      this.related.editors.includes(ctx.subject) ||
      this.related.owners.includes(ctx.subject) ||
      this.related.collections.traverse((c) => c.permits.configure(ctx)),

    manage: (ctx: Context): boolean =>
      this.related.owners.includes(ctx.subject) ||
      this.related.collections.traverse((c) => c.permits.manage(ctx)),
  }
}

class MCPServer implements Namespace {
  related: {
    connectors: (User | Agent | SubjectSet<Workspace, "members">)[]
    operators: (User | Agent)[]
  }

  permits = {
    connect: (ctx: Context): boolean =>
      this.related.connectors.includes(ctx.subject) ||
      this.related.operators.includes(ctx.subject),

    manage: (ctx: Context): boolean =>
      this.related.operators.includes(ctx.subject),
  }
}

class Agent implements Namespace {
  // Agent as an object: who may operate / own it.
  related: {
    operators: (User | Agent | SubjectSet<Workspace, "members">)[]
    owners: User[]
  }

  permits = {
    operate: (ctx: Context): boolean =>
      this.related.operators.includes(ctx.subject) ||
      this.related.owners.includes(ctx.subject),

    own: (ctx: Context): boolean => this.related.owners.includes(ctx.subject),
  }
}

class Client implements Namespace {
  // Agent-proxy bundle: use == connect a harness to its endpoint; manage == edit/delete.
  related: {
    users: (User | SubjectSet<Workspace, "members">)[]
    owners: User[]
  }

  permits = {
    use: (ctx: Context): boolean =>
      this.related.users.includes(ctx.subject) ||
      this.related.owners.includes(ctx.subject),

    manage: (ctx: Context): boolean =>
      this.related.owners.includes(ctx.subject),
  }
}
