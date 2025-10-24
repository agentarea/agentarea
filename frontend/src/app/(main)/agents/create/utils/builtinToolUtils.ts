import { Calculator, Files, Globe, LucideIcon, Settings } from "lucide-react";

/**
 * Icon mapping for different builtin tools
 */
export const getBuiltinToolIcon = (
  toolName: string,
  category?: string
): LucideIcon => {
  switch (toolName) {
    case "calculator":
      return Calculator;
    case "math_toolset":
      return Calculator;
    case "file_toolset":
      return Files;
    case "web_toolset":
      return Globe;
    default:
      // Default icon based on category
      switch (category) {
        case "math":
          return Calculator;
        case "utility":
          return Settings;
        case "information":
          return Globe;
        default:
          return Settings;
      }
  }
};

/**
 * Get builtin tool display information with icon
 */
export const getBuiltinToolDisplayInfo = (tool: {
  name: string;
  display_name?: string;
  category?: string;
  description?: string;
}) => {
  const IconComponent = getBuiltinToolIcon(tool.name, tool.category);

  return {
    IconComponent,
    displayName: tool.display_name || tool.name,
    description: tool.description || "",
  };
};
