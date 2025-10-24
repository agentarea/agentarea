import Image from "next/image";
import { getProviderIconUrl } from "@/lib/provider-icons";
import { cn } from "@/lib/utils";

interface ModelBadgeProps {
  providerName?: string;
  modelDisplayName?: string;
  configName?: string;
  className?: string;
  isLoading?: boolean;
}

export default function ModelBadge({
  providerName,
  modelDisplayName,
  configName,
  className,
  isLoading = false,
}: ModelBadgeProps) {
  const getProviderIcon = () => {
    if (isLoading) {
      return "data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTYiIGhlaWdodD0iMTYiIHZpZXdCb3g9IjAgMCAxNiAxNiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHJlY3Qgd2lkdGg9IjE2IiBoZWlnaHQ9IjE2IiByeD0iMiIgZmlsbD0iI0YzRjNGMyIvPgo8Y2lyY2xlIGN4PSI4IiBjeT0iOCIgcj0iMyIgZmlsbD0iIzk5OTk5OSIvPgo8L3N2Zz4K";
    }
    const iconUrl = providerName ? getProviderIconUrl(providerName) : undefined;
    return (
      iconUrl ||
      "data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTYiIGhlaWdodD0iMTYiIHZpZXdCb3g9IjAgMCAxNiAxNiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHJlY3Qgd2lkdGg9IjE2IiBoZWlnaHQ9IjE2IiByeD0iMiIgZmlsbD0iI0YzRjNGMyIvPgo8cGF0aCBkPSJNOCA0QzkuMTA0NTcgNCAxMCA0Ljg5NTQzIDEwIDZDMTAgNy4xMDQ1NyA5LjEwNDU3IDggOCA4QzYuODk1NDMgOCA2IDcuMTA0NTcgNiA2QzYgNC44OTU0MyA2Ljg5NTQzIDQgOCA0WiIgZmlsbD0iIzk5OTk5OSIvPgo8cGF0aCBkPSJNOCA5QzkuMTA0NTcgOSAxMCA5Ljg5NTQzIDEwIDExQzEwIDEyLjEwNDYgOS4xMDQ1NyAxMyA4IDEzQzYuODk1NDMgMTMgNiAxMi4xMDQ2IDYgMTFDNiA5Ljg5NTQzIDYuODk1NDMgOSA4IDlaIiBmaWxsPSIjOTk5OTk5Ii8+Cjwvc3ZnPgo="
    );
  };

  const getModelName = () => {
    if (isLoading) return "Loading...";
    return modelDisplayName || configName || providerName || "Unknown model";
  };

  return (
    <div
      className={cn(
        "flex max-w-max items-center gap-1 rounded-md bg-gray-100 px-2 py-1 text-sm",
        className
      )}
      title={`Model: ${getModelName()}${providerName ? ` (${providerName})` : ""}`}
    >
      <Image
        src={getProviderIcon()}
        alt={providerName || "Model"}
        width={16}
        height={16}
        className="rounded-sm"
      />
      <span className="text-xs font-medium text-gray-700">
        {getModelName()}
      </span>
      {providerName && (
        <span className="text-xs text-gray-500">({providerName})</span>
      )}
    </div>
  );
}
