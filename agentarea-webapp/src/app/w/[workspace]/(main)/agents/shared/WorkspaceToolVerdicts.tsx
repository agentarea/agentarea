"use client";

import { createContext, useContext, type ReactNode } from "react";
import type {
  WorkspaceToolVerdict,
  WorkspaceToolVerdicts,
} from "./workspaceToolPolicy";

const WorkspaceToolVerdictsContext = createContext<WorkspaceToolVerdicts>({});

export function WorkspaceToolVerdictsProvider({
  verdicts,
  children,
}: {
  verdicts: WorkspaceToolVerdicts;
  children: ReactNode;
}) {
  return (
    <WorkspaceToolVerdictsContext.Provider value={verdicts}>
      {children}
    </WorkspaceToolVerdictsContext.Provider>
  );
}

/** The workspace's verdict on each tool of one connection, by tool name. */
export function useWorkspaceToolVerdicts(
  instanceId: string
): Record<string, WorkspaceToolVerdict> {
  return useContext(WorkspaceToolVerdictsContext)[instanceId] ?? {};
}
