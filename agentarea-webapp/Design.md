# AgentArea Design System

This document serves as the single source of truth for visual design tokens, component primitives, and usage guidelines for the **AgentArea** web application.

---

## Table of Contents

1. [Overview](#overview)
2. [Design Tokens](#design-tokens)
   - [Colors](#colors)
   - [Typography](#typography)
   - [Spacing](#spacing)
   - [Border Radius](#border-radius)
   - [Shadows](#shadows)
   - [Transitions](#transitions)
3. [Themes](#themes)
   - [Light Mode](#light-mode)
   - [Dark Mode](#dark-mode)
4. [Component Primitives](#component-primitives)
   - [Card](#card)
   - [Button](#button)
   - [Input](#input)
   - [Label](#label)
   - [Link](#link)
   - [Loader](#loader)
5. [Usage Guidelines](#usage-guidelines)

---

## Overview

The AgentArea frontend is built with **Next.js**, **Tailwind CSS**, and **shadcn/ui** primitives. Styles are managed through CSS custom properties (variables) defined in `globals.css` and mapped to Tailwind's theme in `tailwind.config.ts`.

**Key technologies:**
- Tailwind CSS v3.4
- next-themes (light / dark / system)
- CSS Variables for token-driven theming
- Inter font family (Google Fonts)

---

## Design Tokens

### Colors

#### Brand Colors

| Token | Light Mode | Dark Mode | Usage |
|-------|------------|-----------|-------|
| **Primary** | `#2252b3` | `#3b6ad4` | Main CTA, active states, key actions |
| **Primary Hover** | `#8c9eff` | `#5b85e0` | Primary buttons / links on hover |
| **Accent** | `#6a7bff` | `#6a7bff` | Highlights, badges, secondary emphasis |
| **Accent Hover** | `#5b6caa` | `#5b6caa` | Accent elements on hover |

#### Semantic Colors

| Token | Light | Dark | Usage |
|-------|-------|------|-------|
| **Background** | `#ffffff` | `#0a0a0a` | Page background |
| **Layout Background** | `#fafafa` | `#18181b` | App shell / sidebar backdrop |
| **Foreground** | `#0a0a0a` | `#fafafa` | Primary text |
| **Text** | `#2c2f33` | `#ffffff` | Body text (slightly softer than foreground) |
| **Chat Background** | `#fafafa` | `#26262b` | Chat panel background |
| **Card** | `#ffffff` | `#0a0a0a` | Card surfaces |
| **Card Foreground** | `#0a0a0a` | `#fafafa` | Text on cards |
| **Popover** | `#ffffff` | `#0a0a0a` | Popover / dropdown surfaces |
| **Popover Foreground** | `#0a0a0a` | `#fafafa` | Text inside popovers |
| **Sidebar** | `#f4f4f5` | `#18181b` | Sidebar background |

#### Neutral Colors

| Token | Light | Dark | Usage |
|-------|-------|------|-------|
| **Secondary** | `#f5f5f5` | `#262626` | Secondary buttons, muted tags |
| **Secondary Foreground** | `#171717` | `#fafafa` | Text on secondary backgrounds |
| **Muted** | `#f5f5f5` | `#262626` | Disabled / placeholder surfaces |
| **Muted Foreground** | `#737373` | `#a3a3a3` | Placeholder text, captions |
| **Border** | `#e5e5e5` | `#262626` | Dividers, input borders |
| **Input** | `#e5e5e5` | `#262626` | Form field borders |
| **Ring** | `#0a0a0a` | `#d4d4d4` | Focus rings |

#### Status Colors

| Token | Light | Dark | Usage |
|-------|-------|------|-------|
| **Destructive** | `#ef4444` | `#7f1d1d` | Errors, delete actions |
| **Destructive Foreground** | `#fafafa` | `#fafafa` | Text on destructive elements |
| **Success** | `#16a34a` | — | Success toasts (Sonner) |
| **Warning** | `#ea580c` | — | Warning toasts (Sonner) |
| **Error** | `#dc2626` | — | Error toasts (Sonner) |

#### Chart Palette

| Token | Light | Dark |
|-------|-------|------|
| **Chart 1** | `#e88c5a` | `#2a6fdf` |
| **Chart 2** | `#2a9d8f` | `#2dbf8f` |
| **Chart 3** | `#264653` | `#e6992e` |
| **Chart 4** | `#e9c46a` | `#b366d9` |
| **Chart 5** | `#f4a261` | `#e62e6b` |

#### Ory Auth Specific

The authentication UI (Ory Elements) uses hard-coded overrides to match the AgentArea brand:

| Element | Color |
|---------|-------|
| Submit button | `#2252b3` |
| Submit hover | `#1a3f8a` |
| Links | `#2252b3` |
| Link hover | `#1a3f8a` |
| Input focus border | `#2252b3` |
| Decorative crosses | `#2252b3` |
| Divider (light) | `#e2e8f0` |
| Divider (dark) | `#64748b` |

---

### Typography

| Property | Value |
|----------|-------|
| **Font Family** | `Inter` (weights: 300, 400, 500, 600, 700) |
| **Base Size** | Browser default (`16px`) |
| **Input Size** | `13px` |

#### Heading Scale

| Level | Mobile | Desktop | Weight |
|-------|--------|---------|--------|
| **H1** | `1.25rem` (20px) | `1.5rem` (24px) | Bold (`700`) |
| **H2** | `1.125rem` (18px) | `1.25rem` (20px) | Semibold (`600`) |
| **H3** | `16px` | `16px` | Medium (`500`) |

#### Utility Text Styles

| Class | Size | Weight | Color |
|-------|------|--------|-------|
| `.note` | `0.75rem` (12px) | Normal | `zinc-400` |
| `.form-error` | `0.75rem` (12px) | Normal | `red-500` |
| `.small-link` | `0.75rem` (12px) | Medium | Primary / Accent |

---

### Spacing

| Context | Value |
|---------|-------|
| **Base radius** | `0.5rem` (8px) |
| **Content section gap** | `1rem` (16px) vertical, `20px`–`25px` bottom padding |
| **Main content padding** | `16px` horizontal, `20px`–`28px` vertical |
| **Card padding** | `14px` (mobile) / `16px` (tablet) / `18px` (desktop) |
| **Form gap** | `1.25rem` (20px) vertical |

---

### Border Radius

| Token | Value |
|-------|-------|
| `--radius` | `0.5rem` (8px) |
| `rounded-lg` | `8px` |
| `rounded-md` | `6px` |
| `rounded-sm` | `4px` |

---

### Shadows

| Token | Value | Usage |
|-------|-------|-------|
| **Card** | `0 2px 10px rgba(0,0,0,0.04)` | Default card elevation |
| **Card Hover** | `shadow-md` (Tailwind) | Card hover state |
| **Inner Strong** | `inset 0 4px 10px rgba(139,92,246,0.2), inset 0 2px 6px rgba(59,130,246,0.2)` | Special inner glow |
| **Inner Strong MD** | `inset 0 4px 12px rgba(0,0,0,0.15)` | Medium inset shadow |
| **Inner Strong LG** | `inset 0 6px 16px rgba(0,0,0,0.12)` | Large inset shadow |

---

### Transitions

| Context | Duration | Easing |
|---------|----------|--------|
| Cards | `300ms` | Default Tailwind ease |
| Links / small interactions | `300ms` | Default Tailwind ease |
| Inputs (Ory) | `200ms` | `ease` |
| Accordions | `200ms` | `ease-out` |

---

## Themes

### Light Mode

```css
:root {
  --layout-background: 0 0% 98%;
  --background: 0 0% 100%;
  --foreground: 0 0% 3.9%;
  --card: 0 0% 100%;
  --card-foreground: 0 0% 3.9%;
  --popover: 0 0% 100%;
  --popover-foreground: 0 0% 3.9%;
  --sidebar: 240 10% 96%;
  --text: 220 9% 19%;
  --chat-background: 0 0 98%;

  --primary: 225 66% 39%;
  --primary-foreground: 0 0% 100%;
  --primary-hover: 234 100% 74.7%;

  --accent: 233 100% 70.8%;
  --accent-foreground: 0 0% 100%;
  --accent-hover: 227 31.7% 51.2%;

  --secondary: 0 0% 96.1%;
  --secondary-foreground: 0 0% 9%;
  --muted: 0 0% 96.1%;
  --muted-foreground: 0 0% 45.1%;
  --destructive: 0 84.2% 60.2%;
  --destructive-foreground: 0 0% 98%;
  --border: 0 0% 89.8%;
  --input: 0 0% 89.8%;
  --ring: 0 0% 3.9%;
  --radius: 0.5rem;
}
```

### Dark Mode

```css
.dark {
  --layout-background: 240 5.9% 10%;
  --background: 0 0% 3.9%;
  --foreground: 0 0% 98%;
  --card: 0 0% 3.9%;
  --card-foreground: 0 0% 98%;
  --popover: 0 0% 3.9%;
  --popover-foreground: 0 0% 98%;
  --text: 0 0% 100%;
  --chat-background: 240 4% 16%;

  --primary: 225 60% 54%;
  --primary-foreground: 0 0% 100%;
  --primary-hover: 225 60% 60%;

  --accent: 233 100% 70.8%;
  --accent-foreground: 224 40% 74%;
  --accent-hover: 227 31.7% 51.2%;

  --secondary: 0 0% 14.9%;
  --secondary-foreground: 0 0% 98%;
  --muted: 0 0% 14.9%;
  --muted-foreground: 0 0% 63.9%;
  --destructive: 0 62.8% 30.6%;
  --destructive-foreground: 0 0% 98%;
  --border: 0 0% 14.9%;
  --input: 0 0% 14.9%;
  --ring: 0 0% 83.1%;
}
```

---

## Component Primitives

### Card

```
Base:
  rounded-md
  bg-white dark:bg-zinc-800
  border border-zinc-200 dark:border-zinc-700
  p-[14px] → p-[18px] (responsive)
  transition-all duration-300
  hover:shadow-md
```

### Button

**Primary (Ory override):**
```
  bg-[#2252b3] hover:bg-[#1a3f8a]
  text-white
  rounded-[4px]
  h-[40px]
  w-full
```

**Standard shadcn primary:**
```
  bg-primary text-primary-foreground
  hover:bg-primary-hover
```

### Input

```
  height: 40px
  border-radius: 4px
  border: 1px solid hsl(var(--border))
  focus: border-[#2252b3] (Ory)
  focus: ring-ring (standard)
  font-size: 13px–15px
```

### Label

```
  flex items-center gap-[5px]
  font-size: 0.9375rem
  mb-[0.125rem]
```

### Link

```
  text-xs text-primary dark:text-accent-foreground
  flex items-center gap-2
  hover:text-accent
  transition-all duration-300
```

### Loader

```
  .loader-primary  → color: hsl(var(--primary))
  .loader-light    → color: white
  Sizes:
    .loader-small   → 3px
    .loader-medium  → 6px
    .loader-large   → 8px
```

---

## Usage Guidelines

### Tailwind Classes

Always prefer Tailwind utility classes over arbitrary values. When a value is not in the default scale, add it to `tailwind.config.ts` under `theme.extend`.

**Do:**
```tsx
<div className="bg-primary text-primary-foreground rounded-lg shadow-card" />
```

**Avoid:**
```tsx
<div style={{ backgroundColor: '#2252b3' }} />
```

### CSS Variables

Use `hsl(var(--token))` for any color that must respect the current theme. Custom components should expose their own CSS variables if they need to be themeable.

### Theming

The app uses `next-themes` with `attribute="class"`. Toggle between `light`, `dark`, and `system`. Always test new components in both modes.

### Adding New Tokens

1. Define the variable in `globals.css` under both `:root` and `.dark`.
2. Map it in `tailwind.config.ts` under `theme.extend.colors` (or `spacing`, etc.).
3. Document the token in this file under the relevant section.

---

## Patterns & Conventions

The token reference above is the *vocabulary*. This section is the
*grammar* — how the existing pages compose those tokens. Read before
adding a new page or visual component, and grep an existing file
referenced here when in doubt.

### Page shell

Every page renders inside `<ContentBlock>` (`src/components/ContentBlock`).
Pick one of two header shapes:

- `{ title, description?, backLink?, controls? }` — for nested resource
  pages.
- `{ breadcrumb: [{label, href?}], description?, controls? }` — for
  index pages and dashboards.

`<ContentBlock>` already wraps in `flex h-full flex-col overflow-hidden`
— **do not double-wrap**. Children either go directly inside, or wrap
in a single `<div className="main-content">` (`h-full space-y-2
overflow-auto px-4 py-5`) for scrollable lists / dashboards.

For RSC data, lazy-load with `<Suspense>` + a small `LoadingSpinner`:

```tsx
<Suspense fallback={<div className="flex h-32 items-center justify-center"><LoadingSpinner /></div>}>
  <FooData />
</Suspense>
```

Reference: `src/app/(main)/inbox/page.tsx` (minimal RSC page),
`src/app/(main)/agents/page.tsx` (page with subheader + controls).

### Surfaces — pick the right one

There are **two** surface kinds. They look similar; they behave
differently. The difference matters for affordance.

#### a) Clickable list/grid card
Reach for the `<Card>` atom (`ui/card.tsx`). It composes `card
card-shadow` from `globals.css`, which **bakes in `cursor-pointer` and
hover-shadow**. Use it where the whole card is a link.

```tsx
<Link href={`/agents/${agent.id}`}>
  <Card className="group h-full p-0 hover:-translate-y-0.5 active:scale-[0.99] hover:border-primary/20">
    …
  </Card>
</Link>
```

Reference: `src/app/(main)/agents/components/AgentCard.tsx` is the
flagship pattern.

#### b) Static dashboard widget / panel
**Do not use `<Card>`** — its `cursor-pointer` makes the user think the
panel itself is clickable. Build a panel from raw tokens:

```tsx
<section className="rounded-md border border-zinc-200 bg-white card-shadow dark:border-zinc-700 dark:bg-zinc-800">
  <header className="flex items-center justify-between border-b border-zinc-200 px-4 py-3 dark:border-zinc-700">
    <h2 className="text-base font-semibold">Spend</h2>
    <span className="note">12% of cap</span>
  </header>
  <div className="space-y-4 p-4">…</div>
</section>
```

Why this shape:
- Same surface tokens as `.card` (white / zinc-800, zinc border).
- `.card-shadow` reuses the documented elevation.
- Explicit `<header>` strip mirrors `ContentBlock` header style and
  gives the panel an obvious title region.
- No `cursor-pointer`, no hover-lift — affordance matches the static
  widget intent.

#### c) List rows inside a panel
Use `.card-item` (`rounded-md border border-border pr-[7px]
transition-colors`). Stack them with `space-y-1` or `space-y-2`. Keep
hover subtle: `hover:bg-muted/40`. Don't apply `.card-shadow` to inner
rows.

### Tables

Project convention is plain `<table>` with these rules — no heavy table
library:

- Wrapper: `overflow-x-auto`.
- `<thead>` row: `text-xs uppercase tracking-wide text-muted-foreground`,
  cells `pb-2 font-medium`.
- Body cell font: default (`text-sm`).
- Numeric cells: `tabular-nums text-right`. Always.
- Row hover: `hover:bg-muted/40`.
- Row separator: `border-t border-zinc-200 dark:border-zinc-700`.
- Cell padding: `py-2 pr-3`.
- Truncate long strings: wrap `<td>` with `max-w-[260px] truncate`.

Status emphasis: only the **number** turns red, never the row
(`<span className={count > 0 ? "text-red-600" : undefined}>`).

### Empty states

For full-page or full-section empty: `<EmptyState>` from
`src/components/EmptyState/`. Provide `title`, `description`,
`iconsType`, optional `action`.

For *inline* empty inside a panel sub-section (e.g. blockers panel
with nothing waiting), a single muted line is enough — no decorations:

```tsx
<div className="py-6 text-center text-sm text-muted-foreground">
  No blockers — fleet healthy.
</div>
```

Don't render an EmptyState inside a panel sub-section — the icon and
heading are too heavy for that scale.

### Status / banners

Avoid building a status palette. The existing patterns:

- **Inline destructive accent** (e.g. failure count): only the
  number/value turns `text-red-600`; surrounding row stays neutral.
- **Pills / tags** (e.g. A2UI marker): `rounded-full bg-blue-100
  px-2 py-0.5 text-[10px] font-medium text-blue-700` (and dark
  counterpart).
- **Banners — use sparingly**, one per page max. Pattern:

```tsx
<div className="flex items-start gap-2 rounded-md border border-amber-300
                bg-amber-50 p-3 text-sm text-amber-900
                dark:border-amber-700/60 dark:bg-amber-900/20 dark:text-amber-200">
  <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
  <div>
    <div className="font-medium">Approaching monthly cap</div>
    <div className="text-xs">87% used. Raise the cap or trim spend.</div>
  </div>
</div>
```

Don't add toast notifications for system events (project preference) —
surface state in-place via banners or inline text.

### Buttons in headers

Header CTA pattern (matches `agents/page.tsx`):

```tsx
<Button className="shrink-0 gap-2" size="xs">
  <Plus className="h-5 w-5" />
  Deploy new agent
</Button>
```

`size="xs"` is the dense toolbar button (24px). Default size (36px) is
for in-form CTAs. Loading state goes through `isLoading` prop — the
button renders the spinner; don't hand-roll.

### Icons

- Library: `lucide-react`. Don't mix with other icon sets.
- Sizes: `h-4 w-4` inline with text; `h-5 w-5` inside buttons; `h-4
  w-4` for section header icons next to a title.
- Buttons with icons get `gap-2`; section headers with icons get
  `gap-2`.

### Numerics

- Currency / counts → `tabular-nums` so digit columns align.
- Currency: `Intl.NumberFormat("en-US", { style: "currency", currency:
  "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 })`.
  For very small values (< $0.01), expand to 4 fraction digits so the
  number isn't misleadingly rendered as `$0.00`.
- Relative time: short forms `just now`, `Nm ago`, `Nh ago`, `Nd ago`.
  Don't use a heavy date library if you don't already need one.

### Internationalization

- Strings live in `messages/en.json` + `messages/ru.json` under section
  keys (e.g. `Metadata`, `Common`, `AgentsPage`).
- Sidebar items have a `titleKey` matched against `Sidebar.*` keys.
- **Add a new key to *both* locale files in the same change**. A
  missing key falls back to the literal `Section.key` string —
  visually broken.
- New page metadata `title` is plain English in the file but rendered
  via `getTranslations`.

### Loading

`LoadingSpinner` from `src/components/LoadingSpinner.tsx`. For RSC
boundaries, use the small spinner pattern from the page-shell section
above. Don't render large skeleton stacks — the existing UX is
"spinner → content"; matches the dense-info aesthetic.

### Dark mode is mandatory

Every surface gets a `dark:` counterpart. Common pairs in this codebase:

| Light | Dark |
|---|---|
| `bg-white` | `dark:bg-zinc-800` (panel) or `dark:bg-zinc-900` (deeper card) |
| `border-zinc-200` | `dark:border-zinc-700` |
| `text-zinc-900` | `dark:text-zinc-100` |
| `text-zinc-400` | (already neutral) |
| `bg-muted/40` / `bg-muted` | (already token-driven) |

If you change a surface, change both modes in the same edit. Never
ship a "we'll do dark mode later" component.

### Anti-patterns

- Using `<Card>` atom for a static dashboard widget — it forces
  `cursor-pointer` and hover-lift on a non-clickable element. Use the
  panel pattern in §"Surfaces" instead.
- Inline `style={{ … }}` for spacing or color — breaks the token
  system. Allowed only for animated transforms or inline svg patterns.
- Hardcoding hex in component code — always use tokens
  (`bg-primary`, `text-muted-foreground`) or the conventional
  `zinc-*` / `red-*` shorthands.
- Toast notifications for system events.
- Custom `h1` / `h2` sizing per page — `globals.css` already defines
  the scale.
- Hover-translate / scale on non-clickable elements — confuses
  affordance.
- Mixing icon libraries.
- Skipping i18n keys "for now".

### New-component checklist

- [ ] Uses tokens (`bg-card`, `text-muted-foreground`, etc.) for surfaces.
- [ ] Light + dark variants present.
- [ ] No new global CSS unless added to `globals.css` `@layer base|utilities`.
- [ ] Numeric data uses `tabular-nums`.
- [ ] If clickable, hover/transition matches the card pattern; if
      not clickable, no `cursor-pointer`.
- [ ] Empty state goes through `<EmptyState>` (or muted inline copy
      for panel sub-sections).
- [ ] Lucide icon, sized `h-4 w-4` or `h-5 w-5` inline with text.
- [ ] Strings keyed in `messages/en.json` and `messages/ru.json`.
- [ ] Page-level component wrapped in `<ContentBlock>`.
- [ ] Surface choice is intentional — clickable card vs static panel.

### References

- `src/components/ContentBlock/ContentBlock.tsx` — page shell.
- `src/components/ui/card.tsx` + `globals.css` `.card`/`.card-shadow`/
  `.card-item` — surface atoms.
- `src/components/ui/button.tsx` — variants reference.
- `src/app/(main)/agents/components/AgentCard.tsx` — flagship clickable
  card pattern.
- `src/app/(main)/inbox/page.tsx` — minimal RSC page pattern.
- `src/app/(main)/dashboard/components/*.tsx` — static panel pattern
  (Spend, Blockers, Agent rows).
- `src/app/globals.css` — tokens, base styles, utility classes.

---

*Last updated: 2026-05-05*
