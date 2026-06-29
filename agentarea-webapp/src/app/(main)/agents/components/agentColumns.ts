/**
 * Shared layout metadata for the agents list. Both the real `Table` (in
 * `AgentsList`) and the loading `TableSkeleton` (in `AgentsSkeleton`) derive
 * from this, so the header labels, order, and cell widths can never drift apart.
 *
 * Only layout-relevant fields live here — the actual cell `render` functions
 * stay in `AgentsList`, keyed by `accessor`.
 */
export type AgentColumnMeta = {
  accessor: string;
  /** Translation key in the `AgentsPage` namespace. */
  labelKey: string;
  cellClassName?: string;
  /** Width/shape of the skeleton bar for this column while loading. */
  barClassName?: string;
};

export const AGENT_COLUMNS: AgentColumnMeta[] = [
  { accessor: "name", labelKey: "name", barClassName: "h-4 w-32" },
  {
    accessor: "description",
    labelKey: "description",
    cellClassName: "max-w-[300px]",
    barClassName: "h-3 w-48",
  },
  { accessor: "model_info", labelKey: "model", barClassName: "h-5 w-24 rounded-full" },
  { accessor: "active_task_count", labelKey: "activeTasks", barClassName: "h-4 w-6" },
  { accessor: "tools_config", labelKey: "tools", barClassName: "h-6 w-16" },
];

/** Grid classes shared by the real agents grid and its skeleton. */
export const AGENTS_GRID_CLASS =
  "grid grid-cols-1 gap-2 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5";
