"use client";

// TEMPORARY visual fixture — delete before finishing.
import { useSearchParams } from "next/navigation";
import { InboxClient } from "@/app/(main)/inbox/components/InboxClient";
import type { InboxTask } from "@/app/(main)/inbox/components/inboxShared";
import { SidebarProvider } from "@/components/ui/sidebar";

const ago = (h: number) => new Date(Date.now() - h * 3_600_000).toISOString();

function build(withPending: boolean) {
  const statuses = withPending
    ? ["failed", "completed", "waiting_for_approval", "completed"]
    : ["failed", "completed", "completed", "completed"];
  return Array.from({ length: 8 }, (_, i) => {
    const status = statuses[i % statuses.length];
    return {
      id: `t${i}`, description: ["test", "Backfill missing avatars", "Approve deploy", "Summarize daily metrics"][i % 4],
      agent_id: `agent-${i % 3}`, agent_name: ["support-bot-4de9c2", "planner-4de9c2", "orchestrator-4de9c2"][i % 3], status,
      created_at: ago(18 + i * 10),
      result: status === "completed" ? { text: "done" } : null,
      error: status === "failed" ? "boom" : null,
      escalation_id: status === "waiting_for_approval" ? "esc-1" : null,
      escalation_tool_name: status === "waiting_for_approval" ? "deploy" : null,
    };
  }) as unknown as InboxTask[];
}

export default function InboxFixture() {
  const clear = useSearchParams().get("clear") === "1";
  return (
    <SidebarProvider>
      <div className="flex h-screen w-full [&>*]:w-full">
        <InboxClient items={build(!clear)} error={null} />
      </div>
    </SidebarProvider>
  );
}
