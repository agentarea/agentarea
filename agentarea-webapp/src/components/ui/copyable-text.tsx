"use client";

import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { cn } from "@/lib/utils";

interface CopyableTextProps {
  text: string;
  displayValue?: string;
  className?: string;
  labelClassName?: string;
  onCopied?: () => void;
  onCopyError?: () => void;
}

export function CopyableText({
  text,
  displayValue,
  className,
  labelClassName,
  onCopied,
  onCopyError,
}: CopyableTextProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      onCopied?.();
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error("Failed to copy text: ", err);
      onCopyError?.();
    }
  };

  return (
    <button
      type="button"
      onClick={handleCopy}
      className={cn(
        "group flex w-full min-w-0 max-w-full cursor-pointer items-center justify-between gap-2 overflow-hidden rounded-md border border-border/50 bg-muted/30 px-3 py-1.5 text-left transition-all hover:bg-muted/50",
        className
      )}
    >
      <span
        className={cn(
          "min-w-0 flex-1 truncate font-mono text-[13px] text-foreground",
          labelClassName
        )}
      >
        {displayValue || text}
      </span>
      <span className="flex shrink-0 items-center justify-center">
        {copied ? (
          <Check className="h-3 w-3 text-green-500" />
        ) : (
          <Copy className="h-3 w-3 text-muted-foreground/50 transition-opacity group-hover:text-muted-foreground" />
        )}
      </span>
    </button>
  );
}
