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
        "w-full max-w-[200px] bg-white dark:bg-zinc-900",
        "text-foreground hover:border-primary/70 dark:hover:bg-zinc-800/50",
        "relative flex items-center justify-between",
        "py-2 px-3 rounded-md",
        "group transition-all duration-200",
        "border border-zinc-200 dark:border-zinc-800"
      )}
    >
      <div className="flex items-center gap-2">
        {/* <GlobeIcon className="h-4 w-4 text-zinc-500 dark:text-zinc-400" /> */}
        <span className="text-sm text-zinc-700 dark:text-zinc-300">
          {t('preferences.switchLanguage')}
        </span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="text-xs font-medium text-zinc-500 dark:text-zinc-400">
          {locale.toUpperCase()}
        </span>
        <ChevronRight className="h-3.5 w-3.5 text-zinc-400 dark:text-zinc-500" />
      </div>
    </button>
  );
} 
