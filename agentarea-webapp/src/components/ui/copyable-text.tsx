"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";

interface CopyableTextProps {
  text: string;
  displayValue?: string;
  className?: string;
  labelClassName?: string;
}

export function CopyableText({
  text,
  displayValue,
  className,
  labelClassName,
}: CopyableTextProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error("Failed to copy text: ", err);
    }
  };

  return (
    <div
      onClick={handleCopy}
      className={cn(
        "group flex cursor-pointer items-center justify-between gap-2 rounded-md border border-border/50 bg-muted/30 px-3 py-1.5 transition-all hover:bg-muted/50",
        className
      )}
    >
      <span className={cn("truncate font-mono text-[13px] text-foreground", labelClassName)}>
        {displayValue || text}
      </span>
      <div className="flex shrink-0 items-center justify-center">
        {copied ? (
          <Check className="h-3 w-3 text-green-500" />
        ) : (
          <Copy className="h-3 w-3 text-muted-foreground/50 transition-opacity group-hover:text-muted-foreground" />
        )}
      </div>
    </div>
  );
}
