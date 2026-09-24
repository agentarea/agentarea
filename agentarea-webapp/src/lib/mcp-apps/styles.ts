import type { McpUiStyles } from "@modelcontextprotocol/ext-apps";

export const MCP_UI_STYLE_TOKEN_NAMES = [
  "--background",
  "--foreground",
  "--card",
  "--card-foreground",
  "--muted",
  "--muted-foreground",
  "--primary",
  "--primary-foreground",
  "--destructive",
  "--destructive-foreground",
  "--border",
  "--ring",
  "--chart-2",
  "--chart-4",
  "--font-sans",
  "--font-mono",
] as const;

export type CssTokenValues = Readonly<Record<string, string>>;

const FALLBACK_SANS =
  "Inter, ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif";
const FALLBACK_MONO = "ui-monospace, 'SF Mono', Menlo, Consolas, monospace";

function tokenValue(tokens: CssTokenValues, name: string): string | undefined {
  const value = tokens[name]?.trim();
  return value || undefined;
}

function hslToken(
  tokens: CssTokenValues,
  name: string,
  fallback: string,
  alpha?: number
): string {
  const value = tokenValue(tokens, name) ?? fallback;
  const triplet =
    value.startsWith("hsl(") && value.endsWith(")")
      ? value.slice(4, -1)
      : value;
  return alpha === undefined ? `hsl(${triplet})` : `hsl(${triplet} / ${alpha})`;
}

function fontToken(
  tokens: CssTokenValues,
  name: string,
  fallback: string
): string {
  return tokenValue(tokens, name) ?? fallback;
}

/**
 * Convert a snapshot of AgentArea CSS custom properties into MCP Apps host
 * style variables. Keeping the snapshot as an argument makes this mapping
 * deterministic and independent of the DOM, while the caller can refresh it
 * whenever the resolved theme changes.
 */
export function mcpUiStyleVariablesFromTokens(
  tokens: CssTokenValues
): McpUiStyles {
  const background = hslToken(tokens, "--background", "hsl(0 0% 100%)");
  const foreground = hslToken(tokens, "--foreground", "hsl(0 0% 3.9%)");
  const card = hslToken(tokens, "--card", background);
  const muted = hslToken(tokens, "--muted", "hsl(0 0% 96.1%)");
  const mutedForeground = hslToken(
    tokens,
    "--muted-foreground",
    "hsl(0 0% 45.1%)"
  );
  const primary = hslToken(tokens, "--primary", "hsl(221 67% 42%)");
  const destructive = hslToken(tokens, "--destructive", "hsl(0 84.2% 60.2%)");
  const border = hslToken(tokens, "--border", "hsl(0 0% 89.8%)");
  const ring = hslToken(tokens, "--ring", foreground);
  const success = hslToken(tokens, "--chart-2", "hsl(173 58% 39%)");
  const warning = hslToken(tokens, "--chart-4", "hsl(43 74% 66%)");

  return {
    "--color-background-primary": background,
    "--color-background-secondary": card,
    "--color-background-tertiary": muted,
    "--color-background-inverse": foreground,
    "--color-background-ghost": "transparent",
    "--color-background-info": hslToken(tokens, "--primary", primary, 0.08),
    "--color-background-danger": hslToken(
      tokens,
      "--destructive",
      destructive,
      0.08
    ),
    "--color-background-success": hslToken(tokens, "--chart-2", success, 0.08),
    "--color-background-warning": hslToken(tokens, "--chart-4", warning, 0.08),
    "--color-background-disabled": muted,

    "--color-text-primary": foreground,
    "--color-text-secondary": mutedForeground,
    "--color-text-tertiary": mutedForeground,
    "--color-text-inverse": background,
    "--color-text-ghost": mutedForeground,
    "--color-text-info": primary,
    "--color-text-danger": destructive,
    "--color-text-success": success,
    "--color-text-warning": warning,
    "--color-text-disabled": mutedForeground,

    "--color-border-primary": border,
    "--color-border-secondary": border,
    "--color-border-tertiary": muted,
    "--color-border-inverse": foreground,
    "--color-border-ghost": "transparent",
    "--color-border-info": hslToken(tokens, "--primary", primary, 0.3),
    "--color-border-danger": hslToken(
      tokens,
      "--destructive",
      destructive,
      0.3
    ),
    "--color-border-success": hslToken(tokens, "--chart-2", success, 0.3),
    "--color-border-warning": hslToken(tokens, "--chart-4", warning, 0.3),
    "--color-border-disabled": muted,

    "--color-ring-primary": ring,
    "--color-ring-secondary": mutedForeground,
    "--color-ring-inverse": background,
    "--color-ring-info": primary,
    "--color-ring-danger": destructive,
    "--color-ring-success": success,
    "--color-ring-warning": warning,

    "--font-sans": fontToken(tokens, "--font-sans", FALLBACK_SANS),
    "--font-mono": fontToken(tokens, "--font-mono", FALLBACK_MONO),
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
    "--shadow-md":
      "0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)",
    "--shadow-lg":
      "0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)",
  };
}
