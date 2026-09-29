interface HasEndpoints {
  id: string;
  source: string;
  target: string;
}

export function computeHighlightSets<E extends HasEndpoints>(
  highlightId: string | null | undefined,
  edges: E[]
): { nodes: Set<string>; edges: Set<string> } | null {
  if (!highlightId) return null;
  const out: Record<string, string[]> = {};
  const inn: Record<string, string[]> = {};
  for (const e of edges) {
    (out[e.source] ||= []).push(e.target);
    (inn[e.target] ||= []).push(e.source);
  }
  const nodeSet = new Set<string>([highlightId]);
  const edgeSet = new Set<string>();
  const walk = (start: string, adj: Record<string, string[]>) => {
    const queue = [start];
    while (queue.length) {
      const cur = queue.shift();
      if (cur === undefined) continue;
      for (const next of adj[cur] || []) {
        if (!nodeSet.has(next)) {
          nodeSet.add(next);
          queue.push(next);
        }
      }
    }
  };
  walk(highlightId, out);
  walk(highlightId, inn);
  for (const e of edges) {
    if (nodeSet.has(e.source) && nodeSet.has(e.target)) edgeSet.add(e.id);
  }
  return { nodes: nodeSet, edges: edgeSet };
}
