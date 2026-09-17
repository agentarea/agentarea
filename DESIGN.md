# Design

## Source of truth
- Status: Active for automation creation and editing.
- Last refreshed: 2026-09-11.
- Primary surface: `/triggers/create` and the shared automation edit form.
- Tokens and shared patterns remain in [agentarea-webapp/Design.md](agentarea-webapp/Design.md).
- Evidence: the current form, generated agent/tool contracts, task execution configuration, the local product-marketing ICP, and the user's same-thread layout direction.

## Brand
- Precise, calm, operational, trustworthy.
- Trust comes from named resources, accurate access scope, and visible orchestration ownership.
- Avoid decorative dashboards, promotional copy, repeated colored field icons, and unverified access claims.

## Product goals
- Let a platform lead describe an automated task and inspect its execution context together.
- Make the selected agent's orchestrator role explicit.
- Keep task-specific additions distinct from capabilities already configured on the agent.
- Success: the user can identify the orchestrator, delegated agents, MCP servers/tools, skills, and files before creating the automation.
- Non-goals: a general workflow canvas, a market-product clone, or workspace-wide permission editing.

## Personas and jobs
- CTOs, VP Engineering, AI/platform leads, and infrastructure teams.
- Define an operational task, its starting event, the responsible agent, and the resources it can use.
- Review access and reuse an existing agent configuration without losing saved settings.

## Information architecture
- Left: task name, task instructions, trigger/channel configuration, and collapsed technical settings.
- Right: orchestrator selector followed by concrete delegation agents, MCP, skills, and files.
- Credentials stay beside the trigger they authenticate; they are references selected by name.
- The existing header owns the primary create/save action.

## Design principles
- Follow the user's two-column authoring/context layout; the right column is a working access panel, not decorative summary text.
- One clear hierarchy: the orchestrator leads the resource groups below it.
- Render named resources and their origin, not just totals or generic assurances.
- Keep optional protocol and failure-limit controls behind a native disclosure.
- No arbitrary JSON editor or manual webhook-setup banners.

## Visual language
- Reuse the existing Inter type system, graphite neutrals, white surfaces, and operational blue.
- Key palette from the existing system: background `#ffffff`, layout `#fafafa`, foreground `#0a0a0a`, muted `#737373`, border `#e5e5e5`, primary `#2252b3`.
- Broad writing area and narrower access column, separated by a quiet rule; no tile for every field.
- Use entity icons for resources and restrained group headings. Favor 8/12/16/24/32px spacing.
- Motion only for disclosures and pickers; respect reduced motion.

## Components
- Reuse `ContentBlock`, `InfoPanelShell`/`InfoPanelBody`, `ConfigSheet`, `SelectableList`, `FileTree`, secret `Select`, `CronScheduler`, and canonical entity icons.
- Shared `Input` title and `Textarea` document variants own authoring typography; avoid per-screen font-size overrides.
- Show origin labels on task additions; inherited rows sit under the selected orchestrator without repeating the same origin caption.
- The shared creation/edit form owns transient task selections.
- Resource presentation must mirror runtime resolution and retain validation, loading, and unavailable states.

## Accessibility
- Every control has an associated or accessible label, including the document-style task title.
- Keyboard access to pickers, resource removal, disclosures, and submission.
- Keep error messages visible; reveal technical controls when they contain validation errors.
- Preserve token-based contrast, light/dark themes, and reduced-motion behavior.

## Responsive behavior
- Desktop: task authoring left, narrower access panel right; the access panel stays in view while feasible.
- Narrow screens: stack the same content without horizontal overflow; pickers remain reachable and touch targets retain their normal sizes.
- Do not require hover to discover a resource or remove a task addition.

## Interaction states
- Loading: explicit resource/agent loading state; do not show a previous agent's resources during a switch.
- Empty: a concise group-specific absence state; the orchestrator remains selectable.
- Error: distinguish unavailable data from an empty configuration and offer retry where data is loaded.
- Success: existing create/update actions and navigation.
- Disabled: preserve existing pending-submit behavior and source-specific credential requirements.
- Slow network: keep task input stable; retry resource loading without reloading the form.

## Content voice
- Short operational labels: task, orchestrator, agents, MCP, skills, files, trigger.
- Explain access origins only where they affect the user's decision.
- Avoid repeated “Optional” markers, setup essays, and backend field terminology in the main path.

## Implementation constraints
- Next.js/React, existing Tailwind/shadcn primitives; no new dependencies.
- Server actions and generated API types; never fetch secret values into the browser.
- Preserve existing form field names, saved values, task parameters, and create/edit semantics.
- Configured access is not a promise that runtime policy or service availability can never block a call.
- Verify desktop/mobile and light/dark screenshots, actual picker interactions, validation, agent switching, and submitted payloads.

## Reference observations
- [Linear](https://linear.app/docs/creating-issues): prioritize the work's title and body; keep secondary properties quieter.
- [Notion](https://www.notion.com/help/database-automations), [Slack](https://slack.com/help/articles/17542172840595-Build-a-workflow--Create-a-workflow-in-Slack/) and [Airtable](https://support.airtable.com/articles/3669392397-getting-started-with-airtable-automations): make the trigger/action relationship explicit.
- [Zapier](https://help.zapier.com/hc/en-us/articles/8496288188429-Set-up-your-Zap-trigger) and [n8n](https://docs.n8n.io/build/understand-workflows/create-and-edit-credentials): select reusable connections/credentials in context.
- [GitHub](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets): use named secret references.
- [Retool](https://docs.retool.com/workflows/quickstart), [Make](https://help.make.com/create-your-first-scenario), and [Vercel](https://vercel.com/docs/git): visible execution sequence, primary entity first, and reasonable defaults.
- These are reference patterns, not a market ranking or a claim that all ten use the same geometry. The two-column layout is the user's explicit choice for AgentArea.

## Open questions
- Runtime policy and service health can change after creation; the UI should not imply immutable authorization.
