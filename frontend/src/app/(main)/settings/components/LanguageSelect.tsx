'use client';

import { useLocale } from 'next-intl';
import { useTransition } from 'react';
import { GlobeIcon, ChevronRight } from 'lucide-react';
import { cn } from "@/lib/utils";
import { useTranslations } from 'next-intl';

export default function LanguageSelect() {
  const locale = useLocale() as 'en' | 'ru';
  const t = useTranslations('SettingsPage');
  
  const onSelectChange = () => {
      const newLocale: 'en' | 'ru' = locale === 'en' ? 'ru' : 'en';
      document.cookie = `NEXT_LOCALE=${newLocale}; path=/; max-age=31536000; SameSite=Lax`;
      window.location.reload();
  };

  return (
    <button
      onClick={onSelectChange}
      className={cn(
        "flex items-center justify-between gap-3 px-4 py-2.5 min-w-[140px]",
        "bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700",
        "text-gray-900 dark:text-gray-100 hover:border-blue-300 dark:hover:border-blue-600",
        "rounded-lg transition-all duration-200 group",
        "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 dark:focus:ring-offset-gray-800"
      )}
    >
      <div className="flex items-center gap-2">
        <GlobeIcon className="h-4 w-4 text-gray-500 dark:text-gray-400" />
        <span className="text-sm font-medium">
          {locale === 'en' ? 'English' : 'Русский'}
        </span>
      </div>
      <ChevronRight className="h-4 w-4 text-gray-400 dark:text-gray-500 group-hover:text-gray-600 dark:group-hover:text-gray-300 transition-colors" />
    </button>
  );
} 
