---
name: AgentArea
description: Governed agentic-network platform — dense, technical product UI with drafting-table texture
colors:
  blueprint-blue: "#2252B3"
  blueprint-blue-deep: "#1A3F8A"
  paper: "#FFFFFF"
  workbench: "#FAFAFA"
  ink: "#0A0A0A"
  body-ink: "#2C2F33"
  graphite: "#737373"
  veil: "#F5F5F5"
  hairline: "#E5E5E5"
  signal-success: "#10B981"
  signal-warning: "#F59E0B"
  signal-danger: "#EF4444"
  signal-info: "#3B82F6"
  ledger-violet: "#5E6AD2"
  drafting-amber: "#D99A00"
  board-line: "#E4E4E7"
  board-crop: "#BCBFC5"
typography:
  headline:
    fontFamily: "Inter, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 700
    lineHeight: 1.3
  title:
    fontFamily: "Inter, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 600
    lineHeight: 1.35
  body:
    fontFamily: "Inter, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Inter, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 500
    lineHeight: 1.4
  data:
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace"
    fontSize: "0.75rem"
    fontWeight: 400
    lineHeight: 1.5
rounded:
  sm: "4px"
  md: "6px"
  lg: "8px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "20px"
  xl: "24px"
components:
  button-primary:
    backgroundColor: "{colors.blueprint-blue}"
    textColor: "{colors.paper}"
    rounded: "{rounded.md}"
    height: "36px"
    padding: "8px 16px"
  button-primary-hover:
    backgroundColor: "{colors.blueprint-blue-deep}"
    textColor: "{colors.paper}"
  button-toolbar:
    backgroundColor: "{colors.blueprint-blue}"
    textColor: "{colors.paper}"
    rounded: "{rounded.sm}"
    height: "24px"
    padding: "0 4px"
  input:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.body-ink}"
    rounded: "{rounded.sm}"
    height: "40px"
  card-clickable:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "14px"
  panel-static:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
---

# Design System: AgentArea

Source of truth for the webapp's visual system. Tokens above are normative (light-mode values; dark counterparts are listed per token below — both are mandatory). Code references: `src/app/globals.css` (tokens, base layer, utilities), `tailwind.config.ts` (mappings), `src/components/ui/*` (atoms). Machine-readable extensions (dark values, tonal ramps, shadows, motion, component snippets) live in `.impeccable/design.json`.

## 1. Overview

**Creative North Star: "The Drafting Table"**

AgentArea is where humans govern autonomous agents: approve their actions, budget their spend, audit what they did. The interface is the drafting table that work happens on — a technical drawing that gets reviewed, stamped, and released. The visual DNA is already in the code and is deliberate: 135° diagonal hatching (`--hatch`, `--hatch-accent`), a dashed board grid with registration crop marks (`--board-line`, `--board-crop`), mono-set data labels, dense bordered lists, and one restrained working blue. Decoration is texture, never ornament: a hatch sweep marks a hoverable row, crop marks frame a dashboard, and nothing glows.

This is a **product register** surface: design serves the task, and the bar is earned familiarity — a user fluent in Linear or Stripe should trust every control on sight. Density is a feature (operators triage lists, tables, event streams); consistency is an affordance; delight lives in precision, not motion. The system explicitly rejects: SaaS gradient heroes, glassmorphism, hero-metric stat tiles, identical icon-card grids, toast notifications for system events, and any color or size invented per-component.

Page anatomy: every page renders inside `<ContentBlock>` (`src/components/ContentBlock`) — either the `title` header shape (nested resource pages) or the `breadcrumb` shape (index pages). ContentBlock already provides `flex h-full flex-col overflow-hidden` and content padding; never double-wrap with `.main-content` inside it. Scrollable list bodies are a single `flex-1 min-h-0 overflow-auto` column. RSC data loads behind `<Suspense>` with a content-shaped skeleton (see Elevation for why skeletons, not spinners).

**Key Characteristics:**
- Dense, bordered, list-first layouts; information over air.
- One blue, tinted zinc neutrals, semantic signal colors only where state demands them.
- Drafting texture (hatch, crop marks, mono labels) as the sole decorative vocabulary.
- Flat surfaces; depth from tone and hairlines, shadow only as state response.
- Both themes always; both locales (en/ru) always; keyboard always.

## 2. Colors

Restrained strategy: tinted neutrals carry the surface, Blueprint Blue appears on ≤10% of any screen, semantic signals mark state and nothing else.

