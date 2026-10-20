import { Lock } from "lucide-react";
import { FactRow } from "@/components/Overview/OverviewCard";

export interface CustomHeader {
  name: string;
  secret: boolean;
  value?: string | null;
}

/**
 * Stored headers or query parameters as rows of a section card: the name in
 * mono, the value on the right, a secret shown only as locked dots.
 */
export function CustomHeadersList({ headers }: { headers: CustomHeader[] }) {
  return (
    <>
      {headers.map((header) => (
        <FactRow
          key={header.name}
          title={<span className="font-mono">{header.name}</span>}
          trailing={
            header.secret ? (
              <span className="inline-flex items-center gap-1.5 font-mono">
                <Lock className="h-3 w-3" />
                ••••••••
              </span>
            ) : (
              <span className="font-mono text-foreground/80">{header.value ?? ""}</span>
            )
          }
        />
      ))}
    </>
  );
}
