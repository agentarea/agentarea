/**
 * Shared card-grid density classes for list pages. Both a page's real card grid
 * and its loading skeleton import from here, so the two can never drift apart.
 */

// agents, tasks — 5 columns at 2xl, no `sm` breakpoint.
export const CARD_GRID_WIDE =
  "grid grid-cols-1 gap-2 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5";

// triggers, connections (MCP), provider-configs — 5 columns at xl, denser `sm`.
export const CARD_GRID_DENSE =
  "grid grid-cols-1 gap-2 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5";
