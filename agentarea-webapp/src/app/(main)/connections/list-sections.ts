import type { ConnectionState, ConnectionStateKey } from "./state";
import type { ConnectionUsage } from "./usage";

/**
 * Three buckets an operator scans in order: what is broken, what is carrying
 * load, and what is configured but inert.
 */
export type SectionKey = "attention" | "active" | "idle";

export type ListFilter = "all" | "attention" | "unused" | "unrestricted";

export const LIST_FILTERS: ListFilter[] = [
  "all",
  "attention",
  "unused",
  "unrestricted",
];

const SECTION_ORDER: SectionKey[] = ["attention", "active", "idle"];

const SECTION_OF: Record<ConnectionStateKey, SectionKey> = {
  failing: "attention",
  broken: "attention",
  unconfigured: "attention",
  working: "active",
  verifying: "active",
  ready: "idle",
};

// Within a section, the worse (or more active) verdict sorts first.
const STATE_SEVERITY: Record<ConnectionStateKey, number> = {
  failing: 0,
  broken: 1,
  unconfigured: 2,
  working: 0,
  verifying: 1,
  ready: 0,
};

export interface ConnectionListRow {
  name: string;
  _state: ConnectionState;
  _usage: ConnectionUsage | undefined;
}

export interface ConnectionSection<T extends ConnectionListRow> {
  key: SectionKey;
  rows: T[];
}

export interface ConnectionList<T extends ConnectionListRow> {
  counts: Record<ListFilter, number>;
  visibleRows: T[];
  sections: ConnectionSection<T>[];
  /** A single bucket needs no headings — they would label the whole list. */
  showSectionHeadings: boolean;
}

function matchesFilter(row: ConnectionListRow, filter: ListFilter): boolean {
  switch (filter) {
    case "attention":
      return SECTION_OF[row._state.key] === "attention";
    case "unused":
      return row._usage?.agents === 0;
    case "unrestricted":
      return row._usage?.grantedTools === null;
    default:
      return true;
  }
}

/**
 * Filter the connection list and split what remains into ordered sections.
 * Counts always describe the whole list, so a chip keeps its number while
 * another filter is active.
 */
export function buildConnectionList<T extends ConnectionListRow>(
  rows: T[],
  filter: ListFilter
): ConnectionList<T> {
  const counts = Object.fromEntries(
    LIST_FILTERS.map((key) => [
      key,
      rows.filter((row) => matchesFilter(row, key)).length,
    ])
  ) as Record<ListFilter, number>;

  const visibleRows = rows.filter((row) => matchesFilter(row, filter));

  const sections = SECTION_ORDER.map((key) => ({
    key,
    rows: visibleRows
      .filter((row) => SECTION_OF[row._state.key] === key)
      .sort(
        (a, b) =>
          STATE_SEVERITY[a._state.key] - STATE_SEVERITY[b._state.key] ||
          a.name.localeCompare(b.name)
      ),
  })).filter((section) => section.rows.length > 0);

  return {
    counts,
    visibleRows,
    sections,
    showSectionHeadings: sections.length > 1,
  };
}
