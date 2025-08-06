"use client";

import React from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Bot, XCircle } from "lucide-react";

interface TasksNavigationButtonsProps {
  type: "clear-filters" | "deploy-agent" | "browse-agents" | "create-agent";
  variant?: "default" | "outline";
  className?: string;
}

export function TasksNavigationButtons({ type, variant = "default", className }: TasksNavigationButtonsProps) {
  const router = useRouter();

  const handleClick = () => {
    switch (type) {
      case "clear-filters":
        router.push("/tasks");
        break;
      case "deploy-agent":
        router.push("/agents/create");
        break;
      case "browse-agents":
        router.push("/agents");
        break;
      case "create-agent":
        router.push("/agents/create");
        break;
    }
  };

  const getButtonProps = () => {
    switch (type) {
      case "clear-filters":
        return {
          children: (
            <>
              <XCircle className="h-4 w-4" />
              Clear Filters
            </>
          )
        };
      case "deploy-agent":
        return {
          children: (
            <>
              <Bot className="h-4 w-4" />
              Deploy Agent
            </>
          )
        };
      case "browse-agents":
        return {
          children: (
            <>
              <Bot className="h-4 w-4" />
              Browse Agents
            </>
          )
        };
      case "create-agent":
        return {
          children: (
            <>
              <Bot className="h-4 w-4" />
              Create Agent
            </>
          )
        };
    }
  };

  return (
    <Button 
      variant={variant} 
      onClick={handleClick} 
      className={`gap-2 ${className || ""}`}
    >
      {getButtonProps().children}
    </Button>
  );
}