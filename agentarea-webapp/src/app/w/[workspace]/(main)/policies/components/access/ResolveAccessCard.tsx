"use client";

import { Check, ChevronDown, Search, Sparkles, X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { AccessControlNode, AccessControlResolveResponse } from "@/types/access-control";
import styles from "./access-control.module.css";

interface ResolveOption {
  id: string;
  name: string;
}

interface ResolveAccessCardProps {
  agents: AccessControlNode[];
  objects: ResolveOption[];
  subjectId: string;
  objectId: string;
  onSubjectChange: (id: string) => void;
  onObjectChange: (id: string) => void;
  result: AccessControlResolveResponse | null;
  loading: boolean;
  error: string | null;
}

function relClass(relation: string): string | undefined {
  switch (relation) {
    case "user":
      return styles.prelUser;
    case "editor":
      return styles.prelEditor;
    case "owner":
      return styles.prelOwner;
    case "connect":
      return styles.prelConnect;
    default:
      return undefined;
  }
}

function agentInitials(name: string): string {
  const letters = name
    .split(/[\s-]+/)
    .map((part) => part[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("");
  return (letters || name.slice(0, 2)).toUpperCase();
}

export default function ResolveAccessCard({
  agents,
  objects,
  subjectId,
  objectId,
  onSubjectChange,
  onObjectChange,
  result,
  loading,
  error,
}: ResolveAccessCardProps) {
  const subject = agents.find((a) => a.id === subjectId);
  const objectName =
    objects.find((o) => o.id === objectId)?.name ?? "this resource";

  return (
    <div className={styles.card}>
      <div className={styles.cardH}>
        <span className={styles.cardHIc}>
          <Search className="h-4 w-4" />
        </span>
        <span className={styles.cardT}>Resolve access</span>
      </div>
      <div className={styles.cardB}>
        <div className={styles.resolveRow}>
          <div className={styles.sel}>
            <span
              className={styles.selAv}
              style={{ background: subject?.color ?? "#6b7280" }}
            >
              {subject ? agentInitials(subject.name) : "?"}
            </span>
            <select
              className={styles.selNative}
              value={subjectId}
              onChange={(e) => onSubjectChange(e.target.value)}
              aria-label="Subject"
            >
              {agents.map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.name}
                </option>
              ))}
            </select>
            <ChevronDown
              className="h-4 w-4 shrink-0"
              style={{ color: "var(--access-muted2)" }}
            />
          </div>
        </div>

        <div className={styles.resolveRow}>
          <span className={styles.relWord}>can use</span>
          <div className={styles.sel}>
            <Sparkles
              className="h-4 w-4 shrink-0"
              style={{ color: "#27a08c" }}
            />
            <select
              className={styles.selNative}
              value={objectId}
              onChange={(e) => onObjectChange(e.target.value)}
              aria-label="Object"
            >
              {objects.map((obj) => (
                <option key={obj.id} value={obj.id}>
                  {obj.name}
                </option>
              ))}
            </select>
            <ChevronDown
              className="h-4 w-4 shrink-0"
              style={{ color: "var(--access-muted2)" }}
            />
          </div>
        </div>

        {error ? (
          <div className={cn(styles.verdict, styles.verdictDeny)}>
            <span className={styles.verdictIcon}>
              <X className="h-[18px] w-[18px]" />
            </span>
            <div>
              <div className={styles.verdictTitle}>Could not resolve</div>
              <div className={styles.verdictSub}>{error}</div>
            </div>
          </div>
        ) : loading ? (
          <div
            className={styles.verdictSub}
            style={{ marginTop: 12 }}
          >
            Resolving access…
          </div>
        ) : result && result.allowed ? (
          <div className={cn(styles.verdict, styles.verdictAllow)}>
            <span className={styles.verdictIcon}>
              <Check className="h-[18px] w-[18px]" />
            </span>
            <div>
              <div className={styles.verdictTitle}>
                Allowed — can {result.verb}
              </div>
              <div className={styles.verdictSub}>
                Effective: <b>{result.effective_relation}</b> · derived from{" "}
                {result.paths.length} relationship path
                {result.paths.length === 1 ? "" : "s"}.
              </div>
            </div>
          </div>
        ) : result ? (
          <div className={cn(styles.verdict, styles.verdictDeny)}>
            <span className={styles.verdictIcon}>
              <X className="h-[18px] w-[18px]" />
            </span>
            <div>
              <div className={styles.verdictTitle}>Denied</div>
              <div className={styles.verdictSub}>
                {subject?.name ?? "This subject"} has no relationship that
                reaches <b>{objectName}</b>.
              </div>
            </div>
          </div>
        ) : null}

        {result && result.allowed && result.paths.length > 0 && (
          <>
            <div className={styles.pathsCap}>Derivation paths</div>
            <div>
              {result.paths.map((path, pathIndex) => (
                <div className={styles.path} key={`path-${pathIndex}`}>
                  {path.hops.map((hop, hopIndex) => {
                    const rel = path.rels[hopIndex];
                    return (
                      <span
                        key={`${hop.id}-${hopIndex}`}
                        style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
                      >
                        <span className={styles.pnode}>
                          <span
                            className={styles.pd}
                            style={{ background: hop.color }}
                          />
                          {hop.name}
                        </span>
                        {rel && (
                          <span className={styles.parrow}>
                            <span className={cn(styles.prel, relClass(rel))}>
                              {rel}
                            </span>
                            <span aria-hidden>›</span>
                          </span>
                        )}
                      </span>
                    );
                  })}
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
