/**
 * Utility functions for MCP server categorization and styling
 */

export type MCPServerCategory =
  | "AI"
  | "Data"
  | "Dev"
  | "Web"
  | "Files"
  | "Messaging"
  | "Tools";

/**
 * Get category for MCP server based on tags
 */
export function getMCPServerCategory(tags: string[]): MCPServerCategory {
  const lowerTags = tags.map((tag) => tag.toLowerCase());

  if (
    lowerTags.some((tag) =>
      tag.includes("ai") ||
      tag.includes("llm") ||
      tag.includes("search") ||
      tag.includes("memory")
    )
  ) {
    return "AI";
  }

  if (
    lowerTags.some((tag) =>
      tag.includes("database") ||
      tag.includes("data") ||
      tag.includes("analytics")
    )
  ) {
    return "Data";
  }

  if (
    lowerTags.some((tag) =>
      tag.includes("git") ||
      tag.includes("repository") ||
      tag.includes("github")
    )
  ) {
    return "Dev";
  }

  if (
    lowerTags.some((tag) =>
      tag.includes("web") || tag.includes("browser") || tag.includes("fetch")
    )
  ) {
    return "Web";
  }

  if (lowerTags.some((tag) => tag.includes("file") || tag.includes("filesystem"))) {
    return "Files";
  }

  if (
    lowerTags.some((tag) =>
      tag.includes("message") ||
      tag.includes("slack") ||
      tag.includes("gmail")
    )
  ) {
    return "Messaging";
  }

  return "Tools";
}

/**
 * Get CSS classes for category badge
 */
export function getCategoryColorClasses(
  category: MCPServerCategory
): string {
  const colorMap: Record<MCPServerCategory, string> = {
    AI: "bg-purple-50 text-purple-700 border-purple-200 dark:bg-purple-950/30 dark:text-purple-300 dark:border-purple-800",
    Data: "bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-950/30 dark:text-blue-300 dark:border-blue-800",
    Dev: "bg-orange-50 text-orange-700 border-orange-200 dark:bg-orange-950/30 dark:text-orange-300 dark:border-orange-800",
    Web: "bg-green-50 text-green-700 border-green-200 dark:bg-green-950/30 dark:text-green-300 dark:border-green-800",
    Files: "bg-yellow-50 text-yellow-700 border-yellow-200 dark:bg-yellow-950/30 dark:text-yellow-300 dark:border-yellow-800",
    Messaging:
      "bg-pink-50 text-pink-700 border-pink-200 dark:bg-pink-950/30 dark:text-pink-300 dark:border-pink-800",
    Tools: "bg-gray-50 text-gray-700 border-gray-200 dark:bg-gray-950/30 dark:text-gray-300 dark:border-gray-800",
  };

  return colorMap[category];
}

/**
 * Constants for MCP server configuration
 */
export const MCP_CONSTANTS = {
  HEALTH_CHECK_INTERVAL_MS: 60000, // 1 minute
  DEFAULT_CONTAINER_PORT: 8000,
} as const;

