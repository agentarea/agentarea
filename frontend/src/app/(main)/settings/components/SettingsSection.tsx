import { ReactNode } from "react";
import { LucideIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";

interface SettingsSectionProps {
  title: string;
  description?: string;
  icon?: LucideIcon;
  badge?: string;
  badgeVariant?: "default" | "secondary" | "outline" | "destructive";
  children: ReactNode;
  className?: string;
}

export default function SettingsSection({
  title,
  description,
  icon: Icon,
  badge,
  badgeVariant = "outline",
  children,
  className = "",
}: SettingsSectionProps) {
  return (
    <div
      className={`rounded-lg border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800 ${className}`}
    >
      <div className="border-b border-gray-200 px-6 py-4 dark:border-gray-700">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {Icon && (
              <div className="rounded-lg bg-blue-50 p-2 dark:bg-blue-900/20">
                <Icon className="h-5 w-5 text-blue-600 dark:text-blue-400" />
              </div>
            )}
            <div>
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                {title}
              </h3>
              {description && (
                <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                  {description}
                </p>
              )}
            </div>
          </div>
          {badge && (
            <Badge variant={badgeVariant} className="text-xs">
              {badge}
            </Badge>
          )}
        </div>
      </div>
      <div className="p-6">{children}</div>
    </div>
  );
}
