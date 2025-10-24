import { ReactNode } from 'react';
import { Badge } from '@/components/ui/badge';
import { LucideIcon } from 'lucide-react';

interface SettingsSectionProps {
  title: string;
  description?: string;
  icon?: LucideIcon;
  badge?: string;
  badgeVariant?: 'default' | 'secondary' | 'outline' | 'destructive';
  children: ReactNode;
  className?: string;
}

export default function SettingsSection({
  title,
  description,
  icon: Icon,
  badge,
  badgeVariant = 'outline',
  children,
  className = ''
}: SettingsSectionProps) {
  return (
    <div className={`bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 ${className}`}>
      <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {Icon && (
              <div className="p-2 bg-blue-50 dark:bg-blue-900/20 rounded-lg">
                <Icon className="h-5 w-5 text-blue-600 dark:text-blue-400" />
              </div>
            )}
            <div>
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                {title}
              </h3>
              {description && (
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
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
      <div className="p-6">
        {children}
      </div>
    </div>
  );
}