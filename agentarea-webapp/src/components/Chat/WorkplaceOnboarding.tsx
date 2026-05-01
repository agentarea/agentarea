"use client";

import React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { ArrowRight, Bot, Paperclip, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import {
  BadgeSuggestions,
  type BadgeSuggestion,
} from "./componets/BadgeSuggestions";
import { ChatWelcome } from "./componets/ChatWelcome";

interface WorkplaceOnboardingProps {
  hasProviders: boolean;
  badgeSuggestions?: BadgeSuggestion[];
}

export function WorkplaceOnboarding({
  hasProviders,
  badgeSuggestions = [],
}: WorkplaceOnboardingProps) {
  const t = useTranslations("WorkplacePage.onboarding");
  const tHero = useTranslations("Workplace.hero");
  const router = useRouter();

  const primaryHref = hasProviders ? "/agents/create" : "/admin/provider-configs";
  const primaryLabel = hasProviders
    ? t("createAgentAction")
    : t("connectLLMAction");

  return (
    <div className="mx-auto flex h-full w-full max-w-3xl flex-col justify-center gap-8 py-8 md:py-0">
      <div className="mx-auto w-full max-w-2xl px-4">
        <div className="flex items-center gap-3 rounded-lg border bg-card px-3.5 py-2.5 shadow-sm">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
            <Bot className="h-4 w-4" strokeWidth={1.75} />
          </div>
          <div className="flex-1 text-xs leading-snug">
            <p className="font-medium text-foreground">{t("noAgentTitle")}</p>
            <p className="text-muted-foreground">
              {hasProviders ? t("noAgentSubtitle") : t("noProviderSubtitle")}
            </p>
          </div>
          <Button
            asChild
            size="sm"
            variant="ghost"
            className="h-7 gap-1 px-2.5 text-xs"
          >
            <Link href={primaryHref}>
              {primaryLabel}
              <ArrowRight className="h-3 w-3" />
            </Link>
          </Button>
        </div>
      </div>

      <div className="flex flex-none w-full items-center justify-center">
        <ChatWelcome title={tHero("title")} />
      </div>

      <div className="relative mx-auto w-full max-w-2xl px-4">
        <div
          aria-disabled="true"
          className={cn(
            "card pointer-events-none relative w-full cursor-not-allowed bg-white px-3 pb-2 pt-2 opacity-80",
            "rounded-2xl border shadow-[0_8px_30px_rgb(0,0,0,0.04)] dark:border-zinc-800 dark:bg-zinc-900 dark:shadow-[0_8px_30px_rgb(0,0,0,0.2)]"
          )}
        >
          <Textarea
            disabled
            placeholder={t("disabledPlaceholder")}
            className="min-h-[60px] resize-none border-0 bg-transparent p-2 text-sm shadow-none focus-visible:ring-0"
          />
          <div className="flex items-center justify-between px-1 pb-1">
            <Button
              variant="ghost"
              size="icon"
              disabled
              className="h-8 w-8 text-muted-foreground"
            >
              <Paperclip className="h-4 w-4" />
            </Button>
            <Button disabled size="icon" className="h-8 w-8">
              <Send className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </div>

      <div className="flex-none w-full pb-4">
        <BadgeSuggestions
          suggestions={badgeSuggestions}
          onBadgeClick={() => router.push(primaryHref)}
          visible={badgeSuggestions.length > 0}
        />
      </div>
    </div>
  );
}
