"use client";

import { useEffect, useMemo, useState } from "react";
import { Grid2x2, Plus, Share2, Zap } from "lucide-react";
import { cn } from "@/lib/utils";
import type {
  AccessControlGraph,
  AccessControlResolveResponse,
  AccessControlRelationshipsResponse,
  SkillCollection,
} from "@/types/access-control";
import GraphPane from "./GraphPane";
import ResolveAccessCard from "./ResolveAccessCard";
import ToolGrantCard from "./ToolGrantCard";
import { layoutGraph } from "./graph-layout";
import styles from "./access-control.module.css";

type ViewMode = "matrix" | "relationships";

interface AccessControlExplorerProps {
  graph: AccessControlGraph;
  relationships: AccessControlRelationshipsResponse;
  collections: SkillCollection[];
  currentUserId: string | null;
}

export default function AccessControlExplorer({
  graph,
  relationships,
  collections,
  currentUserId,
}: AccessControlExplorerProps) {
  const [view, setView] = useState<ViewMode>("relationships");

  const agents = useMemo(
    () => graph.nodes.filter((n) => n.kind === "agent"),
    [graph.nodes]
  );

  // Objects for the resolver: prefer skill collections, fall back to collection nodes.
  const objects = useMemo(() => {
    if (collections.length > 0) {
      return collections.map((c) => ({ id: c.id, name: c.name }));
    }
    return graph.nodes
      .filter((n) => n.kind === "collection" || n.kind === "mcp")
      .map((n) => ({ id: n.id, name: n.name }));
  }, [collections, graph.nodes]);

  const [subjectId, setSubjectId] = useState<string>(agents[0]?.id ?? "");
  const [objectId, setObjectId] = useState<string>(objects[0]?.id ?? "");
  const [result, setResult] = useState<AccessControlResolveResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const layout = useMemo(() => layoutGraph(graph), [graph]);

  // Resolve access whenever the subject or object changes.
  useEffect(() => {
    if (!graph.enabled || !subjectId || !objectId) {
      setResult(null);
      return;
    }

    let cancelled = false;
    const controller = new AbortController();

    async function run() {
      setLoading(true);
      setError(null);
      try {
        const response = await fetch("/api/proxy/v1/access-control/resolve", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            subject_id: `Agent:${subjectId}`,
            resource_kind: "skill",
            resource_id: objectId,
          }),
          signal: controller.signal,
        });
        if (!response.ok) {
          throw new Error(`Resolve failed (${response.status})`);
        }
        const data = (await response.json()) as AccessControlResolveResponse;
        if (!cancelled) {
          setResult(data);
        }
      } catch (e) {
        if (cancelled || (e instanceof Error && e.name === "AbortError")) {
          return;
        }
        setError(e instanceof Error ? e.message : "Failed to resolve access");
        setResult(null);
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    run();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [graph.enabled, subjectId, objectId]);

  // Compute graph highlight from the resolved derivation paths.
  const { highlightedNodeIds, highlightedEdgeKeys } = useMemo(() => {
    const nodes = new Set<string>();
    const edges = new Set<string>();
    if (result?.allowed) {
      for (const path of result.paths) {
        path.hops.forEach((hop, index) => {
          nodes.add(hop.id);
          const next = path.hops[index + 1];
          if (next) {
            edges.add(`${hop.id}>${next.id}`);
          }
        });
      }
    }
    return { highlightedNodeIds: nodes, highlightedEdgeKeys: edges };
  }, [result]);

  const handleSelectNode = (nodeId: string) => {
    const node = graph.nodes.find((n) => n.id === nodeId);
    if (!node) return;
    if (node.kind === "agent") {
      setSubjectId(nodeId);
      return;
    }
    // Selecting a collection/team-style node focuses one of its member agents.
    const memberEdge = graph.edges.find(
      (e) =>
        e.to === nodeId &&
        graph.nodes.find((n) => n.id === e.from)?.kind === "agent"
    );
    if (memberEdge) {
      setSubjectId(memberEdge.from);
    }
  };

  if (!graph.enabled) {
    return (
      <div className={styles.explorer}>
        <div className={styles.body} style={{ display: "block" }}>
          <div className={styles.emptyPane}>
            <div style={{ maxWidth: 420 }}>
              <Share2
                className="mx-auto mb-3 h-8 w-8"
                style={{ color: "var(--access-muted2)" }}
              />
              <div
                style={{
                  fontWeight: 600,
                  fontSize: 14,
                  color: "hsl(var(--foreground))",
                  marginBottom: 6,
                }}
              >
                Access control is not enabled
              </div>
              <p style={{ lineHeight: 1.5 }}>
                Relationship-based access control (Ory Keto) is not configured
                for this workspace. Once enabled, agents, collections, and their
                relationship rules will appear here as an explorable graph.
              </p>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.explorer}>
      <div className={styles.tbar}>
        <div className={styles.seg} role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={view === "matrix"}
            className={cn(styles.segBtn, view === "matrix" && styles.segBtnOn)}
            onClick={() => setView("matrix")}
          >
            <Grid2x2 className="h-3.5 w-3.5 opacity-75" />
            Matrix
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={view === "relationships"}
            className={cn(
              styles.segBtn,
              view === "relationships" && styles.segBtnOn
            )}
            onClick={() => setView("relationships")}
          >
            <Share2 className="h-3.5 w-3.5 opacity-75" />
            Relationships
          </button>
        </div>
        <div className={styles.spacer} />
        <div className={styles.headline}>
          <b>{graph.stats.governed_skill_count.toLocaleString()}</b> skills
          governed by <b>{graph.stats.rule_count}</b> relationship rules ·{" "}
          <b>{graph.stats.direct_exception_count}</b> direct exceptions
        </div>
      </div>

      {view === "matrix" ? (
        <div className={styles.body} style={{ display: "block" }}>
          <div className={styles.emptyPane}>
            <div>
              <Grid2x2
                className="mx-auto mb-3 h-8 w-8"
                style={{ color: "var(--access-muted2)" }}
              />
              <div style={{ fontWeight: 600, color: "hsl(var(--foreground))" }}>
                Matrix view coming soon
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div className={styles.body}>
          <GraphPane
            layout={layout}
            selectedNodeId={subjectId}
            highlightedNodeIds={highlightedNodeIds}
            highlightedEdgeKeys={highlightedEdgeKeys}
            onSelectNode={handleSelectNode}
          />

          <aside className={styles.inspector}>
            <ResolveAccessCard
              agents={agents}
              objects={objects}
              subjectId={subjectId}
              objectId={objectId}
              onSubjectChange={setSubjectId}
              onObjectChange={setObjectId}
              result={result}
              loading={loading}
              error={error}
            />

            <div className={styles.card} id="access-control-add-relationship">
              <div className={styles.cardH}>
                <span className={styles.cardHIc}>
                  <Share2 className="h-4 w-4" />
                </span>
                <span className={styles.cardT}>Relationship rules</span>
                <span className={styles.countBadge}>{relationships.count}</span>
              </div>
              <div>
                {relationships.relationships.map((relationship, index) => (
                  <div
                    key={`${relationship.object}-${relationship.relation}-${relationship.subject}-${index}`}
                    className={cn(styles.relationship, relationship.direct && styles.relationshipDirect)}
                  >
                    <span className={styles.tk}>
                      <span className={styles.tkObj}>{relationship.object}</span>#
                      <span className={styles.tkRel}>{relationship.relation}</span>
                      <span className={styles.tkAt}>@</span>
                      <span className={styles.tkSub}>{relationship.subject}</span>
                    </span>
                    <span className={styles.fan}>
                      →{" "}
                      {relationship.direct
                        ? "direct"
                        : relationship.fanout != null
                          ? `${relationship.fanout.toLocaleString()} skills`
                          : "—"}
                    </span>
                  </div>
                ))}
                {relationships.relationships.length === 0 && (
                  <div
                    className={styles.verdictSub}
                    style={{ padding: 13 }}
                  >
                    No relationship rules defined yet.
                  </div>
                )}
              </div>
              <button type="button" className={styles.addrule}>
                <Plus className="h-3.5 w-3.5" />
                Add relationship
              </button>
            </div>

            <ToolGrantCard
              currentUserId={currentUserId}
              initialRelationships={relationships.relationships}
            />

            <div className={styles.scaleNote}>
              <span className={styles.scaleNoteIcon}>
                <Zap className="h-4 w-4" />
              </span>
              <div>
                <b>Why this scales.</b> Grants attach to collections, not
                individual skills. One rule on a collection governs every skill
                inside it; adding a skill to the collection grants it
                automatically — no per-skill work, even across thousands of
                skills.
              </div>
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}
