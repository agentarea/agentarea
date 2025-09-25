"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import AgentTasksList from "./AgentTasksList";
import AgentPageClient from "./AgentPageClient";
import { Agent } from "@/types/agent";

export default function AgentContentSwitcher({ agent }: { agent: Agent }) {
  const searchParams = useSearchParams();
  const activeTab = useMemo(() => {
    const tab = searchParams.get("tab");
    return tab === "all" ? "all" : "new";
  }, [searchParams]);

  const [showTasks, setShowTasks] = useState(activeTab === "all");

  useEffect(() => {
    if (activeTab === "all") {
      setShowTasks(true);
    }
  }, [activeTab]);

  return (
    <div className="h-full w-full overflow-hidden">
      <div className={activeTab === "new" ? "block h-full" : "hidden h-full"}>
        <AgentPageClient agent={agent} />
      </div>
      {showTasks && (
        <div className={activeTab === "all" ? "block h-full" : "hidden h-full"}>
          <AgentTasksList agentId={agent.id} />
        </div>
      )}
    </div>
  );
}


