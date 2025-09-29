import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function apiFetch(input: string, init: RequestInit = {}) {
  const workspaceId = typeof window !== "undefined"
    ? localStorage.getItem("selectedWorkspace") || "default"
    : "default";

  const headers = new Headers(init.headers || {})
  headers.set("X-Workspace-ID", workspaceId)
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json")
  }

  const response = await fetch(`${API_BASE_URL}${input}`, {
    ...init,
    headers,
  })

  return response
}
