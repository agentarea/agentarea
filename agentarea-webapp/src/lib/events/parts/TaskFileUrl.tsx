"use client";

import { createContext, useContext } from "react";

/** Resolves a path in the task's workspace to a URL the browser can load.
 * Absent outside a task, where a path has nothing to resolve against. */
export const TaskFileUrlContext = createContext<
  ((path: string) => string) | null
>(null);

export const useTaskFileUrl = () => useContext(TaskFileUrlContext);
