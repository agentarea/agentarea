"use client";

import { createContext, useContext } from "react";

/** Resolves a path in the task's workspace to a URL the browser can load.
 * Absent outside a task, where a path has nothing to resolve against. */
export const TaskFileUrlContext = createContext<
  ((path: string) => string) | null
>(null);

export const useTaskFileUrl = () => useContext(TaskFileUrlContext);

/** Where a link to a task file takes the reader: the file open in the task's
 * Files tab, to read rather than download. Absent outside a task. */
export const TaskFileLinkContext = createContext<
  ((path: string) => string) | null
>(null);

export const useTaskFileLink = () => useContext(TaskFileLinkContext);

/** Opens a task file beside the conversation, where the page offers that. */
export const TaskFileOpenContext = createContext<
  ((path: string) => void) | null
>(null);

export const useTaskFileOpen = () => useContext(TaskFileOpenContext);
