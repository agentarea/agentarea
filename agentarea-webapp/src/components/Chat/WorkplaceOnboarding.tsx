"use client";

import React, { Suspense, useRef } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { Lock, Sparkles } from "lucide-react";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import {
  BadgeSuggestions,
  type BadgeSuggestion,
} from "./componets/BadgeSuggestions";
import { ChatInputArea } from "./componets/ChatInputArea";
import { ChatWelcome } from "./componets/ChatWelcome";
import { ComposerSetupBanner } from "./componets/ComposerSetupBanner";

interface WorkplaceOnboardingProps {
  hasModels: boolean;
  badgeSuggestions?: BadgeSuggestion[] | Promise<BadgeSuggestion[]>;
}

const noop = () => {};

/**
 * The workplace before it can be used: the same welcome, composer and chips as
 * WorkplaceChat, with the composer locked and the missing step docked on top of
 * it — a model first, then an agent. Mirroring the chat layout is deliberate:
 * finishing setup should not move anything but the banner.
 */
export function WorkplaceOnboarding({
  hasModels,
  badgeSuggestions,
}: WorkplaceOnboardingProps) {
  const t = useTranslations("WorkplacePage.onboarding");
  const tHero = useTranslations("Workplace.hero");
  const router = useRouter();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const step = hasModels
    ? {
        index: 2,
        title: t("createAgentTitle"),
        description: t("createAgentDescription"),
        action: t("createAgentAction"),
        href: "/agents/create",
        placeholder: t("createAgentPlaceholder"),
      }
    : {
        index: 1,
        title: t("connectModelTitle"),
        description: t("connectModelDescription"),
        action: t("connectModelAction"),
        href: "/models",
        placeholder: t("connectModelPlaceholder"),
      };

  return (
    <div className="mx-auto flex h-full w-full max-w-3xl flex-col justify-center gap-8 overflow-y-auto overflow-x-hidden py-8 md:overflow-visible md:py-0">
      <div className="flex w-full flex-none items-center justify-center">
        <ChatWelcome icon={Sparkles} title={tHero("title")} />
      </div>

      <div className="relative mx-auto w-full px-4 md:px-6">
        <ComposerSetupBanner
          step={step.index}
          totalSteps={2}
          title={step.title}
          description={step.description}
          actionLabel={step.action}
          href={step.href}
        />
        <div className="relative pb-3">
          <ChatInputArea
            disabled
            input=""
            onInputChange={noop}
            onSubmit={(e) => e.preventDefault()}
            isLoading={false}
            placeholder={step.placeholder}
            selectedFiles={[]}
            onRemoveFile={noop}
            onOpenFileDialog={noop}
            onFileSelect={noop}
            fileInputRef={fileInputRef}
            textareaRef={textareaRef}
            variant="centered"
            rows={3}
            leadingControls={
              // Sits where the agent picker will be, shaped like its trigger.
              <span className="flex h-7 items-center gap-1 px-1.5 text-[13px] leading-[1.2] text-zinc-400 dark:text-zinc-500">
                <EntityAvatar
                  variant="soft"
                  size={20}
                  icon={<Lock strokeWidth={1.85} />}
                  aria-hidden
                />
                {t("noAgent")}
              </span>
            }
          />
        </div>
      </div>

      {badgeSuggestions && (
        <div className="w-full flex-none pb-4">
          {/* Their own boundary — the rest of the onboarding screen is static
              and should not wait on the chips. */}
          <Suspense fallback={null}>
            <BadgeSuggestions
              suggestions={badgeSuggestions}
              onBadgeClick={() => router.push(step.href)}
              visible
            />
          </Suspense>
        </div>
      )}
    </div>
  );
}