### Primary
- **Blueprint Blue** (#2252B3 / `hsl(221 67% 42%)`, dark #285CCC / `hsl(221 67% 48%)`): the working accent — primary buttons, active states, selection, links. Hover deepens to **Blueprint Blue Deep** (#1A3F8A light / #4473DA dark). It is the drafting ink of the system; if a screen has two blues, one is wrong.
- **The One Blue Rule.** `--accent` is intentionally an alias of `--primary` (same HSL in both themes). There is no second accent hue. Write `primary` in new code; never rely on `accent` diverging, and never reintroduce the retired violet `#6a7bff` as an accent.

### Neutral
- **Paper** (#FFFFFF, dark #0A0A0A): page and card surface (`--background`, `--card`).
- **Workbench** (#FAFAFA, dark #18181B): app shell, sidebar backdrop, chat panel (`--layout-background`, `--sidebar-background`). Note: `--chat-background` light must be `0 0% 98%` (#FAFAFA) — the `%` on saturation is required or the declaration is invalid CSS.
- **Ink** (#0A0A0A, dark #FAFAFA): headings and primary text (`--foreground`).
- **Body Ink** (#2C2F33, dark #FFFFFF): body copy (`--text`), a half-step softer than Ink.
- **Graphite** (#737373, dark #A3A3A3): captions, placeholders, descriptions (`--muted-foreground`). This is the floor for text — it is exactly 4.5:1 on Paper. **Never** apply opacity modifiers (`/70`, `/60`) or `text-zinc-400` to body-size text; both fall below AA.
- **Veil** (#F5F5F5, dark #262626): muted fills, secondary buttons (`--muted`, `--secondary`).
- **Hairline** (#E5E5E5, dark #262626): borders, dividers, input strokes (`--border`, `--input`). Panel-on-paper pairs are `border-zinc-200 dark:border-zinc-700` with `bg-white dark:bg-zinc-800`.

### Tertiary (signals and set-dressing)
- **Signal Success / Warning / Danger / Info** (#10B981 / #F59E0B / #EF4444 / #3B82F6; dark #34D399 / #FBBF24 / #F87171 / #60A5FA): status dots, row tints (`--row-tint-*`), blocker groups. Destructive actions use `--destructive` (#EF4444, dark #7F1D1D).
- **Ledger Violet** (#5E6AD2, dark #8B93FF): the spend hero chart and budget bar only.
- **Drafting Amber** (#D99A00, dark #E8B23E): warm accent kept warm in both themes (favorites, cap warnings).
- **Board Line / Board Crop** (#E4E4E7 / #BCBFC5; dark #3F3F46 / #4C4F56): the dashboard's dashed grid and registration marks.
- **Tile Base + Hatch family** (`--tile-base`, `--hatch`, `--hatch-soft`, `--hatch-accent`): the 135° stripe textures. `--hatch-accent` is Blueprint Blue at 7% alpha — the only place the accent may appear as texture.

**The Dark Twin Rule.** Every token above has a dark value and every surface utility carries its `dark:` pair in the same edit. A component with only a light mode is unfinished. The failure mode to guard is the inverse too: all recent contrast failures shipped in *light* mode — test both, not just the one you develop in.

**The Sanctioned Ory Exception.** Auth (Ory Elements) uses hardcoded overrides: submit/link #2252B3, hover #1A3F8A, input focus border #2252B3, divider #E2E8F0 light / #64748B dark. In dark mode links must not stay #2252B3 (≈2.7:1 on the dark card) — use #6A8FE0 or lighter. These hexes are the only sanctioned hardcoded colors in the codebase; the override block belongs to the class the auth pages actually render (`.login-ory` / `.ory-elements` must be one class, not two).

## 3. Typography

**UI Font:** Inter (weights 300–700), loaded via `--font-inter`, falling back to system sans.
**Data Font:** the platform mono stack (`font-mono`) — ids, costs, agent slugs, code, log output.

**Character:** one family, tight scale, weight-driven hierarchy. Product UI needs no display face; Inter carries headings, controls, and body. Mono is reserved for machine-shaped data, which gives dense screens their technical rhythm.

### Hierarchy
- **Headline** (700, 1.25rem mobile / 1.5rem desktop): page titles — the `h1` base style. One per page; ContentBlock's terminal breadcrumb must render as the h1 on index pages.
- **Title** (600, 1.125rem / 1.25rem): section headings — the `h2` base style. Sub-sections use `h3` (500, 16px). Panel titles are real headings, not styled `<div>`/`<span>`.
- **Body** (400, 0.875rem `text-sm`): default UI text. Prose runs at 65–75ch max; tables and dense UI may run wider.
- **Label** (500, 0.75rem `text-xs`): metadata, table headers (uppercase + `tracking-wide`), buttons at `size="xs"`. Captions and descriptions use Graphite via `.note` — which must be `text-muted-foreground`, never `text-zinc-400`.
- **Data** (mono, 0.75rem, `tabular-nums`): identifiers, currency, counts, durations.

**The Fixed Steps Rule.** The type scale is 12 / 13 / 14 / 16 / 18 / 20 / 24 px, expressed through named classes (`text-xs`, `inputSize`, `text-sm`, `text-base`, `text-lg`, `text-xl`, `text-2xl`). Arbitrary sizes (`text-[11.5px]`, `text-[12.5px]`, `text-[19px]`) are prohibited — half-pixel type is the system's most visible drift tell. If a real gap exists, add the step to `tailwind.config.ts` `theme.extend.fontSize` and document it here; never inline it.

**The Tabular Rule.** Every number that can change — currency, counts, durations, percentages — sets `tabular-nums`. Currency renders via `Intl.NumberFormat("en-US", { style: "currency", currency: "USD" })` at 2 fraction digits, expanding to 4 only when the value is under $0.01.

## 4. Elevation

Flat by default. Surfaces sit at rest with a hairline border and at most the whisper-quiet **card shadow** (`0 2px 10px rgba(0,0,0,0.04)`, token `shadow-card` / `.card-shadow`). Depth is conveyed tonally — Paper content on Workbench shell, Veil fills inside Paper panels — and in dark mode by borders alone. Shadows are a *response to state*, never a resting property.

### Shadow Vocabulary
- **card-shadow** (`0 2px 10px rgba(0,0,0,0.04)`): resting elevation for panels and cards.
- **hover lift** (`shadow-md`, Tailwind): appears only on *clickable* cards on hover, paired with `hover:-translate-y-0.5`. Never on static panels.
- **inner-strong / -md / -lg** (inset, see `tailwind.config.ts`): legacy special-purpose insets; do not spread to new surfaces.

**The Flat-By-Default Rule.** A shadow at rest, a hover-lift on a non-clickable element, or a hardcoded `shadow-[…rgba…]` value is a defect. If a panel needs more separation, adjust its border or background tone, not its shadow.

Loading states follow the same physics: content-shaped skeletons that mirror the final layout's exact geometry (breakpoints, gaps, row heights), marked `aria-hidden="true"` — no spinner-in-the-void, no layout shift on hydrate. Motion elsewhere is 150–250ms, ease-out, and conveys state only; layout properties (`width`, `height`, `left`, `margin`) are never animated — use transforms.

## 5. Components

The atom set is shadcn/ui + project atoms in `src/components/ui/`. One vocabulary everywhere: the same action must look the same on every screen (Approve is one color app-wide; confirmation is one Dialog pattern, never `window.confirm`).

### Buttons
- **Shape:** gently rounded (6px, `rounded-md`); toolbar `xs` uses 4px.
- **Primary:** Blueprint Blue fill, Paper text, 36px default height (`h-9 px-4`). Hover deepens toward Blueprint Blue Deep (`hover:bg-primary/90`).
- **Sizes:** `default` 36px (in-form CTAs), `sm` 32px, `xs` 24px (dense toolbars and header CTAs — pattern: `<Button size="xs" className="gap-2"><Plus className="h-5 w-5"/>Deploy new agent</Button>`), `lg` 40px, `icon` 36×36. Visual sizes may stay compact, but every interactive target must reach a ≥44px hit area via padding or pseudo-element on touch surfaces.
- **Hover / Focus:** 300ms transition; `focus-visible:ring-1 ring-ring` is mandatory on every interactive atom — removing an outline without a replacement ring is prohibited.
- **Variants:** `secondary` (Veil fill), `outline`, `ghost`, `destructive`, `link`. Loading goes through the `isLoading` prop (built-in spinner); never hand-roll.

### Cards / Containers
Two surface kinds; the difference is affordance and it is load-bearing:
- **Clickable card** — the `<Card>` atom / `.card` (Paper, 1px Hairline border, 6px radius, 14→18px responsive padding, `cursor-pointer`, hover shadow + lift). Use **only** when the whole card is a link. Flagship: `agents/components/AgentCard.tsx`.
- **Static panel** — hand-rolled `<section className="rounded-md border border-zinc-200 bg-white card-shadow dark:border-zinc-700 dark:bg-zinc-800">` with an explicit `<header>` strip (title + `.note` aside, bottom hairline). No pointer cursor, no lift. `cursor-pointer` baked into `.card` is why the atom must not be used for panels; long-term the cursor belongs opt-in on the atom.
- **List rows** — `.card-item` rows stacked with `space-y-1/2`, hover `bg-muted/40`; or `InteractiveListRow` for triage lists (selection tint via `--row-tint-*`, hatch-accent hover sweep). Row hover actions must also reveal on `group-focus-within:` and be reachable on touch; rows themselves are real links/buttons, never `onClick` divs — and interactive children are never nested inside a `role="button"` parent.

### Inputs / Fields
- **Style:** 40px height, 4px radius, 1px Hairline stroke, 13px text (`inputSize`).
- **Focus:** ring via `focus-visible:ring-ring` (standard) or #2252B3 border (Ory).
- **Labels:** every field gets `<FormLabel htmlFor>` bound to an `id` — including every row of repeated key/value editors (env vars, headers), where per-row `aria-label` is the minimum. Errors render adjacent in `.form-error` (12px), wired with `aria-invalid` + `aria-describedby`, and are announced (`role="alert"` for blocking failures). Reference implementation: `MCPInstanceConfigForm`.

### Chips / Status
- **StatusIndicator** (`ui/status-indicator.tsx`) is the only status vocabulary: tone-colored dot + visible text label, `animate-ping` pulse reserved exclusively for pending/attention states, driven from centralized `get*StatusPresentation` helpers in `src/lib/status.ts`. Status is never conveyed by color alone, and presentation helpers never fall through silently — unknown statuses route to `fallbackStatusPresentation`.
- **Tags/pills:** `rounded-full` Veil or tone-tinted fills at 10-11px medium, always with dark pairs.

### Navigation
- Sidebar (collapsible, Workbench tone, `--sidebar-*` token family) with lucide icons and i18n `titleKey` labels; active state via tone, not stripes. Tabs use the shared `HeaderTabs`/`Tabs` atoms — inactive tab text is `text-muted-foreground` (the hardcoded `#C7C7D1` is a defect), active is `text-foreground`, indicator animates via transform.
- Banners, not toasts: system state surfaces in-place — amber inline banner (`border-amber-300 bg-amber-50 … dark:*`) for warnings, one per page maximum; inline text next to the control for operation results; errors distinguish "failed to load" (with retry) from "empty" (with teaching copy). `<EmptyState>` for full sections; a single muted line for panel sub-sections.

### The Hatch & Board (signature)
The texture layer that makes AgentArea look like itself: 135° diagonal hatching (`bg-hatch-soft` for quiet panel texture, `.bg-hatch-on-color` over filled avatars, `--hatch-accent` blue sweep on row hover) and the dashboard's board grid — dashed `--board-line` rules with `--board-crop` registration marks framing a 2×2 that collapses to a column below `lg`. Use the textures where they already live (rows, avatars, board); do not spread them to forms or modals.

## 6. Do's and Don'ts

### Do:
- **Do** use tokens for every color (`bg-primary`, `text-muted-foreground`, zinc/red shorthands with dark pairs). The only sanctioned hex lives in the Ory override table.
- **Do** ship light + dark in the same edit, and test the theme you *didn't* develop in — recent contrast failures were all light-mode.
- **Do** key every user-facing string in **both** `messages/en.json` and `messages/ru.json` in the same change — production is app.agentarea.ru; a Russian sidebar must not open English pages.
- **Do** give every interactive element a visible `focus-visible` ring, a real accessible name (icon-only buttons get `aria-label`; toggles get `aria-pressed`), and a keyboard path — anything revealed on hover reveals on `focus-within` too.
- **Do** set `tabular-nums` on every mutable number and use the documented type steps.
- **Do** surface every failure: inline banner or field error with retry — an error state must never be indistinguishable from an empty state or a success.
- **Do** confirm destructive and bulk-irreversible actions (Dialog, count + consequences named) and disable submit while in flight.
- **Do** mirror final layout geometry in skeletons, `aria-hidden`, zero shift on hydrate.
- **Do** delete dead code on sight — unreferenced components and routes have carried most of this system's violations (and one latent XSS).

### Don't:
- **Don't** add toast notifications for system events — state surfaces in-place. (Standing project rule.)
- **Don't** use arbitrary font sizes (`text-[11.5px]`), arbitrary shadows (`shadow-[…rgba…]`), inline `style` for color/spacing, or `gray-*`/`slate-*` where the neutral is `zinc-*`.
- **Don't** animate layout properties (`width`, `height`, `left`, `margin`) or use `transition-all` where three properties would do; no bounce/elastic easing; no page-load choreography over 250ms; respect `prefers-reduced-motion`.
- **Don't** use the `<Card>` atom for static panels, hover-lift/translate on non-clickables, or `cursor-pointer` on anything that doesn't navigate.
- **Don't** build side-stripe accents (`border-left` > 1px colored), gradient text, glassmorphism, gradient heroes, hero-metric stat tiles, or identical icon+heading+text card grids — the shared absolute bans, all previously found in this codebase and removed.
- **Don't** reach for a modal first — exhaust inline and progressive disclosure; when a modal is right, it is a real Dialog (focus trap, Escape, labelled) on **every** viewport, not just mobile.
- **Don't** put secrets in URLs, `window.confirm`/`window.open` in flows that have Dialog/Link equivalents, or `onClick` on non-interactive elements.
- **Don't** let `hover:text-accent` styling imply a second hue — accent ≡ primary by design (The One Blue Rule).
- **Don't** custom-size `h1`–`h3` per page; the base layer owns the heading scale.
