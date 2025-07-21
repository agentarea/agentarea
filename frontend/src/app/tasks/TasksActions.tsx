"use client";

import React from "react";
import { useRouter } from "next/navigation";
import { Bot, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";

export function TasksActions() {
  const router = useRouter();

  const handleRefresh = () => {
    router.refresh();
  };

  const handleDeployAgent = () => {
    router.push('/agents/create');
  };

  return (
    <div className="flex gap-4 mb-6">
      <Button
        variant="outline"
        onClick={handleRefresh}
        className="gap-2"
      >
        <RefreshCw className="h-4 w-4" />
        Refresh
      </Button>
      <Button
        onClick={handleDeployAgent}
        className="gap-2"
      >
        <Bot className="h-5 w-5" />
        Deploy New Agent
      </Button>
    </div>
  );
}