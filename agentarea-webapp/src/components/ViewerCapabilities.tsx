"use client";

import { createContext, useContext, type ReactNode } from "react";
import type { ViewerCapabilities } from "@/lib/workspace-context";

const ViewerCapabilitiesContext = createContext<ViewerCapabilities | null>(
  null
);

export function ViewerCapabilitiesProvider({
  capabilities,
  children,
}: {
  capabilities: ViewerCapabilities;
  children: ReactNode;
}) {
  return (
    <ViewerCapabilitiesContext.Provider value={capabilities}>
      {children}
    </ViewerCapabilitiesContext.Provider>
  );
}

export function useViewerCapabilities(): ViewerCapabilities {
  const capabilities = useContext(ViewerCapabilitiesContext);
  if (!capabilities) {
    throw new Error(
      "useViewerCapabilities must be used within ViewerCapabilitiesProvider"
    );
  }
  return capabilities;
}
