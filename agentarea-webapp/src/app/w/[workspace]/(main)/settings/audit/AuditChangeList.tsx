import type { AuditEvent } from "./actions";
import { auditChangeLines } from "./auditChanges";

/** An audit event's field diffs, one line per changed leaf, secrets masked. */
export function AuditChangeList({
  changes,
  className,
}: {
  changes: AuditEvent["changes"];
  className?: string;
}) {
  const lines = auditChangeLines(changes);
  if (lines.length === 0) return null;

  return (
    <div className={className}>
      {lines.map((line) => (
        <div key={line.field} className="break-all font-mono text-xs">
          <span className="text-muted-foreground">{line.field}:</span>{" "}
          <span className="text-red-500 line-through">{line.before}</span>{" "}
          <span className="text-emerald-600">{line.after}</span>
        </div>
      ))}
    </div>
  );
}
