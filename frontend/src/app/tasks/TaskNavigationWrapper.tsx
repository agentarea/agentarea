"use client";

import React from "react";
import { useRouter } from "next/navigation";

interface TaskNavigationWrapperProps {
  children: React.ReactNode;
  taskId: string;
}

export function TaskNavigationWrapper({ children, taskId }: TaskNavigationWrapperProps) {
  const router = useRouter();

  const handleClick = () => {
    router.push(`/tasks/${taskId}`);
  };

  return (
    <div 
      className="cursor-pointer hover:bg-muted/50" 
      onClick={handleClick}
    >
      {children}
    </div>
  );
}