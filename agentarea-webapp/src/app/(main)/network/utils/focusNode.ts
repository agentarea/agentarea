import type { NetworkNodeData } from "../types";

/**
 * Resolve a `?focus=` parameter against the loaded topology.
 *
 * Surfaces that hand off to the network — the trigger form's execution panel,
 * a task composer — know the kind and id of what they are pointing at, not
 * which node the graph built for it. They spell that as `type:id`; the type
 * is carried so a stale link opens the graph unfocused rather than landing on
 * whatever else happens to share the id.
 */
export function findFocusedNode(
  nodes: NetworkNodeData[],
  focus: string | null
): NetworkNodeData | null {
  if (!focus) return null;

  const separator = focus.indexOf(":");
  if (separator <= 0) return null;

  const type = focus.slice(0, separator);
  const id = focus.slice(separator + 1);
  if (!id) return null;

  return (
    nodes.find((node) => node.type === type && node.id === id) ?? null
  );
}
