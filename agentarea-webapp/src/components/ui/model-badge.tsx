import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

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
  const getModelName = () => {
    if (isLoading) return "Loading...";
    return modelDisplayName || configName || providerName || "Unknown model";
  };

  const isSm = size === "sm";
  const iconSize = isSm ? 14 : 16;

  // While loading show a neutral skeleton; once loaded render the real icon, or
  // nothing at all if the provider has none. No default/placeholder icons.
  const renderIcon = () => {
    if (isLoading) {
      return (
        <Skeleton
          className="rounded-sm"
          style={{ width: iconSize, height: iconSize }}
        />
      );
    }
    if (!iconUrl) return null;
    return (
      <img
        src={iconUrl}
        alt={providerName || "Model"}
        width={iconSize}
        height={iconSize}
        className="rounded-sm"
        onError={(e) => {
          e.currentTarget.style.display = "none";
        }}
      />
    );
  };

  return (
    <div
      className={cn(
        "flex max-w-max items-center gap-1 rounded-md bg-gray-100",
        isSm ? "px-1.5 py-0.5" : "px-2 py-1",
        className
      )}
      title={`Model: ${getModelName()}${providerName ? ` (${providerName})` : ""}`}
    >
      {renderIcon()}
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
