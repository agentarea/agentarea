import type { McpUiStyles } from "@modelcontextprotocol/ext-apps";

/**
 * AgentArea design tokens (agentarea-webapp/src/app/globals.css) expressed as
 * the standard MCP Apps style variables. Each color is `light-dark(light,
 * dark)`, so one table serves both themes: the theme itself travels separately
 * as `hostContext.theme`, which sets `color-scheme` in the app.
 *
 * The host page applies the same table to itself, so the page and every app
 * inside it draw from one source.
 */
export const AGENTAREA_STYLE_VARIABLES: McpUiStyles = {
  "--color-background-primary": "light-dark(#ffffff, #0a0a0a)",
  "--color-background-secondary": "light-dark(#fafafa, #18181b)",
  "--color-background-tertiary": "light-dark(#f5f5f5, #262626)",
  "--color-background-inverse": "light-dark(#0a0a0a, #fafafa)",
  "--color-background-ghost": "transparent",
  "--color-background-info": "light-dark(rgb(34 82 179 / 0.08), rgb(68 115 218 / 0.16))",
  "--color-background-danger": "light-dark(#fef2f2, rgb(127 29 29 / 0.35))",
  "--color-background-success": "light-dark(#f0fdf4, rgb(22 163 74 / 0.16))",
  "--color-background-warning": "light-dark(#fff7ed, rgb(234 88 12 / 0.16))",
  "--color-background-disabled": "light-dark(#f5f5f5, #171717)",

  "--color-text-primary": "light-dark(#0a0a0a, #fafafa)",
  "--color-text-secondary": "light-dark(#737373, #a3a3a3)",
  "--color-text-tertiary": "light-dark(#a3a3a3, #737373)",
  "--color-text-inverse": "light-dark(#fafafa, #0a0a0a)",
  "--color-text-ghost": "light-dark(#a3a3a3, #525252)",
  "--color-text-info": "light-dark(#2252b3, #4473da)",
  "--color-text-danger": "light-dark(#dc2626, #f87171)",
  "--color-text-success": "light-dark(#16a34a, #4ade80)",
  "--color-text-warning": "light-dark(#ea580c, #fb923c)",
  "--color-text-disabled": "light-dark(#a3a3a3, #525252)",

  "--color-border-primary": "light-dark(#e5e5e5, #262626)",
  "--color-border-secondary": "light-dark(#d4d4d4, #404040)",
  "--color-border-tertiary": "light-dark(#f5f5f5, #1f1f1f)",
  "--color-border-inverse": "light-dark(#0a0a0a, #fafafa)",
  "--color-border-ghost": "transparent",
  "--color-border-info": "light-dark(rgb(34 82 179 / 0.3), rgb(68 115 218 / 0.4))",
  "--color-border-danger": "light-dark(#fecaca, #7f1d1d)",
  "--color-border-success": "light-dark(#bbf7d0, #14532d)",
  "--color-border-warning": "light-dark(#fed7aa, #7c2d12)",
  "--color-border-disabled": "light-dark(#e5e5e5, #262626)",

  "--color-ring-primary": "light-dark(#0a0a0a, #d4d4d4)",
  "--color-ring-secondary": "light-dark(#737373, #a3a3a3)",
  "--color-ring-inverse": "light-dark(#fafafa, #0a0a0a)",
  "--color-ring-info": "light-dark(#2252b3, #4473da)",
  "--color-ring-danger": "light-dark(#ef4444, #f87171)",
  "--color-ring-success": "light-dark(#16a34a, #4ade80)",
  "--color-ring-warning": "light-dark(#ea580c, #fb923c)",

  "--font-sans": "Inter, ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif",
  "--font-mono": "ui-monospace, 'SF Mono', Menlo, Consolas, monospace",

  "--font-weight-normal": "400",
  "--font-weight-medium": "500",
  "--font-weight-semibold": "600",
  "--font-weight-bold": "700",

  "--font-text-xs-size": "0.75rem",
  "--font-text-sm-size": "0.875rem",
  "--font-text-md-size": "1rem",
  "--font-text-lg-size": "1.125rem",

  "--font-heading-xs-size": "0.75rem",
  "--font-heading-sm-size": "0.875rem",
  "--font-heading-md-size": "1rem",
  "--font-heading-lg-size": "1.125rem",
  "--font-heading-xl-size": "1.25rem",
  "--font-heading-2xl-size": "1.5rem",
  "--font-heading-3xl-size": "1.875rem",

  "--font-text-xs-line-height": "1.333",
  "--font-text-sm-line-height": "1.429",
  "--font-text-md-line-height": "1.5",
  "--font-text-lg-line-height": "1.556",

  "--font-heading-xs-line-height": "1.333",
  "--font-heading-sm-line-height": "1.429",
  "--font-heading-md-line-height": "1.5",
  "--font-heading-lg-line-height": "1.4",
  "--font-heading-xl-line-height": "1.4",
  "--font-heading-2xl-line-height": "1.333",
  "--font-heading-3xl-line-height": "1.2",

  "--border-radius-xs": "2px",
  "--border-radius-sm": "4px",
  "--border-radius-md": "6px",
  "--border-radius-lg": "8px",
  "--border-radius-xl": "12px",
  "--border-radius-full": "9999px",

  "--border-width-regular": "1px",

  "--shadow-hairline": "0 1px 2px 0 rgb(0 0 0 / 0.04)",
  "--shadow-sm": "0 2px 10px rgb(0 0 0 / 0.04)",
  "--shadow-md": "0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)",
  "--shadow-lg": "0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)",
};
