import { Lock } from "lucide-react";

export interface CustomHeader {
  name: string;
  secret: boolean;
  value?: string | null;
}

export function CustomHeadersList({
  headers,
  label,
}: {
  headers: CustomHeader[];
  label?: string;
}) {
  if (headers.length === 0) return null;

  return (
    <div className="space-y-2">
      {label && (
        <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          {label}
        </div>
      )}
      <div className="grid gap-2">
        {headers.map((header) => (
          <div
            key={header.name}
            className="flex items-center justify-between rounded-md border px-3 py-2"
          >
            <p className="font-mono text-sm">{header.name}</p>
            <div className="flex items-center gap-1.5">
              {header.secret ? (
                <>
                  <Lock className="h-3.5 w-3.5 text-muted-foreground" />
                  <span className="font-mono text-sm text-muted-foreground">
                    ••••••••
                  </span>
                </>
              ) : (
                <span className="font-mono text-sm">{header.value ?? ""}</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
