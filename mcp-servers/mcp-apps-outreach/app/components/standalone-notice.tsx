import { Radar } from "lucide-react";

/** Shown when a view is opened as a plain page: without a host there is no bridge and no data. */
export function StandaloneNotice({ title }: { title: string }) {
  return (
    <div className="flex min-h-svh items-center justify-center p-6">
      <div className="bg-card flex max-w-sm flex-col items-center gap-3 rounded-xl border p-6 text-center shadow-xs">
        <div className="bg-primary text-primary-foreground flex size-10 items-center justify-center rounded-lg">
          <Radar className="size-5" />
        </div>
        <h1 className="text-base font-semibold">{title}</h1>
        <p className="text-muted-foreground text-sm">
          This is an MCP App. Open it from an MCP host (for example AgentArea) connected to the outreach server — the
          data comes from the server, never from this file.
        </p>
      </div>
    </div>
  );
}
