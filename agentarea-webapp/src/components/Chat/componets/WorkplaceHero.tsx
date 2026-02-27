import React from "react";
import { useTranslations } from "next-intl";
import { Bot, Sparkles } from "lucide-react";

export default function WorkplaceHero() {
  const t = useTranslations("Workplace.hero");

  return (
    <div className="relative flex flex-col items-center justify-center text-center space-y-4 max-w-2xl px-4 animate-in fade-in zoom-in duration-1000 slide-in-from-bottom-2">
      <div className="relative z-10 flex flex-col items-center gap-3">
        {/* Animated Icon - Very minimal */}
        <div className="p-2 rounded-full bg-primary/5 dark:bg-primary/10 mb-2 animate-bounce-slow">
          <Sparkles className="w-5 h-5 text-primary opacity-80" strokeWidth={1.5} />
        </div>
        
        <h1 className="text-xl sm:text-2xl font-light tracking-tight text-zinc-500 dark:text-zinc-400">
          {t("title")}
        </h1>
      </div>
    </div>
  );
}
