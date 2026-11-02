"use client";

import {
  createContext,
  createElement,
  useContext,
  type ReactNode,
} from "react";

const EgressExitsOfferedContext = createContext(false);

/**
 * Whether this deployment has egress exits, as the root layout read it on the
 * server. False on the open build, where nothing about exits is shown.
 */
export function EgressExitsOfferedProvider({
  offered,
  children,
}: {
  offered: boolean;
  children: ReactNode;
}) {
  return createElement(
    EgressExitsOfferedContext.Provider,
    { value: offered },
    children
  );
}

export function useEgressExitsOffered(): boolean {
  return useContext(EgressExitsOfferedContext);
}
