---
title: Authorization models
type: concept
summary: How ACL, RBAC, ABAC and ReBAC differ, what question each answers well, and why most real systems combine two of them.
prerequisites: []
related:
  - /concepts/governance/the-agentarea-model
  - /concepts/governance/policy-engine
  - /concepts/governance/tool-authorization
last_updated: 2026-07-29
---

# Authorization models

Authorization answers one question: may this subject perform this action on this
object? The four common models — ACL, RBAC, ABAC and ReBAC — all answer it. They
differ in where the answer is stored, and that difference decides which questions
stay cheap as the system grows.

This page is deliberately product-free. It describes the field, not AgentArea.
The model AgentArea actually deploys is described in
[the AgentArea model](/concepts/governance/the-agentarea-model), and you cannot
evaluate that page without this one.

## The problem

Every system starts with permissions inline: an `if user.is_admin` here, a
hardcoded list of allowed emails there. That works until three things happen at
once.

- **Sharing arrives.** One user wants to give another user access to one object,
  without making them an admin of everything.
- **Hierarchy arrives.** Objects live inside containers, and access to the
  container should reach the contents — without copying a grant onto every child.
- **Someone asks the reverse question.** Not "may Alice read this?" but "what can
  Alice read?" and "who can read this?" Inline checks answer the first and are
  useless for the other two.

An authorization model is the decision about which of those three you make cheap.

## The four models

| Model | Permission lives on | Natural question | Weak at |
|---|---|---|---|
| ACL | the object | may this subject touch this object | organisation-wide rules, hierarchy |
| RBAC | the subject, via a role | what may this person do anywhere | per-object sharing |
| ABAC | neither, computed at request time | conditional and contextual rules | listing, auditing who has access |
| ReBAC | the edges between objects | both directions, through hierarchy | request-time conditions on its own |

### ACL

An access control list attaches permissions to the object: a list of
`(subject, permission)` pairs stored with the thing being protected. Unix file
modes and S3 bucket ACLs are the canonical examples.

ACLs are exact and obvious. They are also flat: there is no way to say "everyone
in Finance" without expanding Finance into individual entries, and no way to say
"grants on this folder reach its files" without writing the grant on every file.
An org-wide policy change means rewriting every list.

### RBAC

Role-based access control bundles permissions into named roles — `editor`,
`billing-admin` — and assigns roles to subjects. The permission set moves from
the object to the subject.

RBAC answers "what may this person do" in one lookup, which is why it dominates
enterprise IAM. Its failure mode is specific and well known: **role explosion.**
The moment permissions need to differ per object, you need a role per object
(`project-42-editor`), and the role catalogue grows with the data. Most systems
that "use RBAC" for sharing have quietly reinvented ACLs inside their role names.

Two role shapes exist and they are not interchangeable. **Concentric** roles nest
(`manage` implies `write` implies `read`) — GitHub and Google Drive work this
way. **Independent** bags do not: a write-only role grants write and nothing
else. Concentric is easier to reason about; independent is what you need when
"can modify but must not read the contents" is a real requirement.

### ABAC

Attribute-based access control computes the decision at request time from
attributes of the subject, the object and the environment: department, data
classification, time of day, source network, spend so far. It is the most
expressive model — it is the only one that can express "not after hours" or "only
while under budget".

The cost is that decisions are computed, not stored. You cannot answer "who can
read this document" without evaluating the policy against every subject, and you
cannot audit an ABAC system by reading its data — you have to read its rules,
which are effectively code. Policy languages like Rego and CEL exist because
those rules need a reviewable form.

### ReBAC

Relationship-based access control stores the *edges* between objects and derives
permissions by walking them. Alice can read `doc:1` because she is an editor of
`folder:9`, and `doc:1` sits in `folder:9`. Nothing about that permission is
stored on `doc:1`; it is computed from two relationships.

The design comes from Google's Zanzibar paper and is implemented by OpenFGA,
SpiceDB and Ory Keto. It is the model behind Drive-style, Notion-style and
Figma-style sharing, and it answers all three questions:

- **Check** — may this subject do this to this object (walk the graph).
- **List objects** — what can this subject reach (reverse lookup from the subject).
- **List subjects** — who can reach this object (expand from the object).

The cost is real. The graph is a second datastore that must stay consistent with
your primary database, every write is a distributed write, and the graph on its
own has no notion of time, budget or request context. Production ReBAC systems
add conditional edges (OpenFGA calls them conditions) precisely to buy back a
slice of ABAC.

## When each fits

- Reach for **ACL** when objects are few, sharing is direct, and nobody asks the
  reverse question. It is not a beginner's mistake; it is a correct answer to a
  small problem.
- Reach for **RBAC** when permissions describe *job functions* rather than
  objects: who may access the billing system at all, who may deploy.
- Reach for **ABAC** when the decision genuinely depends on request context —
  time, spend, classification, network — and you accept that you will not be able
  to enumerate access from stored data.
- Reach for **ReBAC** when objects nest and users share individual objects with
  each other. If your product has folders, projects or workspaces and a Share
  button, this is the shape of your problem.

Note that ReBAC and RBAC are not opposites. A ReBAC graph can hold roles as
objects — a role node carrying permission bits, bound to a subject and a target
by an assignment node. That is how you get role bundles without role explosion:
the role names the bundle, the graph edge names the scope.

## Why not RBAC alone

RBAC is the default answer and the reason to reject it is specific, not
stylistic: **roles are global, sharing is local.**

A role is a bundle of permissions that means the same thing everywhere it is
assigned. The moment a user needs edit on one project and read on another, the
role has to carry the project in its identity, and you are maintaining a role
catalogue that grows with your data rather than with your job functions. Systems
that go down this path end up with thousands of roles nobody can audit, and the
reverse question — who actually has access to this project — becomes a string
search over role names.

ReBAC keeps the bundle and moves the scope onto an edge. The same role object can
be attached to a hundred projects with a hundred assignment edges, and the graph
still answers both directions in one query. The tradeoff you accept in exchange
is an extra datastore with its own consistency and availability characteristics.

## Limits

- **A model is data, not enforcement.** ACL, RBAC, ABAC and ReBAC all describe
  how a decision is *derived*. None of them tells you where the check is called.
  A perfectly modelled graph with no call site at the execution path authorizes
  nothing, and this is by far the most common way authorization projects fail.
- **Listing is a separate engineering problem.** ReBAC gives you reverse lookup
  in principle. In practice, list endpoints usually keep the database as the
  pagination and sorting backbone and refine a page with batched checks, because
  reverse lookup cannot sort by business fields and has result caps. Expect to
  build that layer.
- **No model decides the failure posture.** When the authorization store is
  unreachable, the system either denies (fail-closed, correct, causes an outage)
  or allows (fail-open, keeps serving, is a security incident). That is an
  operational choice made in code, and a system that has not made it explicitly
  has made it by accident.
- **Hybrids are the norm, not a compromise.** Relationship graphs handle
  hierarchy and sharing; runtime ceilings such as budgets, rate limits and
  approval requirements are attribute-shaped and belong to a policy engine. A
  system with both is not confused — it is answering two different questions.

## Related

- [The AgentArea model](/concepts/governance/the-agentarea-model) — the types,
  relations and tuples actually deployed.
- [The policy engine](/concepts/governance/policy-engine) — where runtime
  ceilings are decided, and why they are not in the graph.
- [Tool authorization](/concepts/governance/tool-authorization) — the layers a
  single tool call clears.
