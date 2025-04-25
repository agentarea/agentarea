'use client';

import { useLocale } from 'next-intl';
import { useTransition } from 'react';
import { GlobeIcon } from 'lucide-react';
import { cn } from "@/lib/utils";
import { useTranslations } from 'next-intl';

export default function LanguageSelect() {
  const locale = useLocale() as 'en' | 'ru';
  const t = useTranslations('LanguageSelect');
  
  const onSelectChange = () => {
      const newLocale: 'en' | 'ru' = locale === 'en' ? 'ru' : 'en';
      document.cookie = `NEXT_LOCALE=${newLocale}; path=/; max-age=31536000; SameSite=Lax`;
      window.location.reload();
  };

  return (
    <button
      onClick={onSelectChange}
      className={cn(
        "text-foreground hover:bg-zinc-200/60 hover:dark:bg-white/10",
        "relative text-[14px] leading-[14px] flex items-center justify-between",
        "py-[10px] px-[10px] rounded-[8px]",
        "group transition-all duration-300 w-full"
      )}
    >
      <div className="flex items-center gap-[8px]">
        <GlobeIcon className="h-5 w-5 flex-shrink-0" />
        <span className="truncate leading-[18px] transition-all duration-300">
          {t('switchLanguage')}
        </span>
      </div>
      <span className="text-xs leading-[18px] opacity-70 font-medium transition-all duration-300">
        {locale.toUpperCase()}
      </span>
    </button>
  );
} 
