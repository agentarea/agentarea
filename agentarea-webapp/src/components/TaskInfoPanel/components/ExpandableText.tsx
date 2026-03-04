import { useState, useRef, useEffect } from "react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { ChevronDown, ChevronUp } from "lucide-react";

interface ExpandableTextProps {
  content: string;
  className?: string;
  maxLines?: number;
}

export default function ExpandableText({
  content,
  className,
  maxLines = 3,
}: ExpandableTextProps) {
  const t = useTranslations("TaskInfoPanel");
  const [isExpanded, setIsExpanded] = useState(false);
  const [isOverflowing, setIsOverflowing] = useState(false);
  const textRef = useRef<HTMLParagraphElement>(null);

  useEffect(() => {
    const checkOverflow = () => {
      const element = textRef.current;
      if (element) {
        // If content is short, scrollHeight will be equal to clientHeight even without clamp
        // If clamped, scrollHeight > clientHeight
        setIsOverflowing(element.scrollHeight > element.clientHeight);
      }
    };

    // Use a small timeout to ensure layout is done
    const timer = setTimeout(checkOverflow, 0);
    window.addEventListener("resize", checkOverflow);
    
    return () => {
      clearTimeout(timer);
      window.removeEventListener("resize", checkOverflow);
    };
  }, [content, maxLines]);

  return (
    <div className={cn("space-y-1", className)}>
      <p
        ref={textRef}
        className={cn(
          "text-xs text-foreground/90 leading-relaxed whitespace-pre-wrap transition-all overflow-hidden",
          !isExpanded && "line-clamp-3"
        )}
        style={!isExpanded ? { 
          display: "-webkit-box",
          WebkitLineClamp: maxLines,
          WebkitBoxOrient: "vertical",
        } : undefined}
      >
        {content}
      </p>
      {isOverflowing && (
        <button
          type="button"
          onClick={() => setIsExpanded(!isExpanded)}
          className="flex items-center gap-1 text-[11px] font-medium text-primary hover:text-primary/80 transition-colors focus:outline-none"
        >
          {isExpanded ? (
            <>
              {t("showLess")} <ChevronUp className="h-3 w-3" />
            </>
          ) : (
            <>
              {t("showMore")} <ChevronDown className="h-3 w-3" />
            </>
          )}
        </button>
      )}
    </div>
  );
}
