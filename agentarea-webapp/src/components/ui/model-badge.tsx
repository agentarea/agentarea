import { cn } from "@/lib/utils";

// Neutral placeholders rendered while loading or when a provider has no icon.
const LOADING_ICON =
  "data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTYiIGhlaWdodD0iMTYiIHZpZXdCb3g9IjAgMCAxNiAxNiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHJlY3Qgd2lkdGg9IjE2IiBoZWlnaHQ9IjE2IiByeD0iMiIgZmlsbD0iI0YzRjNGMyIvPgo8Y2lyY2xlIGN4PSI4IiBjeT0iOCIgcj0iMyIgZmlsbD0iIzk5OTk5OSIvPgo8L3N2Zz4K";
const FALLBACK_ICON =
  "data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTYiIGhlaWdodD0iMTYiIHZpZXdCb3g9IjAgMCAxNiAxNiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHJlY3Qgd2lkdGg9IjE2IiBoZWlnaHQ9IjE2IiByeD0iMiIgZmlsbD0iI0YzRjNGMyIvPgo8cGF0aCBkPSJNOCA0QzkuMTA0NTcgNCAxMCA0Ljg5NTQzIDEwIDZDMTAgNy4xMDQ1NyA5LjEwNDU3IDggOCA4QzYuODk1NDMgOCA2IDcuMTA0NTcgNiA2QzYgNC44OTU0MyA2Ljg5NTQzIDQgOCA0WiIgZmlsbD0iIzk5OTk5OSIvPgo8cGF0aCBkPSJNOCA5QzkuMTA0NTcgOSAxMCA5Ljg5NTQzIDEwIDExQzEwIDEyLjEwNDYgOS4xMDQ1NyAxMyA4IDEzQzYuODk1NDMgMTMgNiAxMi4xMDQ2IDYgMTFDNiA5Ljg5NTQzIDYuODk1NDMgOSA4IDlaIiBmaWxsPSIjOTk5OTk5Ii8+Cjwvc3ZnPgo=";

interface ModelBadgeProps {
  providerName?: string;
  /** Provider icon URL resolved by the backend (single source of truth). */
  iconUrl?: string | null;
  modelDisplayName?: string;
  configName?: string;
  className?: string;
  isLoading?: boolean;
  size?: "default" | "sm";
}

export default function ModelBadge({
  providerName,
  iconUrl,
  modelDisplayName,
  configName,
  className,
  isLoading = false,
  size = "default",
}: ModelBadgeProps) {
  const getProviderIcon = () => {
    if (isLoading) return LOADING_ICON;
    return iconUrl || FALLBACK_ICON;
  };

  const getModelName = () => {
    if (isLoading) return "Loading...";
    return modelDisplayName || configName || providerName || "Unknown model";
  };

  const isSm = size === "sm";

  return (
    <div
      className={cn(
        "flex max-w-max items-center gap-1 rounded-md bg-gray-100",
        isSm ? "px-1.5 py-0.5" : "px-2 py-1",
        className
      )}
      title={`Model: ${getModelName()}${providerName ? ` (${providerName})` : ""}`}
    >
      <img
        src={getProviderIcon()}
        alt={providerName || "Model"}
        width={isSm ? 14 : 16}
        height={isSm ? 14 : 16}
        className="rounded-sm"
        onError={(e) => {
          e.currentTarget.src = FALLBACK_ICON;
        }}
      />
      <span
        className={cn(
          "font-medium text-gray-700",
          isSm ? "text-[10px]" : "text-xs"
        )}
      >
        {getModelName()}
      </span>
      {providerName && !isSm && (
        <span className="text-xs text-gray-500">({providerName})</span>
      )}
    </div>
  );
}
